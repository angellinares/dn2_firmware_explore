/* A strip that draws a noise generator's and a sub-oscillator's traces from their
 * settings, as the voice would play them: the generator's own steps (synth/noise_q16)
 * one sample a column after a warm-up, from a fixed seed so it stands still, and the
 * sub's shape (synth/sub_q16) at its own scale. It takes plain values, so any machine
 * with a noise or a sub can draw it; the Python mirror dnfw.waverider.noise_glyph
 * predicts every pixel.
 *
 * One subject: drawing the strip.
 */
#ifndef UI_NOISE_STRIP_H
#define UI_NOISE_STRIP_H

#include "box.h"                      /* the box: x1 - x0 + 1 == NOISE_ENV_WIDTH */

struct noise_strip_values {
    int nois, type, colr, dec;          /* 0..127, NOISE_*, 0..127 (64 flat), 0..126 / 127 Inf */
    int sub, octave, shape;             /* 0..127, 0..2 (-1..-3 oct), SUB_* */
};


enum { STRIP_OVER = 3,                  /* the sub solid, the noise dotted under it */
       STRIP_SUM = 4 };                 /* one line, their sum, as the track adds them */

void noise_strip_draw(void *canvas, const struct noise_strip_values *v,
                      const struct strip_box *b, int glyph);

#endif
