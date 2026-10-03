/* Waverider's SYN page (M8.1): the wave across the middle, the controls in two
 * slim strips around it.
 *
 * The layout is Tonverk's Wavefinder page (User Manual OS 1.4.1, p. 94), on a
 * screen of the same size, drawn with our own widgets: encoders A..D are a strip
 * above the wave, E..H a strip below it, and each control is its label with a
 * small indicator, not a dial. So all eight controls of an oscillator fit on one
 * page, and the wave is on every page. `docs/waverider-m7-pages.md`, "M8.1".
 *
 * Entered from `wr_grid` (dnfw.waverider.pages) in place of the stock grid
 * `0x40017428(view, canvas)`, on a Waverider track only. It keeps the grid's own
 * tail: the level meter on the left (`view->vtable[184]`) and the page dots on
 * the right (`0x4006598a`). The encoders, the value line in the header, p-locks
 * and SAVE/LOAD are untouched: they go through the page descriptor's record ids,
 * which stay WaveTone's.
 *
 * Coordinates are the canvas's own: 128 x 64, y counting up from the bottom
 * edge (the SYN page's blits place cell row 0 at y 34..51). The header takes
 * the top ten rows, the level meter and track box the left 18 columns.
 *
 * One subject: drawing the page. What the controls are is `wr_gen.h`, generated
 * from dnfw.waverider.pages and .wave.
 */
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned char u8;

#define GET_VALUE  ((int (*)(void *, u32, u8 *))0x4006538E)   /* (view, id, &flag) */
#define SET_PIXEL  ((void (*)(void *, int, int, int))0x40113B90)  /* (canvas, x, y, on) */
#define TEXT       ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545C)
#define PAGE_COUNT ((int (*)(void *))0x400173CA)
#define PAGE_DOTS  ((void (*)(void *, void *, int, int, int))0x4006598A)
#define IS_DIRTY   ((int (*)(void *))0x4011D2F4u)               /* screen: a redraw due? */
#define FONT       0x44507ED8u                                  /* the grid's label font */
#define CENTRED    2                                            /* TEXT flag: x is the centre */

/* a parameter record: +8 min, +12 max, +16 default (TUN1: 0x400, 0x7c00, 0x4000) */
#define RECORD(id) ((const int *)(0x401F7F94u + 60u * (id)))

/* {min, max, default}: the record's, or Waverider's own for the controls it steps
 * itself (M10b, `pages.RANGES`: MOVE 0..4, TRIG 0..1), as wr_range answers the
 * firmware's limits getter on a Waverider track */
static const int *limits(u32 id)
{
    for (int k = 0; k < WR_RANGES; k++)
        if ((u32)wr_ranges[k][0] == id)
            return &wr_ranges[k][1];
    return RECORD(id) + 2;
}

/* the strips: four columns of 25 across x 22..121 */
#define COL0  22
#define COLW  25
#define TOP_LABEL_Y 46
#define TOP_BAR_Y   43
#define BOT_BAR_Y   9
#define BOT_LABEL_Y 1
#define BAR_HALF    10

/* the wave, and the position bar under it */
#define WAVE_X  24
#define WAVE_CY 28
#define WAVE_AMP 11
#define POS_Y   15
#define CURSOR_Y (POS_Y - 2)    /* the LFO's position cursor: under the bar (owner) */
#define MARK    3

#ifndef WR_MARKERS
#define WR_MARKERS 1          /* the modulation markers and the redraw they need */
#endif

#ifdef WR_PROBE
/* Measurement builds only (scripts/build_modview_probe.py; tools/dn2modview.py reads
 * this over the probe's PEEK). DTCN0 is the free-running timer the probe also reads
 * (132 MHz on the instrument), so `ticks` over `draws` is the time one page draw
 * takes, and `marker_ticks` the part the markers take. */
#define DTCN0   (*(volatile u32 *)0xFC07000Cu)
struct wr_probe { u32 magic, draws, ticks, marker_ticks, markers, spare, wave_ticks, max_draw; };
volatile struct wr_probe wr_probe __attribute__((section(".data"))) =
    { 0x57525052u, 0, 0, 0, WR_MARKERS, 0x2D2D2D2Du, 0, 0 };
