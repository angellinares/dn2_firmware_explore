/* The wavetable page's lists, drawn as the stock PRESET POOL list is: a title band, seven
 * rows, the selected row inverted, a scrollbar on the right (docs/waverider-wtmenu.md).
 *
 * - LOAD and POOL: the working project's pool, shown slots 001..127. A slot names its
 *   table, or reads as a row of slashes when it has none, as an empty preset slot does.
 * - MANAGE: every table in the +Drive store, in store order; a + marks the tables
 *   already in the working project's pool.
 * The rows are built when a list opens, from one read of the store index and of record
 * 0 (csrc/wrstore), and rebuilt after an edit.
 *
 * FUNC opens a popup with the highlighted row's actions, as the stock managers do:
 * MANAGE has ADD TO POOL, POOL has CLEAR SLOT (wtedit.c). UP/DOWN choose, YES runs, NO
 * closes it. A result worth saying (already in the pool, the pool full) replaces the
 * title until the next key. One subject: the lists' rows, keys and drawing. */

#include "../wrstore/records.h"
#include "wtlist.h"
#include "wtedit.h"

#define TEXT        ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545cu)
#define FILL        ((void (*)(void *, int, int, int, int, int))0x40114954u)
#define CLEAR       ((void (*)(void *, int, int))0x40114d94u)
#define TITLE_FONT  0x44507ef8u
#define ROW_FONT    0x44507ee0u
#define KEY_YES     10
#define KEY_FUNC    17
#define KEY_UP      11
#define KEY_NO      12
#define KEY_DOWN    14
#define VISIBLE     7
#define ROW_H       8
#define NAME_LEN    16

struct row { u8 slot; u8 in_pool; char name[NAME_LEN]; };    /* slot 0xff: none */

static struct row rows[SLOTS] __attribute__((section(".data")));
static u32 count __attribute__((section(".data"))) = 0;
static u32 kind __attribute__((section(".data"))) = 0;
static u32 cursor __attribute__((section(".data"))) = 0;
static u32 top __attribute__((section(".data"))) = 0;
static u32 popup __attribute__((section(".data"))) = 0;      /* 1 while it is open */
static u32 choice __attribute__((section(".data"))) = 0;
static const char *note __attribute__((section(".data"))) = 0;

/* each list's actions, in the popup's order */
static const char *const manage_actions[] = { "ADD TO POOL" };
static const char *const pool_actions[] = { "CLEAR SLOT" };

static u32 actions(const char *const **names)
{
    if (kind == WL_MANAGE) { *names = manage_actions; return 1; }
    if (kind == WL_POOL) { *names = pool_actions; return 1; }
    *names = 0;
    return 0;
}

static void copy_name(char *to, const u8 *entry)
{
    for (u32 i = 0; i < NAME_LEN - 1; i++)
        to[i] = (char)entry[E_NAME + i];
    to[NAME_LEN - 1] = 0;
}

static void build(u32 k);

void wt_list_open(u32 k)
{
    build(k);
    cursor = top = 0;
    popup = 0;
    note = 0;
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
            r->in_pool = 1;
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

static void run(u32 action)
{
    const struct row *r = &rows[cursor];
    u32 result = WT_FAILED;
    (void)action;                                  /* one action per list so far */
    if (kind == WL_MANAGE)
        result = wt_pool_add(r->slot);
    else if (kind == WL_POOL)
        result = r->slot == 0xff ? WT_DONE : wt_pool_clear(cursor);
    note = result == WT_ALREADY ? "ALREADY IN THE POOL"
         : result == WT_FULL ? "THE POOL IS FULL"
         : result == WT_FAILED ? "+DRIVE WRITE FAILED" : 0;
    build(kind);
}

u32 wt_list_key(u32 code, u32 pressed, u32 released)
{
    const char *const *names;
    u32 n = actions(&names);
    if (pressed)
        note = 0;
    if (popup) {
        if (code == KEY_NO && released)
            popup = 0;
        if (code == KEY_UP && pressed && choice)
            choice--;
        if (code == KEY_DOWN && pressed && choice + 1 < n)
            choice++;
        if (code == KEY_YES && released) {
            popup = 0;
            run(choice);
        }
        return 1;
    }
    if (code == KEY_FUNC && released && n && count) {
        popup = 1;
        choice = 0;
        return 1;
    }
    if (code == KEY_NO)
        return released ? 0 : 1;
    if ((code == KEY_UP || code == KEY_DOWN) && pressed && count) {
        if (code == KEY_UP && cursor)
            cursor--;
        if (code == KEY_DOWN && cursor + 1 < count)
            cursor++;
        if (cursor < top)
            top = cursor;
        if (cursor >= top + VISIBLE)
            top = cursor - VISIBLE + 1;
    }
    return 1;
}

static const char *const titles[3] = { "LOAD WAVETABLE", "WAVETABLE MANAGER", "WAVETABLE POOL" };

void wt_list_draw(void *canvas)
{
    CLEAR(canvas, 0, 0);
    TEXT(canvas, TITLE_FONT, 64, 58, 2, note ? note : titles[kind]);
    FILL(canvas, 0, 57, 127, 63, -1);
    if (!count) {
        TEXT(canvas, ROW_FONT, 64, 28, 2, kind == WL_MANAGE ? "NO TABLES ON THE +DRIVE" : "EMPTY");
        return;
    }
    for (u32 i = 0; i < VISIBLE && top + i < count; i++) {
        const struct row *r = &rows[top + i];
        int y = 48 - (int)i * ROW_H;
        if (kind == WL_MANAGE)
            TEXT(canvas, ROW_FONT, 3, y, 0, "%c %s", r->in_pool ? '+' : ' ', r->name);
        else if (r->slot == 0xff)
            TEXT(canvas, ROW_FONT, 3, y, 0, "%03u //////////", top + i + 1);
        else
            TEXT(canvas, ROW_FONT, 3, y, 0, "%03u %s", top + i + 1, r->name);
        if (top + i == cursor)
            FILL(canvas, 1, y - 1, 120, y + 6, -1);
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
    if (popup) {
        const char *const *names;
        u32 n = actions(&names);
        int hi = 44, lo = hi - (int)n * (ROW_H + 2) - 7;
        FILL(canvas, 18, lo - 1, 110, hi + 1, 0);  /* a white margin, then the box's border */
        FILL(canvas, 20, lo, 108, hi, 1);
        FILL(canvas, 21, lo + 1, 107, hi - 1, 0);
        for (u32 i = 0; i < n; i++) {
            int y = hi - 11 - (int)i * (ROW_H + 2);
            TEXT(canvas, ROW_FONT, 26, y, 0, names[i]);
            if (i == choice)
                FILL(canvas, 23, y - 2, 105, y + 7, -1);
        }
    }
}
