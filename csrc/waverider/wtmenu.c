/* The wavetable page of the PRESET/KIT menu: page 2, after PRESET/KIT again (layout A,
 * the owner, 2026-10-06; docs/waverider-wtmenu.md).
 *
 * The stock PresetKitMenuView (vtable 0x401e6da0) stays the view. Three of its vtable
 * slots point here instead, and each falls through to stock on page 1:
 * - the key handler (slot at 0x401e6db0, stock 0x4008c78e(view, event)). On page 1 the
 *   PRESET/KIT release, which stock answers by closing the menu, turns page 2 on. On
 *   page 2, UP and DOWN move the cursor, and PRESET/KIT or NO close the menu as stock
 *   does;
 * - the redraw (slot at 0x401e6db8, stock 0x4008a5ec(view, canvas)): page 2 is drawn
 *   with the stock primitives, at the stock page's coordinates, so it reads as its twin;
 * - the LED callback (LedHandler slot at 0x401e6e54, stock thunk 0x4008abec), which
 *   runs every frame while the menu is open. A gap in it means the menu was closed and
 *   opened again, so the next open starts on page 1.
 * The right column shows the pool at a glance: tables in the working project's pool,
 * the free slots, and the tables on the +Drive the DSP can play.
 *
 * One subject: page 2's menu. The lists it opens are not built yet. */

#include "../wrstore/records.h"
#include "pool.h"

extern volatile struct wr_pool wr_pool;                  /* pool.c */

#define TICKS       (*(volatile u32 *)0x466758B0u)
#define STOCK_KEY   ((u32 (*)(void *, void *))0x4008c78eu)
#define STOCK_DRAW  ((void (*)(void *, void *))0x4008a5ecu)
#define KEY_CODE    ((u32 (*)(void *))0x40116018u)
#define KEY_PRESS   ((u32 (*)(void *))0x40116070u)       /* -> bool, in d0's low byte */
#define KEY_RELEASE ((u32 (*)(void *))0x40116040u)
#define SET_DIRTY   ((void (*)(void *))0x4011c7bau)       /* the view: redraw it (as stock after a cursor move) */
#define CLEAR       ((void (*)(void *, int, int))0x40114d94u)
#define TEXT        ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545cu)
#define VLINE       ((void (*)(void *, int, int, int, int))0x40114066u)
#define FILL        ((void (*)(void *, int, int, int, int, int))0x40114954u)
#define BLIT        ((void (*)(void *, u32, int, int, int))0x401157fcu)
#define FONT        0x44507ef8u                          /* the PRESET/KIT page's */
#define ICON_LOAD   0x44646464u
#define ICON_MANAGE 0x44646378u
#define ICON_POOL   0x44646a90u
#define KEY_PRESET  7
#define KEY_YES     10
#define KEY_UP      11
#define KEY_NO      12
#define KEY_DOWN    14
#define GAP         12                                   /* ticks without an LED call: closed */
#define ITEMS       3

struct wr_wtmenu { u32 magic, page, cursor, opened, seen, drive_tables; };
volatile struct wr_wtmenu wr_wtmenu __attribute__((section(".data"))) =
    { 0x57524d4eu, 0, 0, 0, 0, 0 };

void wr_wt_led_hook(void);

/* the menu was closed since the last frame: it opens on page 1 */
static void freshen(void)
{
    if (TICKS - wr_wtmenu.seen > GAP)
        wr_wtmenu.page = 0;
}

static u32 playable_on_drive(void)
{
    u8 *index = wr_store_index();
    u32 n = 0;
    for (u32 s = 0; index && s < SLOTS; s++)
        n += wr_store_playable(index + s * ENTRY_BYTES, s) ? 1 : 0;
    if (index)
        DELETE(index);
    return n;
}

