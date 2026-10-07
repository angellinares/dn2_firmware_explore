/* A ring of int16 samples: one writer (an interrupt) pushes blocks, readers look back
 * from the write count. TRACE_RING is a power of two; a reader keeps well behind the
 * writer (it has TRACE_RING - its look-back samples before they are overwritten).
 *
 * One subject: the ring. Header-only. */
#ifndef UI_TRACE_RING_H
#define UI_TRACE_RING_H

#define TRACE_RING 2048

struct trace_ring {
    volatile unsigned w;                /* samples written, ever (wraps) */
    short s[TRACE_RING];
};

static inline void trace_ring_push(volatile struct trace_ring *r, const short *x, int n)
{
    unsigned w = r->w;
    for (int k = 0; k < n; k++)
        r->s[(w + k) & (TRACE_RING - 1)] = x[k];
    r->w = w + n;                       /* after the samples: a reader never sees a gap */
}

static inline int trace_ring_at(const volatile struct trace_ring *r, unsigned i)
{
    return r->s[i & (TRACE_RING - 1)];
}

#endif