/* wave_ticks: the part wave() takes (the curve, the band and the position bar);
 * max_draw: the longest single draw (m10b3h-prof, 2026-10-03: is one of our draws
 * what stretches the audio interrupt past a frame?) */
#endif

/* The oscillator a page shows the wave of: osc 2 on page 2, osc 1 on pages 1 and 3
 * (page 3 is MOVE's TRIG, M10a, which is not an oscillator's) */
static int osc_of(int page)
{
    return page == 1 ? 1 : 0;
}

#if WR_MARKERS
/* Modulation (docs/modulation-display.md). The audio tick keeps, per VOICE, a target
 * array (the sound's values, copied when a note takes the voice) and the value array
 * it smooths from it and then modulates in place (0x400db12a, 0x400db22c); slot s of
 * voice v is at +34 + 202 v + 2 s in both, at the record's own scale for a linear
 * parameter (instrument, modview1, 2026-10-01: POS 74 with no LFO reads 0x4a00).
 * The 16 rows are voices, not tracks (instrument, wrm9c, 2026-10-02: a poly
 * Waverider on track 2 sat on voices 3/5/7/8/14, then 0/5/7; the LFO4 work found the
 * same, docs/lfo4-build-plan.md "SOLVED"). Reading row = the active track showed
 * another sound's modulation: page 1's wave flicked between tables 0 and 1 while an
 * FM track's LFO moved its own slot 27. So the rows are read at `voice()`.
 *
 * The value array alone lags the knob: it holds what was last heard, so with the
 * sequencer stopped it does not follow a turn (owner, modview2b). So the markers
 * show the modulation as an offset, heard - target, drawn around the knob's own
 * value: the dot at knob + offset, and the range the offset swept lately around the
 * knob. A turn moves all three together. */
#define ACTIVE_TRACK (*(volatile u8 *)0x42431A6Cu)
#define TARGETS 0x80003AF0u
#define VALUES  0x800068E4u
/* voice v's track, a long each (instrument, wrm9c, 2026-10-02: 12 readings against
 * the frame's machine types while the voices moved, no mismatch; a "reuse"-locked
 * voice held its track, the FM Drum voice its own) */
#define OWNER(v)   (((volatile u32 *)0x80005308u)[v])
/* voice v's machine type in the SHARC control frame (dnfw.waverider.frame MACHINE) */
#define MACHINE(v) (((volatile unsigned short *)(0x80005E60u + 148u))[v])
#define NEW_TYPE 5
/* the UI tick, about 120 a second (instrument, modview3, 2026-10-01: 239 in 2.0 s).
 * Not a millisecond count, as docs/display-path.md had it from the emulator. */
#define TICKS   (*(volatile u32 *)0x466758B0u)
#define TICK_HZ 120
#define SET_DIRTY ((void (*)(void *))0x4011D2FEu)               /* screen: redraw */

#define QUANT   0x300           /* an offset step worth a redraw: about half a pixel */
/* POS's own step: 1/16 of a table frame (a frame is 0x800). QUANT is half a pixel of
 * the cursor but 37 % of a frame of the wave's morph, so a slow MOVE on POS redrew
 * about 7 times a second, the wave stepping visibly (instrument, m10b3f,
 * 2026-10-03: oscillator 2's Tri, pattern stopped). FRAME still caps the rate. */
#define POS_QUANT 0x80
#define HOLD    (2 * TICK_HZ)   /* a range edge holds 2 s before it relaxes */
#define SHOWN   (TICK_HZ * 6 / 5)   /* 1.2 s: the stock UI redraws a shown page once a second */
#define FRAME   5               /* ticks: at most 24 redraws a second, about a turn's own rate */
#define MARKED  4               /* the places with markers: POS and TBL of each osc (TUNE is
                                 * pitch-converted in the array, so not yet) */

/* The voice to read for the active track: one it owns that plays a Waverider (an idle
 * voice also reads track 0). The last one chosen is kept while it still qualifies,
 * so the markers do not jump between voices whose LFOs are at different phases.
 * -1: none (the track has not played; nothing is shown, as before the first PLAY). */
static int chosen __attribute__((section(".data"))) = -1;

