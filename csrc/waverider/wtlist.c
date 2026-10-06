/* The wavetable page's lists, drawn and driven as the stock preset manager's are
 * (owner, 2026-10-07: behave like stock; measured on stock 1.11 in the emulator, PRESET >
 * MANAGE): a title band, seven rows, the highlighted row inverted, a scrollbar on the
 * right (docs/waverider-wtmenu.md).
 *
 * - LOAD and POOL: the working project's pool, shown slots 001..128. A slot names its
 *   table, reads as a row of slashes when it has none, as an empty preset slot does, or
 *   MISSING when its table was deleted (it plays Prim. until CLEAR SLOT frees it).
 * - MANAGE: every table in the +Drive store, in store order; a + marks the tables
 *   already in the working project's pool.
 * The rows are built when a list opens, from one read of the store index and of record
 * 0 (csrc/wrstore), and rebuilt after an edit.
 *
 * The keys, as stock's:
 * - YES: in LOAD, puts the highlighted slot on the active track's TBL, for the
 *   oscillator of the SYN page last shown (wtedit.c). In MANAGE and POOL, ticks or
 *   unticks the highlighted row (a check mark at its left) and moves down one.
 * - RIGHT opens the list's operations in a side panel on the right; the list narrows and
 *   its highlighted row is outlined. UP/DOWN choose, YES runs, NO or LEFT closes it.
 *   An operation acts on the ticked rows, or on the highlighted row when none is ticked:
 *   MANAGE has ADD TO POOL (one write for the set), DELETE (asked first: DELETE n? in the
 *   title, YES deletes, NO keeps), SELECT ALL, DESELECT ALL; POOL has CLEAR SLOT, SELECT
 *   ALL, DESELECT ALL; LOAD has LOAD TO TBL1 and LOAD TO TBL2.
 * - LEFT is stock's SORTING menu: none here yet, so it does nothing.
 * A result worth saying replaces the title until the next key. One subject: the lists'
 * rows, keys and drawing. */

#include "../wrstore/records.h"
#include "wtlist.h"
#include "wtedit.h"
#include "pool.h"
#include "events.h"

#define TEXT        ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545cu)
#define FILL        ((void (*)(void *, int, int, int, int, int))0x40114954u)
#define CLEAR       ((void (*)(void *, int, int))0x40114d94u)
#define SET_PIXEL   ((void (*)(void *, int, int, int))0x40113b90u)   /* (canvas, x, y, on), as page.c */
#define TITLE_FONT  0x44507ef8u
#define ROW_FONT    0x44507ee0u
#define KEY_YES     10
#define KEY_UP      11
#define KEY_NO      12
#define KEY_LEFT    13
#define KEY_DOWN    14
#define KEY_RIGHT   15
#define VISIBLE     7
#define ROW_H       8
#define NAME_LEN    16
#define PANEL_X     60          /* the side panel's left edge, as stock's */

struct row { u8 slot; u8 in_pool; char name[NAME_LEN]; };    /* slot 0xff: none; in_pool 2: its table is gone */

static struct row rows[SLOTS] __attribute__((section(".data")));
static u8 ticked[SLOTS] __attribute__((section(".data")));
static u32 count __attribute__((section(".data"))) = 0;
static u32 kind __attribute__((section(".data"))) = 0;
static u32 cursor __attribute__((section(".data"))) = 0;
static u32 top __attribute__((section(".data"))) = 0;
static u32 panel __attribute__((section(".data"))) = 0;      /* 1 while the side panel is open */
static u32 choice __attribute__((section(".data"))) = 0;
static const char *note __attribute__((section(".data"))) = 0;   /* may hold one %u: note_n */
static u32 note_n __attribute__((section(".data"))) = 0;
static u32 confirming __attribute__((section(".data"))) = 0;   /* DELETE asked, YES not yet */
/* an operation's rows and their store slots: static, off the UI task's stack */
static u8 at[SLOTS] __attribute__((section(".data")));
static u8 what[SLOTS] __attribute__((section(".data")));

enum { OP_ADD, OP_DELETE, OP_CLEAR, OP_ALL, OP_NONE, OP_TBL1, OP_TBL2 };

