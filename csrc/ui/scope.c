/* The oscilloscope trace (scope.h). */
#include "scope.h"
#include "canvas.h"

void scope_draw(void *c, const volatile struct trace_ring *r, const struct strip_box *b)
{
    int w = b->x1 - b->x0 + 1, cy = (b->y0 + b->y1) >> 1, half = (b->y1 - b->y0) >> 1;
    unsigned span = (unsigned)w * SCOPE_SPC;
    unsigned end = r->w;                                 /* a snapshot: the writer runs on */
    unsigned from = end - span - SCOPE_SEARCH;
    int peak = 0;
    for (unsigned i = from; i != end; i++) {
        int v = trace_ring_at(r, i);
        if (v < 0) v = -v;
        if (v > peak) peak = v;
    }
    if (peak < SCOPE_QUIET) {
        for (int x = b->x0; x <= b->x1; x++)
            canvas_px(c, x, cy);
        return;
    }
    /* the latest rising zero crossing in the search span, armed below -peak/8 so noise
     * around zero doesn't trigger; none: free-run on the newest window */
    unsigned trig = end - span;
    int armed = 0, h = peak >> 3;
    for (unsigned i = from; i != from + SCOPE_SEARCH; i++) {
        int v = trace_ring_at(r, i);
        if (v < -h)
            armed = 1;
        else if (armed && v >= 0) {
            trig = i;
            armed = 0;
        }
    }
    int last = (trace_ring_at(r, trig) * half) / peak;
    for (int k = 0; k < w; k++) {
        int lo = last, hi = last;
        for (unsigned j = 0; j < SCOPE_SPC; j++) {
            int y = (trace_ring_at(r, trig + (unsigned)k * SCOPE_SPC + j) * half) / peak;
            if (y < lo) lo = y;
            if (y > hi) hi = y;
            last = y;
        }
        canvas_column(c, b->x0 + k, cy + lo, cy + hi);
    }
}
