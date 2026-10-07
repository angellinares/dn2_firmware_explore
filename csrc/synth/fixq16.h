/* Q16 fixed point (1.0 = 65536) for the ColdFire, which has no 64-bit multiply.
 *
 * One subject: the arithmetic. Header-only, so any module can take it.
 */
#ifndef SYNTH_FIXQ16_H
#define SYNTH_FIXQ16_H

#define Q16_ONE 65536

/* v (Q16, signed) x c (Q16, 0 <= c < 2^16), as two partial products */
static inline int q16_mul(int v, int c)
{
    return (v >> 16) * c + (int)(((unsigned)(v & 0xFFFF) * (unsigned)c) >> 16);
}

/* y x level / 100, rounding towards zero: a 0..127 level where 100 is unity, as the
 * DSP's gains are */
static inline int q16_level(int y, int level)
{
    return y >= 0 ? y * level / 100 : -(-y * level / 100);
}

#endif
