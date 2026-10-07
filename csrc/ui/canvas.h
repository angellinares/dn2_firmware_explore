/* Pixels on a stock canvas (128 x 64, y counting up from the bottom edge).
 *
 * One subject: putting pixels down. Header-only; the setter's address is the OS's.
 */
#ifndef UI_CANVAS_H
#define UI_CANVAS_H

#include "../include/dn2_111.h"

static inline void canvas_px(void *c, int x, int y)
{
    ((void (*)(void *, int, int, int))DN2_SET_PIXEL)(c, x, y, 1);
}

/* a vertical run x, y0..y1, either way round */
static inline void canvas_column(void *c, int x, int y0, int y1)
{
    if (y0 > y1) {
        int t = y0; y0 = y1; y1 = t;
    }
    for (int y = y0; y <= y1; y++)
        canvas_px(c, x, y);
}

#endif
