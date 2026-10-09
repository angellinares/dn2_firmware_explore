/* Waverider's table pool: the store's tables (csrc/wrstore) into the DSP's load area,
 * so TBL can play them (docs/drive-load-command.md, "The pool").
 *
 * From the UI task, once a pass (wr_drive_poll). Five seconds after boot, and again
 * whenever the store has changed (wr_store.changes: the /waverider route commits a
 * write or a delete), it fills the pool:
 * 1. reads the store's current index, and the working project's pool list (record 0,
 *    csrc/wrstore/records.c): its stored record, or with none (or the automatic
 *    flag) the automatic pool, every playable slot in slot order, up to POOL_SLOTS;
 * 2. pool entry j is the list's entry j, when that store slot holds a table the DSP
 *    plays (wr_store_playable: 1..64 waves of 64..4096 int16); otherwise entry j is
 *    empty and plays Prim. (pool.asm), as a slot past the count does;
 * 3. clears the request directory's magic, so the DSP stops building from tables
 *    about to be rewritten;
 * 4. sends each table as stored, slot n's sectors, to entry j's place in the load area
 *    (loader.c), and from the same chunks makes the page's display spans (as
 *    dnfw.waverider.wave.pool_spans);
 * 5. sends the request directory (count, generation, each entry's frames and points),
 *    its magic last. The DSP then builds each entry's levels in its idle time
 *    (build3.asm) and names an entry for pool.asm only once it is whole; an entry being
 *    rebuilt plays Prim. meanwhile, never half a table.
 * The page then offers TBL slots 2 .. 1 + count (wr_pool.count, once ready): count is
 * the last entry in use + 1, so a gap shows as an unnamed slot.
 *
 * Not yet: a table's own hash is not checked here (the route checked it when it was
 * written), and a refill sends every table again, changed or not. */

#include "loader.h"
#include "../wrstore/records.h"
#include "pool.h"
#include "events.h"

#define TICKS        (*(volatile u32 *)0x466758B0u)   /* the UI's 120 Hz tick */
#define TICK_HZ      120
#define START        (5 * TICK_HZ)
#define DIR_OFFSET   0u                                /* the request directory, the load area's first 4 KB (0x807ff000) */
#define TABLE_OFFSET 0x1000u                           /* entry j's table at offset TABLE_OFFSET + j x RAW_BYTES */
#define RAW_BYTES    0x80000u                          /* 512 KiB: a store slot */
#define POOL_MAGIC   0x57525033u                       /* 'WRP3' (dnfw.waverider.dsp.POOL_MAGIC) */
#define SHOWN        16                                /* the page's frames of a table (WR_POOL_SPANS) */

enum { WAITING, FILLING, DIRECTORY, READY, CLEARING, FAILED, MAGIC };

volatile struct wr_pool wr_pool __attribute__((section(".data"))) =
    { 0x5752504Cu, WAITING, 0, 0, 0, 0, 0, { 0 }, { { 0 } } };

/* the request directory from its word 1 (count, generation, 0, a word per entry), as the
 * ColdFire sends it: each DSP word as two 16-bit halves, low first; then its magic */
#define BODY_WORDS (3 + POOL_SLOTS)
static u16 directory[2 * BODY_WORDS] __attribute__((section(".data"))) = { 0 };
static u16 magic[2] __attribute__((section(".data"))) = { 0 };
static u32 next __attribute__((section(".data"))) = 0;     /* the next pool entry to send */
static u32 filling __attribute__((section(".data"))) = 0;  /* entries found this fill */
#define EMPTY_SLOT 0xFFu
static u8 slots[POOL_SLOTS] __attribute__((section(".data"))) = { 0 };   /* EMPTY_SLOT: none */
static char names[POOL_SLOTS][POOL_NAME] __attribute__((section(".data"))) = { { 0 } };
static u8 waves_of[POOL_SLOTS] __attribute__((section(".data"))) = { 0 };
static u16 points_of[POOL_SLOTS] __attribute__((section(".data"))) = { 0 };
/* the table loading now: which shown frames each of its frames fills (first, last + 1) */
static u8 shown_from[64] __attribute__((section(".data"))) = { 0 };
static u8 shown_to[64] __attribute__((section(".data"))) = { 0 };

/* shown frame d is the table's frame nearest d x (F - 1) / 15, the frame a POS of d plays
 * (dnfw.waverider.table3.position) */
static void shown_frames(u32 waves)
{
    for (u32 f = 0; f < 64; f++)
        shown_from[f] = shown_to[f] = 0;
    for (u32 d = 0; d < SHOWN; d++) {
        u32 f = (2 * d * (waves - 1) + SHOWN - 1) / (2 * (SHOWN - 1));
        if (shown_to[f] == shown_from[f])
            shown_from[f] = (u8)d;
        shown_to[f] = (u8)(d + 1);
    }
}

static int to_byte(int v)
{
    int b = (v * 127 + (v >= 0 ? 16383 : -16383)) / 32767;     /* to nearest, halves away from 0 */
    return b > 127 ? 127 : b < -127 ? -127 : b;
}

static void put(signed char (*frame)[WR_POOL_WIDTH], u32 c, int b)
{
    if (b < frame[0][c]) frame[0][c] = (signed char)b;
    if (b > frame[1][c]) frame[1][c] = (signed char)b;
}

/* loader.c's callback: a chunk of a table, its samples big-endian as the store has them.
 * Column c of a frame of N points covers points c N / 96 .. (c + 1) N / 96
 * (dnfw.waverider.wave): a point's column is the last c with c N / 96 <= p. */