static int voice(void)
{
    u32 t = ACTIVE_TRACK;
    if (t > 15)
        return -1;
    if (chosen >= 0 && OWNER(chosen) == t && MACHINE(chosen) == NEW_TYPE)
        return chosen;
    chosen = -1;
    for (int v = 0; v < 16; v++)
        if (OWNER(v) == t && MACHINE(v) == NEW_TYPE) {
            chosen = v;
            break;
        }
    return chosen;
}

static int heard(int v, u32 id)
{
    return *(volatile unsigned short *)(VALUES + 34u + 202u * v + 2u * RECORD(id)[1]);
}

/* M10b-3: MOVE's share of POS. The SHARC moves POS itself (modulator.asm), so the value
 * array never sees it; it reports each voice's shape instead, as byte 2v + osc of its
 * reply's tail, the shape's high byte (reader_m9.asm, wr_mod_done). This applies the
 * same arithmetic as wr_mod_b: POS += (MPOS - 0x3200) x shape x 0x7800 / (0x3200 x
 * 0xffff), in 32 bits (the shape's low byte is its high byte again, within a step). */
#define REPLY_TAIL ((volatile u8 *)(0x800053A4u + 0xA9Cu))
#define MPOS_ID(o) ((o) ? 250u : 246u)          /* OFS1 / OFS2 (pages.PAGES) */
#define RATE_ID(o) ((o) ? 244u : 240u)          /* PD1 / PD2 */

#define MOVE_ID(o) ((o) ? 257u : 253u)          /* M.Shape: the shape index << 8, 4 = Square */

/* MOVE's POS shift at shape byte S (the report's high byte, or 0 / 255 for its ends) */
static int move_offset_at(int v, int o, int s)
{
    int mpos = heard(v, MPOS_ID(o)) - 0x3200;
    if (!mpos)
        return 0;
    return ((mpos * (s << 8 | s)) >> 16) * 0x7800 / 0x3200;
}

static int move_offset(int v, int o)
{
    return move_offset_at(v, o, REPLY_TAIL[2 * v + o]);
}

/* M10b-3: follow the newest note. Each trig plays on the next voice (instrument,
 * m10b3b, 2026-10-03: a Ramp Up on track 1 ramped on voices 15, 3, 5, 4, 8, 9, 10, 13
 * in turn), and a one-shot stops at its end, so the voice chosen went still while
 * the next notes moved. A voice of the track whose report moves after standing still
 * for STILL has started a note: it becomes the one shown. A looping shape never
 * stands still, so with one the chosen voice is kept, as before.
 * A voice reads as Waverider (MACHINE) only once it has played a Waverider note, and
 * on its first one that comes after its report has begun to move: the first lap of
 * notes was missed until every voice had played once (instrument, m10b3d,
 * 2026-10-03). So a voice that is not yet the track's keeps its last still time, and
 * is taken as soon as it qualifies; with none chosen, the first that moves is taken. */
#define STILL   (TICK_HZ / 2)
/* A shape byte that moves more than JUMP between two polls has restarted: a new note
 * with TRIG on restart. A looping shape never stands still, so without this the page
 * kept its first voice and jumped whenever the rotation retriggered that one
 * (instrument, m10b3f/g, 2026-10-03: unison, 3-note chords, Tri on osc 2). Not for
 * Square, which jumps by design, nor past RATE 60 (2 cycles a second: a Tri moves
 * about 51 steps in a 50 ms gap between polls), where motion could pass for a jump. */
#define JUMP      96
#define JUMP_RATE 60
static u8 seen[32] __attribute__((section(".data"))) = { 0 };
static u32 seen_at[32] __attribute__((section(".data"))) = { 0 };

/* Each oscillator's byte is watched on its own, and only the shown one's (O) can
 * switch: judged on both, a MOVE running on the other oscillator kept every voice
 * from ever standing still, so page 1 never followed while osc 2 looped
 * (instrument, m10b3e, 2026-10-03). Both are tracked every poll, so turning the
 * page does not read old changes as new notes. */
