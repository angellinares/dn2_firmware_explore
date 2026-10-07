/* An oscilloscope trace of a sample ring in a box: triggered on a rising zero crossing so
 * a steady tone stands still, scaled to its own peak (the shape, not the level), each
 * column the min..max of its samples so a high note reads as a band, not as aliasing.
 * Silence draws the centre line. The Python mirror dnfw.waverider.scope_glyph predicts
 * every pixel.
 *
 * One subject: drawing the trace. */
#ifndef UI_SCOPE_H
#define UI_SCOPE_H

#include "box.h"
#include "trace_ring.h"

#define SCOPE_SPC    8                  /* samples per column: 98 columns = 16 ms at 48 kHz */
#define SCOPE_SEARCH 512                /* samples searched for the trigger, behind the window */
#define SCOPE_QUIET  64                 /* a peak below this (int16) is silence */

void scope_draw(void *canvas, const volatile struct trace_ring *r, const struct strip_box *b);

#endif
