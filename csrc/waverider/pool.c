/* Waverider's table pool: the store's tables (csrc/wrstore) into the DSP's load area,
 * so TBL can play them (docs/drive-load-command.md, "The pool").
 *
 * From the UI task, once a pass (wr_drive_poll). Five seconds after boot, and again
 * whenever the store has changed (wr_store.changes: the /waverider route commits a
 * write or a delete), it fills the pool:
 * 1. reads the store's current index, and the working project's pool list (record 0,
 *    csrc/wrstore/records.c): its stored record, or with none (or the automatic
 *    flag) the automatic pool, every playable slot in slot order, up to POOL_SLOTS;
 * 2. pool entry j is the list's entry j, when that store slot holds a table with the
 *    reader's geometry (16 waves of 512 int16, 16 KiB); otherwise entry j is empty
 *    and plays Prim. (pool.asm), as a slot past the count does;
 * 3. sends each table, slot n's sectors, to pool address j (loader.c), and from the
 *    same chunks makes the page's display spans (as dnfw.waverider.wave.pool_spans);
 * 4. sends the pool directory last, so the DSP plays none of it before all of it is
 *    there (pool.asm reads it: magic, count, the entries' DDR addresses, 0 empty).
 * The page then offers TBL slots 2 .. 1 + count (wr_pool.count, once ready): count is
 * the last entry in use + 1, so a gap shows as an unnamed slot.
 *
 * Not yet: a table's own hash is not checked here (the route checked it when it was
 * written), and a refill rewrites tables in place while the old directory still
 * names them, so a voice on a moved table glitches until the new directory lands. */

#include "loader.h"
#include "../wrstore/records.h"
#include "pool.h"
#include "events.h"

#define TICKS        (*(volatile u32 *)0x466758B0u)   /* the UI's 120 Hz tick */
#define TICK_HZ      120
#define START        (5 * TICK_HZ)
#define AREA         0x807FF000u                       /* the load area's first byte in DDR */
#define DIR_OFFSET   0u                                /* the directory, the area's first 4 KB */
#define TABLE_OFFSET 0x1000u                           /* pool table j at offset TABLE_OFFSET + j x 16 KB */
#define TABLES       (AREA + TABLE_OFFSET)             /* 0x80800000 */
#define TABLE_BYTES  0x4000u                           /* 16 x 512 int16 */
#define POOL_MAGIC   0x57525031u                       /* 'WRP1' */

enum { WAITING, FILLING, DIRECTORY, READY, FAILED = 5 };

volatile struct wr_pool wr_pool __attribute__((section(".data"))) =
    { 0x5752504Cu, WAITING, 0, 0, 0, 0, 0, { 0 }, { { 0 } } };

/* the directory as the ColdFire sends it: each DSP word as two 16-bit halves, low first */
static u16 directory[2 * (2 + POOL_SLOTS)] __attribute__((section(".data"))) = { 0 };
static u32 next __attribute__((section(".data"))) = 0;     /* the next pool entry to send */
static u32 filling __attribute__((section(".data"))) = 0;  /* entries found this fill */
#define EMPTY_SLOT 0xFFu
static u8 slots[POOL_SLOTS] __attribute__((section(".data"))) = { 0 };   /* EMPTY_SLOT: none */
static char names[POOL_SLOTS][POOL_NAME] __attribute__((section(".data"))) = { { 0 } };

static const u16 *col_start(void)
{
    /* column c covers points c*512/96 .. (c+1)*512/96 (dnfw.waverider.wave) */
    static u16 at[WR_POOL_WIDTH + 1] __attribute__((section(".data"))) = { 0 };
    if (!at[WR_POOL_WIDTH])
        for (u32 c = 0; c <= WR_POOL_WIDTH; c++)
            at[c] = (u16)(c * 512 / WR_POOL_WIDTH);
    return at;
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

/* loader.c's callback: a chunk of a table, its samples big-endian as the store has them */
static void seen(u32 dest, const u16 *w, u32 bytes)
{
    const u16 *at = col_start();
    u32 j, first;
    if (dest < TABLE_OFFSET)
        return;
    dest -= TABLE_OFFSET;
    j = dest / TABLE_BYTES;
    first = dest % TABLE_BYTES / 2;
    if (j >= POOL_SLOTS)
        return;
    for (u32 i = 0; i < bytes / 2; i++) {
        u32 k = first + i, f = k / 512, p = k % 512, c = p * WR_POOL_WIDTH / 512;
        signed char (*frame)[WR_POOL_WIDTH] = WR_POOL_SPANS[j][f];
        int b = to_byte((short)w[i]);
        while (c + 1 < WR_POOL_WIDTH && at[c + 1] <= p) c++;
        while (c > 0 && at[c] > p) c--;
        put(frame, c, b);
        if (p == at[c] && c > 0)
            put(frame, c - 1, b);                  /* a column's first point ends the one before */
        if (p == 0)
            put(frame, WR_POOL_WIDTH - 1, b);      /* the last column wraps to point 0 */
    }
}

static void clear_spans(u32 j)
{
    for (u32 f = 0; f < 16; f++)
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
        for (u32 i = 0; i < POOL_NAME; i++)
            names[j][i] = ok && i < POOL_NAME - 1 ? (char)index[n * ENTRY_BYTES + E_NAME + i] : 0;
        if (ok)
            filling = j + 1;
    }
    DELETE(rec);
    if (index)
        DELETE(index);
    wr_pool.generation = index ? wr_store.generation : 0;
    wr_pool.state = FILLING;             /* no store: an empty directory, count 0 */
}

static void send_directory(void)
{
    u32 words[2] = { POOL_MAGIC, POOL_SLOTS };
    for (u32 k = 0; k < 2 + POOL_SLOTS; k++) {
        u32 v = k < 2 ? words[k]
              : (k - 2 < filling && slots[k - 2] != EMPTY_SLOT ? TABLES + (k - 2) * TABLE_BYTES : 0);
        directory[2 * k] = (u16)v;
        directory[2 * k + 1] = (u16)(v >> 16);
    }
    if (wr_load_memory(directory, sizeof directory, DIR_OFFSET))
        wr_pool.state = DIRECTORY;
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
            if (wr_load_extent(REGION + DATA_START + slots[next] * SLOT_SECTORS,
                               TABLE_BYTES / 512, TABLE_OFFSET + next * TABLE_BYTES, seen)) {
                wr_pool.slot_of[next] = slots[next];
                next++;
            }
        } else {
            send_directory();
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