static void seen(u32 dest, const u16 *w, u32 bytes)
{
    u32 j, first, n;
    if (dest < TABLE_OFFSET)
        return;
    dest -= TABLE_OFFSET;
    j = dest / RAW_BYTES;
    if (j >= POOL_SLOTS || !points_of[j])
        return;
    n = points_of[j];
    first = dest % RAW_BYTES / 2;
    for (u32 i = 0; i < bytes / 2; i++) {
        u32 k = first + i, f = k / n, p = k % n, c;
        int b;
        if (f >= waves_of[j] || shown_from[f] == shown_to[f])
            continue;                              /* past the table, or a frame not shown */
        c = (WR_POOL_WIDTH * (p + 1) + n - 1) / n - 1;
        if (c > WR_POOL_WIDTH - 1)
            c = WR_POOL_WIDTH - 1;
        b = to_byte((short)w[i]);
        for (u32 d = shown_from[f]; d < shown_to[f]; d++) {
            signed char (*frame)[WR_POOL_WIDTH] = WR_POOL_SPANS[j][d];
            put(frame, c, b);
            if (c > 0 && c * n / WR_POOL_WIDTH == p)
                put(frame, c - 1, b);              /* a column's first point ends the one before */
            if (p == 0)
                put(frame, WR_POOL_WIDTH - 1, b);  /* the last column wraps to point 0 */
        }
    }
}

static void clear_spans(u32 j)
{
    for (u32 f = 0; f < SHOWN; f++)
        for (u32 c = 0; c < WR_POOL_WIDTH; c++) {
            WR_POOL_SPANS[j][f][0][c] = 127;
            WR_POOL_SPANS[j][f][1][c] = -127;
        }
}

static void begin(void)
{
    u8 *index, *rec = NEW(RECORD_BYTES);
    wr_pool.changes_seen = wr_store.changes;
    wr_pool.fills++;
    index = wr_store_index();
    filling = next = 0;
    wr_record_resolve(0, rec, index);
    for (u32 j = 0; j < POOL_SLOTS; j++) {
        u32 n = be16(rec + R_ENTRIES + 2 * j);
        int ok = index && n < SLOTS && wr_store_playable(index + n * ENTRY_BYTES, n);
        slots[j] = ok ? (u8)n : EMPTY_SLOT;
        waves_of[j] = ok ? (u8)be16(index + n * ENTRY_BYTES + E_WAVES) : 0;
        points_of[j] = ok ? (u16)be16(index + n * ENTRY_BYTES + E_POINTS) : 0;
        for (u32 i = 0; i < POOL_NAME; i++)
            names[j][i] = ok && i < POOL_NAME - 1 ? (char)index[n * ENTRY_BYTES + E_NAME + i] : 0;
        if (ok)
            filling = j + 1;
    }
    DELETE(rec);
    if (index)
        DELETE(index);
    wr_pool.generation = index ? wr_store.generation : 0;
    wr_pool.state = CLEARING;            /* no store: an empty directory, count 0 */
}

static void send_directory(void)
{
    u32 words[3] = { POOL_SLOTS, wr_pool.fills, 0 };
    for (u32 k = 0; k < BODY_WORDS; k++) {
        u32 v = k < 3 ? words[k]
              : (k - 3 < filling && slots[k - 3] != EMPTY_SLOT ? waves_of[k - 3] | (u32)points_of[k - 3] << 16 : 0);
        directory[2 * k] = (u16)v;
        directory[2 * k + 1] = (u16)(v >> 16);
    }
    if (wr_load_memory(directory, sizeof directory, DIR_OFFSET + 4))
        wr_pool.state = MAGIC;
}

void wr_drive_poll(void)
{
    u32 now = TICKS;
    wr_load_poll();
    if (wr_load.failed) {
        wr_pool.state = FAILED;
        return;
    }
    switch (wr_pool.state) {
    case WAITING:
        if (now >= START)
            begin();
        break;
    case READY:
        if (wr_store.changes != wr_pool.changes_seen && wr_load_idle())
            begin();
        break;
    case CLEARING:                       /* the DSP stops building before a table is rewritten */
        magic[0] = magic[1] = 0;
        if (wr_load_idle() && wr_load_memory(magic, sizeof magic, DIR_OFFSET))
            wr_pool.state = FILLING;
        break;
    case FILLING:
        if (!wr_load_idle())
            break;
        if (next < filling) {
            if (slots[next] == EMPTY_SLOT) {
                clear_spans(next);
                wr_pool.slot_of[next] = EMPTY_SLOT;
                next++;
                break;
            }
            clear_spans(next);
            shown_frames(waves_of[next]);
            if (wr_load_extent(REGION + DATA_START + slots[next] * SLOT_SECTORS,
                               (2u * waves_of[next] * points_of[next] + 511) / 512,
                               TABLE_OFFSET + next * RAW_BYTES, seen)) {
                wr_pool.slot_of[next] = slots[next];
                next++;
            }
        } else {
            send_directory();
        }
        break;
    case MAGIC:                          /* the directory whole: its magic, last */
        if (wr_load_idle()) {
            magic[0] = (u16)POOL_MAGIC;
            magic[1] = (u16)(POOL_MAGIC >> 16);
            if (wr_load_memory(magic, sizeof magic, DIR_OFFSET))
                wr_pool.state = DIRECTORY;
        }
        break;
    case DIRECTORY:
        if (wr_load_idle()) {
            for (u32 j = 0; j < filling; j++)
                for (u32 i = 0; i < POOL_NAME; i++)
                    wr_pool.names[j][i] = names[j][i];
            wr_pool.count = filling;
            wr_pool.state = READY;
        }
        break;
    }
    wr_load_poll();
}

/* What the page finds at the chunk's first bytes (pool.h). */
const struct wr_drive_head wr_drive_head __attribute__((section(".text.entry"))) =
    { WR_DRIVE_MAGIC, wr_drive_poll, &wr_pool, &wr_events };
