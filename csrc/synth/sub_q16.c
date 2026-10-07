/* The sub-oscillator's shapes in Q16 (sub_q16.h). */
#include "sub_q16.h"

int sub_q16(unsigned phase, int shape)
{
    int h = (int)((phase << 1) >> 17);                  /* x mod 0.5: 0..32767 */
    int neg = (int)(phase >> 31);
    if (shape == SUB_SIN) {
        int y = (int)(((unsigned)h * (unsigned)(32768 - h)) >> 12);
        return neg ? -y : y;
    }
    if (shape == SUB_TRI)
        return 4 * (neg ? h : 32768 - h) - 65536;
    if (shape == SUB_SQR)
        return neg ? -65536 : 65536;
    return phase < 0x40000000u ? 65536 : -21845;
}
