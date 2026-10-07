/* The noise generator in Q16 (noise_q16.h). The coefficients are the DSP's float32
 * ones (live.NOISE_PINK, NOISE_BROWN, NOISE_DIG) x 65536, rounded. */
#include "noise_q16.h"
#include "fixq16.h"

/* P. Kellet's economy pink: three one-poles (a, d) and a direct term, x 0.25. The third
 * d is above 1.0, so it is kept as d - 1 plus the input itself */
static const int pink_a[3] = { 65382, 63111, 37356 };
static const int pink_d[3] = { 6491, 19432, 68989 - Q16_ONE };
#define PINK_DIRECT 12111
#define BROWN_A     64225          /* 0.98 */
#define BROWN_D     9830           /* 0.15 */
#define DIG_LEVEL   32768          /* +-0.5 */

void noise_q16_init(struct noise_q16 *n, unsigned seed)
{
    n->x = seed ? seed : 1u;
    n->pink[0] = n->pink[1] = n->pink[2] = 0;
    n->brown = n->lp = 0;
    n->env = Q16_ONE - 1;
}

int noise_q16_next(struct noise_q16 *n, int type, int colr)
{
    unsigned x = n->x;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    n->x = x;
    int w = (int)x >> 15, y;                              /* x as a signed fraction, Q16 */
    if (type == NOISE_WHT) {
        y = w;
    } else if (type == NOISE_PNK) {
        for (int j = 0; j < 3; j++)
            n->pink[j] = q16_mul(n->pink[j], pink_a[j]) + q16_mul(w, pink_d[j]) + (j == 2 ? w : 0);
        y = (n->pink[0] + n->pink[1] + n->pink[2] + q16_mul(w, PINK_DIRECT)) >> 2;
    } else if (type == NOISE_BRN) {
        n->brown = q16_mul(n->brown, BROWN_A) + q16_mul(w, BROWN_D);
        y = n->brown;
    } else {
        y = (x >> 31) ? -DIG_LEVEL : DIG_LEVEL;
    }
    n->lp += (y - n->lp) >> 3;
    return y - (((colr - 64) * n->lp) >> 6);
}

int noise_q16_decay(struct noise_q16 *n, int y, int k)
{
    y = q16_mul(y, n->env);
    n->env = q16_mul(n->env, k);
    return y;
}