/* each list's operations, in the panel's order: names and codes in parallel arrays (a
 * {name, code} struct is 8 bytes, and indexing it emits a scale-8 address, which the
 * ColdFire refuses: scripts/check_coldfire.py) */
static const char *const manage_names[] = { "ADD TO POOL", "DELETE", "SELECT ALL", "DESELECT ALL" };
static const u8 manage_codes[] = { OP_ADD, OP_DELETE, OP_ALL, OP_NONE };
static const char *const pool_names[] = { "CLEAR SLOT", "SELECT ALL", "DESELECT ALL" };
static const u8 pool_codes[] = { OP_CLEAR, OP_ALL, OP_NONE };
static const char *const load_names[] = { "LOAD TO TBL1", "LOAD TO TBL2" };
static const u8 load_codes[] = { OP_TBL1, OP_TBL2 };

static u32 ops(const char *const **names, const u8 **codes)
{
    if (kind == WL_MANAGE) { *names = manage_names; *codes = manage_codes; return 4; }
    if (kind == WL_POOL) { *names = pool_names; *codes = pool_codes; return 3; }
    *names = load_names;
    *codes = load_codes;
    return 2;
}

static void copy_name(char *to, const u8 *entry)
{
    for (u32 i = 0; i < NAME_LEN - 1; i++)
        to[i] = (char)entry[E_NAME + i];
    to[NAME_LEN - 1] = 0;
}

static void say(const char *what, u32 n)
{
    note = what;
    note_n = n;
}

static void untick_all(void)
{
    for (u32 i = 0; i < SLOTS; i++)
        ticked[i] = 0;
}

/* a row worth ticking: MANAGE every row; POOL a slot with a table, or a MISSING one */
static int tickable(u32 i)
{
    return kind == WL_MANAGE || rows[i].slot != 0xff || rows[i].in_pool == 2;
}

static void build(u32 k);

void wt_list_open(u32 k)
{
    build(k);
    untick_all();
    cursor = top = 0;
    panel = 0;
    note = 0;
    confirming = 0;
}

static void build(u32 k)
{
    u8 *index = wr_store_index(), *rec = NEW(RECORD_BYTES);
    u8 member[SLOTS];
    wr_record_resolve(0, rec, index);
    for (u32 s = 0; s < SLOTS; s++)
        member[s] = 0;
    for (u32 j = 0; j < POOL_ENTRIES; j++) {
        u32 s = be16(rec + R_ENTRIES + 2 * j);
        if (s < SLOTS)
            member[s] = 1;
    }
    kind = k;
    count = 0;
    if (k == WL_MANAGE) {
        for (u32 s = 0; index && s < SLOTS; s++)
            if (index[s * ENTRY_BYTES + 1] & 1) {
                struct row *r = &rows[count++];
                r->slot = (u8)s;
                r->in_pool = member[s];
                copy_name(r->name, index + s * ENTRY_BYTES);
            }
    } else {
        for (u32 j = 0; j < POOL_ENTRIES; j++) {
            struct row *r = &rows[count++];
            u32 s = be16(rec + R_ENTRIES + 2 * j);
            int used = index && s < SLOTS && (index[s * ENTRY_BYTES + 1] & 1);
            r->slot = used ? (u8)s : 0xff;
            r->in_pool = s < SLOTS && !used ? 2 : 1;    /* 2: names a table no longer stored */
            if (used)
                copy_name(r->name, index + s * ENTRY_BYTES);
            else
                r->name[0] = 0;
        }
    }
    DELETE(rec);
    if (index)
        DELETE(index);
    if (cursor >= count)
        cursor = count ? count - 1 : 0;
}

/* the rows an operation acts on: the ticked ones, else the highlighted one -> how many */
static u32 targets(u8 *out)
{
    u32 n = 0;
    for (u32 i = 0; i < count; i++)
        if (ticked[i])
            out[n++] = (u8)i;
    if (!n && count)
        out[n++] = (u8)cursor;
    return n;
}

