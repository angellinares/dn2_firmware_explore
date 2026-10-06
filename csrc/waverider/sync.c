/* The song position for MOVE's SYNC (M10b-2), the ColdFire half.
 *
 * MOVE runs on the DSP, which cannot see the sequencer. So every frame carries the
 * position since PLAY, which the DSP turns into a tempo-locked phase that starts on
 * step 1 (modulator.asm, sync.asm). docs/sequencer-playhead.md has the measurements.
 *
 * - **The steps:** 0x446483d0 + t is track t's current step (0 = step 1) and
 *   0x446483e0 + t its next one: static arrays, named by `lea` at 0x400d79f2 and
 *   0x400d79fe (1.11). While playing, next = current + 1 (mod the pattern's length);
 *   STOP sets both to 0 and holds them there, and PLAY starts with 0 and 1. So both 0
 *   is stopped. A torn read can show them equal for a moment, so a STOP counts only
 *   after STOP_FRAMES frames in a row. Track 1's steps are the clock: with one length
 *   and one scale for the pattern every track reads the same (measured); per-track
 *   lengths and scales are not.
 * - **Between steps,** the tempo: frame +0xd8 is BPM x 120 (the copy of 0x800026c2 the
 *   stock code sends), and a sixteenth lasts 1500 x 60 / (4 x BPM) frames, so it ends
 *   when the tempo words summed since the step reach SIXTEENTH. The fraction holds
 *   just short of the next step until the sequencer gets there (a pause).
 * - **The position** is a u32 in which 2^32 is SYNC_LOOP sixteenths, 24 bars: the
 *   least common multiple of every SYNC length, the triplets and the dotted ones
 *   included, so each length's phase is the position times a whole number and stays
 *   continuous where the position wraps. It goes in frame bytes 2644..2647, unused
 *   in the tail (out/tail_sweep.json), the low half first, as the DSP reads a word.
 *
 * A chunk the loader sends in place of a frame carries no position: the DSP keeps the
 * last one for that block, so a synced MOVE stands still for 0.7 ms. */

#include "sync.h"

#define STEP_NOW    ((volatile const u8 *)0x446483D0u)   /* + track */
#define STEP_NEXT   ((volatile const u8 *)0x446483E0u)
#define TEMPO       0xD8                  /* frame bytes: BPM x 120, u16 */
#define POSITION    2644                  /* frame bytes 2644..2647 */
#define SIXTEENTH   2700000u              /* tempo words summed over a sixteenth: 22500 x 120 */
#define SYNC_LOOP   384u                  /* sixteenths in 2^32 of the position */
#define STOP_FRAMES 8

volatile struct wr_sync wr_sync __attribute__((section(".data"))) =
    { 0x57525359u, 0, 0, 0, 0, 0 };
static u32 last_step __attribute__((section(".data"))) = 0;
static u32 still __attribute__((section(".data"))) = 0;          /* frames with both bytes 0 */

void wr_sync_frame(u8 *frame)
{
    u32 now = STEP_NOW[0], next = STEP_NEXT[0];
    u32 tempo = (u32)frame[TEMPO] << 8 | frame[TEMPO + 1];
    u32 frac, x, p;

    if (now == 0 && next == 0) {
        if (still < STOP_FRAMES && ++still == STOP_FRAMES) {
            wr_sync.stops++;
            wr_sync.sixteenths = 0;
            last_step = 0;
        }
        if (still == STOP_FRAMES)
            wr_sync.ticks = 0;            /* held at step 1 until PLAY */
    } else
        still = 0;

    if (now != next && now != last_step) {
        last_step = now;
        wr_sync.steps++;
        wr_sync.sixteenths = (wr_sync.sixteenths + 1) % SYNC_LOOP;
        wr_sync.ticks = 0;
    }
    if (still < STOP_FRAMES && wr_sync.ticks < SIXTEENTH)
        wr_sync.ticks += tempo;
    if (wr_sync.ticks > SIXTEENTH - 1)
        wr_sync.ticks = SIXTEENTH - 1;

    frac = wr_sync.ticks * 1024u / 42188u;            /* x 65536 / SIXTEENTH */
    if (frac > 0xFFFFu)
        frac = 0xFFFFu;
    x = wr_sync.sixteenths << 16 | frac;
    p = 170u * x + 2u * x / 3u;                       /* x x 2^32 / (SYNC_LOOP x 2^16) */
    wr_sync.position = p;
    frame[POSITION] = (u8)(p >> 8);
    frame[POSITION + 1] = (u8)p;
    frame[POSITION + 2] = (u8)(p >> 24);
    frame[POSITION + 3] = (u8)(p >> 16);
}
