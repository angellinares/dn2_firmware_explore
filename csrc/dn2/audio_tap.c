/* One track's audio from the two links (audio_tap.h). */
#include "audio_tap.h"

/* the SSI0 read position, in frames, and the track it follows (0xFF: none yet) */
static unsigned ssi_cursor __attribute__((section(".data"))) = 0;
static unsigned ssi_track __attribute__((section(".data"))) = 0xFF;

static int s24_be(const volatile unsigned char *p)          /* 24-bit big-endian, signed */
{
    int v = (int)((unsigned)p[0] << 24 | (unsigned)p[1] << 16 | (unsigned)p[2] << 8);
    return v >> 8;
}

static unsigned ssi_written(void)                            /* frames before the DMA's position */
{
    unsigned d = *(volatile unsigned *)DN2_SSI_RX_DADDR - DN2_SSI_RX;
    return (d / DN2_SSI_FRAME) % DN2_SSI_FRAMES;
}

int dn2_track_take(unsigned track, short *out)
{
    if (track > 15)
        return 0;
    if (track >= 6) {                                         /* tracks 7..16: the reply */
        unsigned c = 2 * (track - 6);
        const volatile unsigned char *r =
            (const volatile unsigned char *)(DN2_REPLY + DN2_REPLY_RECORDS) + 3 * c;
        for (int k = 0; k < DN2_BLOCK; k++, r += DN2_REPLY_RECORD)
            out[k] = (short)((s24_be(r) + s24_be(r + 3)) >> 9);
        return DN2_BLOCK;
    }
    unsigned end = ssi_written();
    if (track != ssi_track) {                                 /* a new track: one block back */
        ssi_track = track;
        ssi_cursor = (end + DN2_SSI_FRAMES - DN2_BLOCK) % DN2_SSI_FRAMES;
    }
    int n = 0;
    for (; ssi_cursor != end; ssi_cursor = (ssi_cursor + 1) % DN2_SSI_FRAMES, n++) {
        const volatile int *f = (const volatile int *)(DN2_SSI_RX + ssi_cursor * DN2_SSI_FRAME) + 2 * (track + 1);
        int l = (f[0] << 8) >> 8, r = (f[1] << 8) >> 8;      /* the low 24 bits, signed */
        out[n] = (short)((l + r) >> 9);
    }
    return n;
}