static void load_to(u32 osc)
{
    u32 result = rows[cursor].slot == 0xff ? WT_EMPTY : wt_tbl_load(cursor, osc);
    say(result == WT_NOT_WAVERIDER ? "NOT A WAVERIDER TRACK"
        : result == WT_EMPTY && rows[cursor].in_pool == 2 ? "ITS TABLE WAS DELETED"
        : result == WT_EMPTY ? "THIS SLOT IS EMPTY"
        : osc ? "LOADED TO TBL2" : "LOADED TO TBL1", 0);
}

static void run(u32 op)
{
    u32 n = targets(at), result, added, skipped;
    switch (op) {
    case OP_ALL:
        for (u32 i = 0; i < count; i++)
            ticked[i] = (u8)tickable(i);
        return;
    case OP_NONE:
        untick_all();
        return;
    case OP_TBL1:
    case OP_TBL2:
        load_to(op == OP_TBL2);
        return;
    case OP_DELETE:
        confirming = n;                               /* irreversible: ask first */
        say(n == 1 ? "DELETE? YES / NO" : "DELETE %u? YES / NO", n);
        return;
    case OP_ADD:
        for (u32 k = 0; k < n; k++)
            what[k] = rows[at[k]].slot;
        result = wt_pool_add_many(what, n, &added, &skipped);
        if (result == WT_FAILED)
            say("+DRIVE WRITE FAILED", 0);
        else if (result == WT_FULL)
            say(added ? "POOL FULL: %u ADDED" : "THE POOL IS FULL", added);
        else if (!added)
            say("ALREADY IN THE POOL", 0);
        else
            say(added == 1 ? "ADDED TO THE POOL" : "%u ADDED TO THE POOL", added);
        break;
    case OP_CLEAR:
        for (u32 k = 0; k < n; k++)
            what[k] = at[k];
        result = wt_pool_clear_many(what, n);
        say(result == WT_DONE ? (n == 1 ? "SLOT CLEARED" : "%u SLOTS CLEARED") : "+DRIVE WRITE FAILED", n);
        break;
    }
    untick_all();
    build(kind);
}

static void move(u32 down)
{
    if (!down && cursor)
        cursor--;
    if (down && cursor + 1 < count)
        cursor++;
    if (cursor < top)
        top = cursor;
    if (cursor >= top + VISIBLE)
        top = cursor - VISIBLE + 1;
}

u32 wt_list_key(u32 code, u32 pressed, u32 released)
{
    const char *const *names;
    const u8 *codes;
    u32 n = ops(&names, &codes);
    if (confirming) {
        if (code == KEY_YES && released) {
            u32 k = targets(at), gone = 0;
            for (u32 i = 0; i < k; i++)
                gone += wt_store_delete(rows[at[i]].slot) == WT_DONE ? 1 : 0;
            confirming = 0;
            say(gone == k ? (k == 1 ? "DELETED" : "%u DELETED") : "+DRIVE WRITE FAILED", k);
            untick_all();
            build(kind);
        } else if (code == KEY_NO && released) {
            confirming = 0;
            note = 0;
        }
        return 1;
    }
    if (pressed)
        note = 0;
    if (panel) {
        if ((code == KEY_NO || code == KEY_LEFT) && released)
            panel = 0;
        if (code == KEY_UP && pressed && choice)
            choice--;
        if (code == KEY_DOWN && pressed && choice + 1 < n)
            choice++;
        if (code == KEY_YES && released) {
            panel = 0;
            run(codes[choice]);
        }
        return 1;
    }
    if (code == KEY_RIGHT) {
        if (released && count) {
            panel = 1;
            choice = 0;
        }
        return 1;
    }
    if (code == KEY_LEFT)
        return 1;                                  /* stock's SORTING: none here yet */
    if (code == KEY_YES) {
        if (released && count) {
            if (kind == WL_LOAD)
                load_to(wr_events.shown_osc ? 1 : 0);
            else {
                if (tickable(cursor))
                    ticked[cursor] ^= 1;
                move(1);                           /* as stock: the next row */
            }
        }
        return 1;
    }
    if (code == KEY_NO)
        return released ? 0 : 1;
    if (code != KEY_UP && code != KEY_DOWN)
        return 2;                                  /* not the list's: the stock handler's */
    if (pressed && count)
        move(code == KEY_DOWN);
    return 1;
}