static void follow(u32 now, int o)
{
    int c = voice();
    u32 t = ACTIVE_TRACK;
    for (int k = 0; k < 32; k++) {
        int v = k >> 1;
        u8 a = REPLY_TAIL[k], was = seen[k];
        if (a == was)
            continue;
        seen[k] = a;
        if (OWNER(v) != t || MACHINE(v) != NEW_TYPE)
            continue;                       /* not the track's yet: the start stays pending */
        if ((k & 1) == o && v != c) {
            int d = a > was ? a - was : was - a;
            int restart = d > JUMP && (heard(v, MOVE_ID(o)) >> 8) < 4
                && (heard(v, RATE_ID(o)) >> 8) <= JUMP_RATE;
            if (restart || now - seen_at[k] > STILL)
                chosen = c = v;
        }
        seen_at[k] = now;
    }
}

static int mod_offset(u32 id)
{
    int v = voice(), slot = RECORD(id)[1];
    if (v < 0 || slot < 0 || slot > 99)
        return 0;
    u32 at = 34u + 202u * v + 2u * slot;
    int off = *(volatile unsigned short *)(VALUES + at) - *(volatile unsigned short *)(TARGETS + at);
    if (id == WR_POS_ID)
        off += move_offset(v, 0);
    else if (id == WR_POS2_ID)
        off += move_offset(v, 1);
    return off;
}

/* POS and TBL of osc 1 (page 1), then of osc 2 (page 2, M9b): page p's are 2p, 2p + 1 */
static const u32 marked[MARKED] = { WR_POS_ID, WR_TBL_ID, WR_POS2_ID, WR_TBL2_ID };

/* per marked parameter: the offset range swept lately, and when each edge last grew */
struct sweep { int lo, hi; u32 lo_at, hi_at; };
static struct sweep sweeps[MARKED] __attribute__((section(".data"))) =
    { { 0, 0, 0, 0 }, { 0, 0, 0, 0 }, { 0, 0, 0, 0 }, { 0, 0, 0, 0 } };
/* the page the last draw showed: wr_poll watches its two places only */
static int shown_page __attribute__((section(".data"))) = 0;
/* what the last draw showed, for wr_poll to compare against */
static u32 drawn_at __attribute__((section(".data"))) = 0;
static u32 asked_at __attribute__((section(".data"))) = 0;
static int drawn_sig __attribute__((section(".data"))) = 0;
static int settling __attribute__((section(".data"))) = 0;

static int which(u32 id)
{
    for (int k = 0; k < MARKED; k++)
        if (marked[k] == id)
            return k;
    return -1;
}

/* How fast the parameter moves, from the settings of the LFOs aimed at it
 * (docs/modulation-display.md, "faster than the screen"): tier 0 is slow enough for
 * a moving dot (up to a redraw rate's eighth, 3 Hz at 24 a second), tier 1 is jerky
 * (up to half the rate, 12 Hz) and gets the dot over a dithered band, tier 2 would
 * alias and gets the band alone. The rate is the manual's table (p. 64):
 *   f = |SPD| x MULT x BPM / 30720 Hz, BPM 120 for a fixed MULT.
 * The LFO settings are the target array's slots 1..24, eight an LFO: SPD, MULT,
 * FADE, DEST, WAVE, SPH, MODE, DEP (the record table: ids 75..83, 85..93, 95..103).
 * DEST holds the destination's slot << 8 (docs/fx-master-modulation.md). */
#define TIER_FPS 24
/* The tempo, as BPM x 120: 14400 at 120.0, 14520 at 121.0 (instrument, modview3b,
 * 2026-10-01, three snapshots of the on-chip RAM, stopped). The control frame for the
 * SHARC carries a copy at 0x80005f38. */
#define TEMPO_X120 (*(volatile unsigned short *)0x800026C2u)

static int bpm(void)
{
    int t = TEMPO_X120 / 120;
    return t >= 20 && t <= 400 ? t : 120;
}

static int lfo_word(int v, int slot)
{
    return *(volatile unsigned short *)(TARGETS + 34u + 202u * v + 2u * slot);
}

