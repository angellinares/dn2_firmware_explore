/* A drawing box on a stock canvas: inclusive edges, y up, and a full-scale height.
 *
 * One subject: where a strip draws. */
#ifndef UI_BOX_H
#define UI_BOX_H

struct strip_box {
    int x0, x1, y0, y1;                 /* inclusive, y up */
    int unit;                           /* full scale, in pixels (where the drawing has one) */
};

#endif