u32 wr_wt_key(void *view, void *event)
{
    u32 code = KEY_CODE(event);
    freshen();
    if (!wr_wtmenu.page) {
        if (code == KEY_PRESET && (KEY_RELEASE(event) & 0xff)) {
            wr_wtmenu.page = 1;
            wr_wtmenu.cursor = 0;
            wr_wtmenu.opened++;
            wr_wtmenu.drive_tables = playable_on_drive();
            SET_DIRTY(view);
            return 1;
        }
        return STOCK_KEY(view, event);
    }
    switch (code) {
    case KEY_PRESET:
    case KEY_NO:
        if (KEY_RELEASE(event) & 0xff)
            wr_wtmenu.page = 0;
        return STOCK_KEY(view, event);       /* stock closes the menu on these */
    case KEY_UP:
    case KEY_DOWN:
        if (KEY_PRESS(event) & 0xff) {
            u32 c = wr_wtmenu.cursor;
            wr_wtmenu.cursor = code == KEY_UP ? (c ? c - 1 : 0) : (c + 1 < ITEMS ? c + 1 : c);
            SET_DIRTY(view);
        }
        return 1;
    case KEY_YES:
        return 1;                            /* the lists come next */
    default:
        return 1;                            /* page 1's own keys mean nothing here */
    }
}

static const char *const labels[ITEMS] = { "LOAD", "MANAGE", "POOL" };
static const u32 icons[ITEMS] = { ICON_LOAD, ICON_MANAGE, ICON_POOL };
/* the stock page's rows: text baseline, icon, and the highlight's bottom and top */
static const signed char text_y[ITEMS] = { 44, 31, 18 };
static const signed char icon_y[ITEMS] = { 42, 29, 16 };
static const signed char sel_lo[ITEMS] = { 41, 28, 15 };
static const signed char sel_hi[ITEMS] = { 51, 38, 25 };

#define DIGIT_W 5                                        /* FONT's advance, measured on screen */

/* N right-aligned so its last digit ends at x RIGHT */
static void number_right(void *canvas, int right, int y, u32 n)
{
    int digits = n >= 100 ? 3 : n >= 10 ? 2 : 1;
    TEXT(canvas, FONT, right - digits * DIGIT_W, y, 0, "%u", n);
}

static u32 in_pool(void)
{
    u32 n = 0;
    if (wr_pool.state != 3)
        return 0;
    for (u32 j = 0; j < wr_pool.count && j < POOL_SLOTS; j++)
        n += wr_pool.slot_of[j] != 0xff ? 1 : 0;
    return n;
}

void wr_wt_draw(void *view, void *canvas)
{
    u32 used;
    freshen();
    if (!wr_wtmenu.page) {
        STOCK_DRAW(view, canvas);
        return;
    }
    used = in_pool();
    CLEAR(canvas, 0, 0);
    TEXT(canvas, FONT, 32, 58, 2, "WAVETABLE");
    TEXT(canvas, FONT, 96, 58, 2, "POOL");
    VLINE(canvas, 64, 58, 62, 1);
    FILL(canvas, 0, 57, 127, 63, -1);
    VLINE(canvas, 64, 1, 55, 1);
    for (u32 i = 0; i < ITEMS; i++) {
        BLIT(canvas, icons[i], 9, icon_y[i], 0);
        TEXT(canvas, FONT, 22, text_y[i], 0, labels[i]);
    }
    FILL(canvas, 7, sel_lo[wr_wtmenu.cursor], 58, sel_hi[wr_wtmenu.cursor], -1);
    TEXT(canvas, FONT, 70, 44, 0, "IN POOL");
    number_right(canvas, 122, 44, used);
    TEXT(canvas, FONT, 70, 31, 0, "FREE");
    number_right(canvas, 122, 31, POOL_SLOTS - used);
    TEXT(canvas, FONT, 70, 18, 0, "+DRIVE");
    number_right(canvas, 122, 18, wr_wtmenu.drive_tables);
}

/* The LED callback: note the frame, then the stock thunk with its arguments as they are */
__asm__(
"	.section .text.wr_wt_led,\"ax\",@progbits\n"
"	.globl	wr_wt_led_hook\n"
"wr_wt_led_hook:\n"
"	move.l	0x466758b0,%d0\n"               /* d0 is free at a call's entry */
"	move.l	%d0,wr_wtmenu+16\n"
"	jmp	0x4008abec\n"
"	.text\n");