static int tier(u32 id)
{
    int t = voice(), slot = RECORD(id)[1], fastest = 0;
    if (t < 0)
        return 0;
    for (int l = 0; l < 3; l++) {
        int base = 1 + 8 * l;
        int dep = lfo_word(t, base + 7) - 0x4000;
        if (lfo_word(t, base + 3) != slot << 8 || (dep < 0x80 && dep > -0x80))
            continue;
        int spd = lfo_word(t, base) - 0x4000, m = lfo_word(t, base + 1) >> 8;
        if (spd < 0) spd = -spd;
        /* MULT: 0..11 are 1..2K BPM, synced; 12..23 are 1..2K fixed at 120 BPM
         * (instrument, modview3b: raw 8 reads "256 BPM", 0 "1 BPM", 12 "1") */
        int beats = m < 12 ? bpm() : 120, mult = 1 << (m < 12 ? m : m - 12);
        /* spd/16 x mult x bpm stays in 31 bits; Hz x 30720 x 256 / 16 = Hz x 491520 */
        int rate = (spd >> 4) * mult * beats;
        int k = rate > 491520 * (TIER_FPS / 2) ? 2 : rate > 491520 * (TIER_FPS / 8) ? 1 : 0;
        if (k > fastest)
            fastest = k;
    }
    /* MOVE on POS (M10b-3): one cycle a second at RATE 50, twice as fast every +10,
     * so past 66 it is over 3 Hz and past 86 over 12 Hz -- the LFOs' two tiers */
    int o = id == WR_POS2_ID ? 1 : 0;
    if ((id == WR_POS_ID || id == WR_POS2_ID) && heard(t, MPOS_ID(o)) != 0x3200) {
        int r = heard(t, RATE_ID(o)) >> 8;
        int k = r > 86 ? 2 : r > 66 ? 1 : 0;
        if (k > fastest)
            fastest = k;
    }
    return fastest;
}

/* what a redraw would change: the offsets of the places slow enough to animate */
static int signature(void)
{
    int sig = 0;
    for (int k = 2 * osc_of(shown_page); k < 2 * osc_of(shown_page) + 2; k++)
        sig = sig * 131 + (tier(marked[k]) < 2
                           ? mod_offset(marked[k]) / (k & 1 ? QUANT : POS_QUANT) : 0);
    return sig;
}

/* widen at once; after HOLD without growing, an edge relaxes toward the offset */
static void sweep(int k, int off, u32 now)
{
    struct sweep *w = &sweeps[k];
    if (off <= w->lo) { w->lo = off; w->lo_at = now; }
    else if (now - w->lo_at > HOLD) w->lo += (off - w->lo) / 4 + 1;
    if (off >= w->hi) { w->hi = off; w->hi_at = now; }
    else if (now - w->hi_at > HOLD) w->hi += (off - w->hi) / 4 - 1;
    if (w->lo > off) w->lo = off;
    if (w->hi < off) w->hi = off;
    if (w->hi - w->lo > QUANT)
        settling = 1;
}

/* Called by the UI task in place of its `isDirty(screen)` (0x4002e464), once a loop:
 * while Waverider's page is on screen (it drew in the last SHOWN) and a marker
 * would move, ask the stock redraw (0x4011d2fe), at most every FRAME. Off the
 * page, or with nothing modulated, it costs a compare and the stock call. */
int wr_poll(void *screen)
{
    u32 now = TICKS;
    follow(now, osc_of(shown_page));
    if (now - drawn_at < SHOWN && now - asked_at >= FRAME
            && (settling || signature() != drawn_sig)) {
        asked_at = now;
        SET_DIRTY(screen);
    }
    return IS_DIRTY(screen);
}
#endif

#if !WR_MARKERS
/* the UI loop's redraw test, as stock: nothing on the page moves by itself */
int wr_poll(void *screen)
{
    return IS_DIRTY(screen);
}
#endif

static void *method(void *obj, int offset)
{
    return *(void **)(*(char **)obj + offset);
}

static void px(void *c, int x, int y)
{
    SET_PIXEL(c, x, y, 1);
}

static void column(void *c, int x, int y0, int y1)
{
    if (y0 > y1) {
        int t = y0; y0 = y1; y1 = t;
    }
    for (int y = y0; y <= y1; y++)
        px(c, x, y);
}

/* A control's value under its label: a dotted track with the value filled in,
 * from the left, or from the centre for a control whose default is the middle
 * of its range (TUNE). A control of a few steps (TBL: 0..0x100) is drawn as
 * that many segments with the current one filled. */
