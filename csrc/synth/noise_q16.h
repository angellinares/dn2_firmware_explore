/* A noise generator in Q16 integers: xorshift32, a colour filter per TYPE, a tilt, and
 * a decay envelope. It mirrors Waverider's DSP noise (noise.asm; the reference is
 * dnfw.waverider.live.NoiseVoice) step for step, so a screen can draw what the voice
 * plays. Nothing here knows a machine, a page or a screen.
 *
 * One subject: the generator's state and its next sample.
 */
#ifndef SYNTH_NOISE_Q16_H
#define SYNTH_NOISE_Q16_H

enum { NOISE_WHT, NOISE_PNK, NOISE_BRN, NOISE_DIG, NOISE_TYPES };

struct noise_q16 {
    unsigned x;                 /* xorshift32's state: never 0 */
    int pink[3], brown, lp;     /* the filters' state */
    int env;                    /* the envelope, Q16 */
};

void noise_q16_init(struct noise_q16 *n, unsigned seed);

/* the next sample, Q16, before the gain: TYPE's colour, then the tilt by COLR (0..127,
 * 64 flat: n - (COLR - 64) / 64 x a one-pole low-pass at 1/8) */
int noise_q16_next(struct noise_q16 *n, int type, int colr);

/* y under the envelope, then the envelope one step on by its factor k (Q16) */
int noise_q16_decay(struct noise_q16 *n, int y, int k);

#endif