static const char *const titles[3] = { "LOAD WAVETABLE", "WAVETABLE MANAGER", "WAVETABLE POOL" };

/* A line one pixel wide, by single pixels: FILL grows a one-pixel rectangle in both its
 * set and its invert modes (measured in frames: a tick drawn with it came out 3 x 3 a
 * pixel, and inverting neighbours cancelled each other). */
static void line(void *canvas, int x0, int y0, int x1, int y1)
{
    for (int y = y0; y <= y1; y++)
        for (int x = x0; x <= x1; x++)
            SET_PIXEL(canvas, x, y, 1);
}

/* stock's check mark, 4 x 3, before the row's text (stock 1.11, PRESET > MANAGE) */
static void tick(void *canvas, int x, int y)
{
    line(canvas, x, y + 1, x, y + 1);
    line(canvas, x + 1, y, x + 1, y);
    line(canvas, x + 2, y + 1, x + 2, y + 1);
    line(canvas, x + 3, y + 2, x + 3, y + 2);
}

static void outline(void *canvas, int x0, int y0, int x1, int y1)
{
    line(canvas, x0, y0, x1, y0);
    line(canvas, x0, y1, x1, y1);
    line(canvas, x0, y0 + 1, x0, y1 - 1);
    line(canvas, x1, y0 + 1, x1, y1 - 1);
}

void wt_list_draw(void *canvas)
{
    CLEAR(canvas, 0, 0);
    TEXT(canvas, TITLE_FONT, 64, 58, 2, note ? note : titles[kind], note_n);
    FILL(canvas, 0, 57, 127, 63, -1);
    if (!count) {
        TEXT(canvas, ROW_FONT, 64, 28, 2, kind == WL_MANAGE ? "NO TABLES ON THE +DRIVE" : "EMPTY");
        return;
    }
    for (u32 i = 0; i < VISIBLE && top + i < count; i++) {
        const struct row *r = &rows[top + i];
        int y = 48 - (int)i * ROW_H;
        if (ticked[top + i])
            tick(canvas, 3, y);
        if (kind == WL_MANAGE)
            TEXT(canvas, ROW_FONT, 9, y, 0, "%c %s", r->in_pool ? '+' : ' ', r->name);
        else if (r->in_pool == 2)
            TEXT(canvas, ROW_FONT, 9, y, 0, "%03u MISSING", top + i + 1);
        else if (r->slot == 0xff)
            TEXT(canvas, ROW_FONT, 9, y, 0, "%03u //////////", top + i + 1);
        else
            TEXT(canvas, ROW_FONT, 9, y, 0, "%03u %s", top + i + 1, r->name);
        if (top + i == cursor && !panel)
            FILL(canvas, 0, y - 1, 120, y + 6, -1);
    }
    /* the scrollbar: a track, and a thumb for the rows shown */
    FILL(canvas, 123, 0, 126, 55, -1);
    {
        int span = 54, thumb = count > VISIBLE ? span * VISIBLE / (int)count : span;
        int at = count > VISIBLE ? (span - thumb) * (int)top / (int)(count - VISIBLE) : 0;
        if (thumb < 3)
            thumb = 3;
        FILL(canvas, 124, 54 - at - thumb + 1, 125, 54 - at, -1);
    }
    if (panel) {
        const char *const *names;
        const u8 *codes;
        u32 n = ops(&names, &codes);
        int y = 48 - (int)(cursor - top) * ROW_H;
        outline(canvas, 0, y - 1, PANEL_X - 2, y + 6);    /* the highlighted row, outlined */
        FILL(canvas, PANEL_X - 1, 0, 127, 56, 0);         /* the panel over the list's right */
        line(canvas, PANEL_X - 1, 0, PANEL_X - 1, 56);    /* its edge, one pixel as stock's */
        for (u32 i = 0; i < n; i++) {
            int iy = 48 - (int)i * ROW_H;
            TEXT(canvas, ROW_FONT, PANEL_X + 2, iy, 0, names[i]);
            if (i == choice)
                FILL(canvas, PANEL_X, iy - 1, 127, iy + 6, -1);
        }
    }
}