static void indicator(void *c, int cx, int y, u32 id, int v)
{
    const int *r = limits(id);
    int lo = r[0], hi = r[1], def = r[2], span = hi - lo;
    if (span <= 0)
        return;
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    int x0 = cx - BAR_HALF, x1 = cx + BAR_HALF;

    if (span % 0x100 == 0 && span / 0x100 < 8) {
        int n = span / 0x100 + 1, at = (v - lo) / 0x100;
        int w = (x1 - x0 + 2) / n;
        for (int k = 0; k < n; k++) {
            int a = x0 + k * w, b = a + w - 2;
            for (int x = a; x <= b; x++) {
                px(c, x, y);
                if (k == at)
                    px(c, x, y + 1);
            }
        }
        return;
    }

    for (int x = x0; x <= x1; x += 2)
        px(c, x, y);
    int at = x0 + (v - lo) * (x1 - x0) / span;
    int from = (2 * def == lo + hi) ? cx : x0;
    column(c, at, y, y + 1);
    for (int x = (from < at ? from : at); x <= (from < at ? at : from); x++)
        px(c, x, y + 1);
}

#if WR_MARKERS
/* a small "approximately" sign, two tildes 4 wide, 4 x 5, its bottom-left corner at
 * (x, y): each tilde low, high, low, high, so it reads as a wave and not as carets */
static void approx(void *c, int x, int y)
{
    for (int k = 0; k < 2; k++) {
        int yy = y + 1 + 3 * k;
        px(c, x, yy); px(c, x + 1, yy + 1); px(c, x + 2, yy); px(c, x + 3, yy + 1);
    }
}

/* x of value v on place cx's track, as `indicator` places it */
static int track_x(u32 id, int cx, int v)
{
    const int *r = limits(id);
    int lo = r[0], hi = r[1];
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    return cx - BAR_HALF + (v - lo) * (2 * BAR_HALF) / (hi - lo);
}

/* Place i's modulation, on the row beside its track (y), option B: the range swept
 * lately around the knob, dotted, and a two-pixel dot at knob + offset. Nothing at
 * all while the parameter is not modulated. */
static void modulation(void *c, int cx, int y, int label_y, u32 id, int set, u32 now)
{
    int k = which(id);
    const int *r = limits(id);
    if (k < 0 || r[1] <= r[0])
        return;
    int off = mod_offset(id);
    sweep(k, off, now);
    struct sweep *w = &sweeps[k];
    if (w->hi - w->lo <= QUANT && off < QUANT && off > -QUANT)
        return;
    int a = track_x(id, cx, set + w->lo), b = track_x(id, cx, set + w->hi);
    int speed = tier(id);
    if (speed == 0) {
        for (int x = a; x <= b; x += 2)
            px(c, x, y);
    } else {
        for (int x = a; x <= b; x++)            /* the band: a 50 % dither, the panel's grey */
            for (int yy = y - 1; yy <= y; yy++)
                if (((x + yy) & 1) == 0)
                    px(c, x, yy);
    }
    if (speed < 2)
        column(c, track_x(id, cx, set + off), y - 1, y);
    else
        approx(c, cx + 10, label_y);            /* "too fast to draw" beside the label */
}
#endif

/* The frame the SHARC reader plays for the current TBL and POS, interpolated
 * between the two frames either side, one span a column; then the table's
 * position as a dotted bar with a marker. With the markers, the wave is the frame
 * heard (the knob plus the modulation), and a dotted marker under the bar shows
 * where the modulation has it, while the solid one stays on the knob. */
/* column x of the frame at (tbl, pos), interpolated: its span, in canvas rows */
static void span(int tbl, int pos, int x, int *lo, int *hi)
{
    int fx = pos >> 3;                      /* pos * 15 * 256 / 0x7800, exactly */
    int f = fx >> 8, frac = fx & 0xFF;
    int g = f < WR_FRAMES - 1 ? f + 1 : f;
    int l = wr_spans[tbl][f][0][x] + (((wr_spans[tbl][g][0][x] - wr_spans[tbl][f][0][x]) * frac) >> 8);
    int h = wr_spans[tbl][f][1][x] + (((wr_spans[tbl][g][1][x] - wr_spans[tbl][f][1][x]) * frac) >> 8);
    *lo = WAVE_CY + l * WAVE_AMP / 127;
    *hi = WAVE_CY + h * WAVE_AMP / 127;
}

