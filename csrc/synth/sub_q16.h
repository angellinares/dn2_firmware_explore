/* A sub-oscillator's shapes in Q16, from a u32 phase: no table. They mirror Waverider's
 * DSP sub (sub.asm; the reference is dnfw.waverider.live.sub_value).
 *
 * One subject: a shape's value at a phase.
 */
#ifndef SYNTH_SUB_Q16_H
#define SYNTH_SUB_Q16_H

enum { SUB_SIN, SUB_TRI, SUB_SQR, SUB_PLS, SUB_SHAPES };

/* SIN two parabolas, TRI, SQR, PLS a 25 % pulse at +1 / -1/3 (no DC); +-65536 */
int sub_q16(unsigned phase, int shape);

#endif
