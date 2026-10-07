/* One track's audio from the two links (audio_tap.h). */
#include "audio_tap.h"

static int s24_be(const volatile unsigned char *p)          /* 24-bit big-endian, signed */
{
    int v = (int)((unsigned)p[0] << 24 | (unsigned)p[1] << 16 | (unsigned)p[2] << 8);
    return v >> 8;
}

int dn2_track_block(unsigned track, short *out)
{
    if (track > 15)
        return 0;
    if (track >= 6) {                                         /* tracks 7..16: the reply */
        unsigned c = 2 * (track - 6);
        const volatile unsigned char *r =
            (const volatile unsigned char *)(DN2_REPLY + DN2_REPLY_RECORDS) + 3 * c;
        for (int k = 0; k < DN2_BLOCK; k++, r += DN2_REPLY_RECORD)
            out[k] = (short)((s24_be(r) + s24_be(r + 3)) >> 9);
        return 1;
    }
    unsigned half = *(volatile unsigned *)DN2_SSI_TX_SADDR < DN2_SSI_TX_HALF2 ? 1 : 0;
    const volatile int *f = (const volatile int *)(DN2_SSI_RX + half * DN2_SSI_HALF) + 2 * (track + 1);
    for (int k = 0; k < DN2_BLOCK; k++, f += DN2_SSI_FRAME / 4) {
        int l = (f[0] << 8) >> 8, r = (f[1] << 8) >> 8;      /* the low 24 bits, signed */
        out[k] = (short)((l + r) >> 9);
    }
    return 1;
}