static int clamp_pos(int pos)
{
    return pos < 0 ? 0 : pos > WR_POS_MAX ? WR_POS_MAX : pos;
}

/* The frame at (tbl, pos) as a thin line. Each column is its span drawn solid --
 * its real extent, as Tonverk's Wavefinder draws a column -- with a span of two
 * pixels or less shrunk to its middle pixel, and joined to the column before only
 * across the gap between them, if there is one. A smooth stretch is one pixel
 * thick, a steep one a single solid stroke. Drawing each span by its two edges
 * instead split every steep slope into two traces (modview4e, on the instrument). */
static void curve(void *c, int tbl, int pos)
{
    int last_lo = 0, last_hi = 0;
    for (int x = 0; x < WR_WIDTH; x++) {
        int lo, hi;
        span(tbl, pos, x, &lo, &hi);
        if (hi - lo <= 2)                   /* a smooth stretch: one pixel, at its middle */
            lo = hi = (lo + hi) >> 1;
        column(c, WAVE_X + x, lo, hi);
        if (x > 0 && lo > last_hi)
            column(c, WAVE_X + x, last_hi + 1, lo);
        else if (x > 0 && hi < last_lo)
            column(c, WAVE_X + x, hi, last_lo - 1);
        last_lo = lo;
        last_hi = hi;
    }
}

/* the wave of the page's oscillator: osc 1 on page 1, osc 2 on page 2 (M9b) */
static void wave(void *c, void *view, int page)
{
    u8 flag;
    int o = osc_of(page);
    u32 pos_id = marked[2 * o], tbl_id = marked[2 * o + 1];
    struct sweep *sw = &sweeps[2 * o];
    int tbl = GET_VALUE(view, tbl_id, &flag) >> 8;
    int pos = GET_VALUE(view, pos_id, &flag);
#if WR_MARKERS
    int set_pos = clamp_pos(pos);
    int moved = mod_offset(pos_id);
    int speed = tier(pos_id);
    pos += moved;
    tbl = (GET_VALUE(view, tbl_id, &flag) + mod_offset(tbl_id)) >> 8;
#else
    (void)sw;
#endif
    if (tbl < 0) tbl = 0;
    if (tbl >= WR_TABLES) tbl = WR_TABLES - 1;
    pos = clamp_pos(pos);

#if WR_MARKERS
    if (speed > 0) {
        /* Faster than the screen: the two frames at the ends of the sweep, drawn as
         * ordinary curves, with a sparse dotted fill between them (one pixel in
         * nine) -- the frames being heard lie in there. A dense 50 % envelope read
         * as too heavy on the panel (owner, modview4b). */
        int from = clamp_pos(set_pos + sw->lo), to = clamp_pos(set_pos + sw->hi);
        /* A fast MOVE's ends are known, not measured: shape 0 and 255, the DSP's own
         * arithmetic, plus what the LFOs add now. Sampled at the redraw rate they
         * wandered, and the two end waves changed for a fixed sweep (owner, m10b3g). */
        int v = voice();
        if (v >= 0 && (heard(v, RATE_ID(o)) >> 8) > 66 && heard(v, MPOS_ID(o)) != 0x3200) {
            int lfo = moved - move_offset(v, o);
            int e0 = move_offset_at(v, o, 0), e1 = move_offset_at(v, o, 255);
            from = clamp_pos(set_pos + lfo + (e0 < e1 ? e0 : e1));
            to = clamp_pos(set_pos + lfo + (e0 < e1 ? e1 : e0));
        }
        curve(c, tbl, from);
        curve(c, tbl, to);
        for (int x = 0; x < WR_WIDTH; x += 3) {
            int alo, ahi, blo, bhi;
            span(tbl, from, x, &alo, &ahi);
            span(tbl, to, x, &blo, &bhi);
            int y0, y1;                         /* the gap between the two curves */
            if (ahi < blo) { y0 = ahi; y1 = blo; }
            else if (bhi < alo) { y0 = bhi; y1 = alo; }
            else continue;                      /* they touch in this column */
            for (int y = y0 + 2; y <= y1 - 2; y++)
                if (y % 3 == 0)
                    px(c, WAVE_X + x, y);
        }
        for (int x = 0; x < WR_WIDTH; x += 2)
            px(c, WAVE_X + x, POS_Y);
        int a = WAVE_X + from * (WR_WIDTH - MARK) / WR_POS_MAX;
        int b = WAVE_X + to * (WR_WIDTH - MARK) / WR_POS_MAX + MARK - 1;
        for (int x = a; x <= b; x++)            /* the positions swept, under the bar */
            if ((x & 1) == 0)
                px(c, x, CURSOR_Y);
        int m = WAVE_X + set_pos * (WR_WIDTH - MARK) / WR_POS_MAX;
        for (int k = 0; k < MARK; k++)
            column(c, m + k, POS_Y, POS_Y + 1);
        return;
    }
#endif

    curve(c, tbl, pos);

    for (int x = 0; x < WR_WIDTH; x += 2)
        px(c, WAVE_X + x, POS_Y);
#if WR_MARKERS
    int m = WAVE_X + set_pos * (WR_WIDTH - MARK) / WR_POS_MAX;
    int h = WAVE_X + pos * (WR_WIDTH - MARK) / WR_POS_MAX;
    /* while POS is modulated at all (the range swept is wider than a step), even
     * as the cursor passes under the knob's own marker (owner, modview4f) */
    if (sw->hi - sw->lo > QUANT || moved >= QUANT || moved <= -QUANT)
        for (int k = 0; k < MARK; k += 2)
            px(c, h + k, CURSOR_Y);
#else
    int m = WAVE_X + pos * (WR_WIDTH - MARK) / WR_POS_MAX;
#endif
    for (int k = 0; k < MARK; k++)
        column(c, m + k, POS_Y, POS_Y + 1);
}

void wr_page_draw(void *view, void *canvas)
{
#ifdef WR_PROBE
    u32 t0 = DTCN0, tm = 0;
#endif
    int page = ((int (*)(void *))method(view, 132))(view);
    if (page < 0 || page >= WR_PAGES)
        page = 0;
#if WR_MARKERS
    u32 now = TICKS;
    settling = 0;
    shown_page = page;
    drawn_sig = signature();
#endif

#ifdef WR_PROBE
    u32 w0 = DTCN0;
#endif
    wave(canvas, view, page);
#ifdef WR_PROBE
    wr_probe.wave_ticks += DTCN0 - w0;
#endif

    for (int i = 0; i < 8; i++) {
        int top = i < 4;
        int cx = COL0 + COLW * (i & 3) + COLW / 2;
        u32 id = wr_ids[page][i];
        TEXT(canvas, FONT, cx, top ? TOP_LABEL_Y : BOT_LABEL_Y, CENTRED, "%.5s", wr_labels[page][i]);
        if (!id)
            continue;
        u8 flag;
        int set = GET_VALUE(view, id, &flag);
        indicator(canvas, cx, top ? TOP_BAR_Y : BOT_BAR_Y, id, set);
#if WR_MARKERS
#ifdef WR_PROBE
        u32 m0 = DTCN0;
#endif
        modulation(canvas, cx, top ? TOP_BAR_Y - 2 : BOT_BAR_Y + 3, top ? TOP_LABEL_Y : BOT_LABEL_Y,
                   id, set, now);
#ifdef WR_PROBE
        tm += DTCN0 - m0;
#endif
#endif
    }

    /* the stock grid's own tail: the level meter, then the page dots */
    ((void (*)(void *, void *, int))method(view, 184))(view, canvas, 0);
    int n = PAGE_COUNT(view);
    if (n > 1)
        PAGE_DOTS(view, canvas, n, page, 7);
#if WR_MARKERS
    drawn_at = now;
#endif
#ifdef WR_PROBE
    wr_probe.draws++;
    u32 took = DTCN0 - t0;
    wr_probe.ticks += took;
    wr_probe.marker_ticks += tm;
    if (took > wr_probe.max_draw)
        wr_probe.max_draw = took;
#endif
}
