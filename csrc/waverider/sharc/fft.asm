// fft.asm -- Waverider stage 3: an in-place complex FFT, radix 2, float32.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). The levels of a pool table are built from it (docs/waverider-stage3.md):
// a frame's forward transform, then per level an inverse transform of the harmonics the
// level keeps (dnfw.waverider.geometry.frame_levels).
//
// The data is N complex floats, (re, im) pairs, 8 bytes each, at a byte address (L1 or
// DDR). The bits of the indices are reversed first, then log2 N stages of butterflies
// (decimation in time). Forward is x[k] = sum x[n] e^(-2 pi i nk / N); with SIGN = -1.0
// the conjugate twiddles give the inverse, unscaled (the caller divides by N).
//
// Twiddles: TW holds (cos, -sin) of 2 pi t / NMAX for t = 0 .. NMAX/2 - 1, 8 bytes each;
// a stage of span S reads every (NMAX / S)-th entry, so one table serves every N <= NMAX.
//
// Parameter block at DM 0x2e4000 (byte addresses):
//   +0 data   +4 N   +8 TW   +12 NMAX * 4 (the first stage's twiddle stride, bytes)
//   +16 SIGN (float32, 1.0 forward, -1.0 inverse)
//
// The forms are the ones reader_m5.asm lists: counted software loops (no DO), each
// access `I0 = Rn` then `DM(0, I0)` / `DM(1, I0)`, and every add with R8-R15 first.
// Clobbers R0-R15, I0-I2. Not ABI-clean: the caller saves what it needs.
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16f800 (DM 0x2df000): the absolute
// jumps below are resolved for it (scripts/sharc_resolve_jumps.py).

.SECTION/PM seg_pmco;

.GLOBAL wr_fft.;
wr_fft.:
      R8 = DM(0x2e4000);                // data
      R9 = DM(0x2e4004);                // N

      // -- the indices' bits reversed: swap x[i] and x[j] once each, j = bitrev(i)
      R10 = R10 - R10;                  // i
      R11 = R11 - R11;                  // j

.GLOBAL wr_fft_rev.;
wr_fft_rev.:
      COMPU(R10, R11);
      IF GE JUMP 0x16f82b;              // -> wr_fft_noswap.
      R13 = LSHIFT R10 BY 3;
      R13 = R8 + R13;
      I0 = R13;
      R14 = LSHIFT R11 BY 3;
      R14 = R8 + R14;
      I1 = R14;
      R2 = DM(0, I0);
      R3 = DM(1, I0);
      R4 = DM(0, I1);
      R5 = DM(1, I1);
      DM(0, I0) = R4;
      DM(1, I0) = R5;
      DM(0, I1) = R2;
      DM(1, I1) = R3;

.GLOBAL wr_fft_noswap.;
wr_fft_noswap.:
      R12 = LSHIFT R9 BY -1;            // m = N / 2

.GLOBAL wr_fft_carry.;
wr_fft_carry.:
      R13 = R11 AND R12;
      IF EQ JUMP 0x16f83a;              // -> wr_fft_carried.
      R11 = R11 - R12;                  // that bit was set: clear it, carry down
      R12 = LSHIFT R12 BY -1;
      JUMP 0x16f82e;                    // -> wr_fft_carry.

.GLOBAL wr_fft_carried.;
wr_fft_carried.:
      R11 = R11 + R12;                  // the first clear bit from the top, set
      R7 = 1;
      R10 = R10 + R7;
      COMPU(R10, R9);
      IF LT JUMP 0x16f808;              // -> wr_fft_rev.

      // -- the butterflies: half (bytes) 8, 16, .. N * 4; span = 2 half
      R9 = LSHIFT R9 BY 3;              // N * 8: the data's length in bytes
      R9 = R8 + R9;                     // its end
      R10 = 8;                          // half, bytes
      R11 = 16;                         // span, bytes
      R14 = DM(0x2e400c);               // the twiddle stride, bytes (NMAX/2 entries x 8 at span 2)

.GLOBAL wr_fft_stage.;
wr_fft_stage.:
      R12 = R12 - R12;                  // k, bytes (0 .. half - 8)
      R13 = DM(0x2e4008);               // the twiddle for k = 0

.GLOBAL wr_fft_k.;
wr_fft_k.:
      I2 = R13;
      R0 = DM(0, I2);                   // wr
      R1 = DM(1, I2);                   // wi (-sin)
      R6 = DM(0x2e4010);                // SIGN
      F1 = F1 * F6;
      R15 = R8 + R12;                   // a = data + k

.GLOBAL wr_fft_bfly.;
wr_fft_bfly.:
      I0 = R15;
      R7 = R15 + R10;                   // b = a + half
      I1 = R7;
      R2 = DM(0, I0);                   // xr
      R3 = DM(1, I0);                   // xi
      R4 = DM(0, I1);                   // yr
      R5 = DM(1, I1);                   // yi
      F6 = F0 * F4;
      F7 = F1 * F5;
      F6 = F6 - F7;                     // tr = wr yr - wi yi
      F7 = F0 * F5;
      F4 = F1 * F4;
      F7 = F7 + F4;                     // ti = wr yi + wi yr
      F4 = F2 - F6;
      DM(0, I1) = R4;
      F5 = F3 - F7;
      DM(1, I1) = R5;
      F2 = F2 + F6;
      DM(0, I0) = R2;
      F3 = F3 + F7;
      DM(1, I0) = R3;
      R15 = R15 + R11;                  // the next group
      COMPU(R15, R9);
      IF LT JUMP 0x16f85f;              // -> wr_fft_bfly.

      R7 = 8;
      R12 = R12 + R7;                   // k + 1
      R13 = R13 + R14;                  // its twiddle
      COMPU(R12, R10);
      IF LT JUMP 0x16f853;              // -> wr_fft_k.

      R10 = LSHIFT R10 BY 1;
      R11 = LSHIFT R11 BY 1;
      R14 = LSHIFT R14 BY -1;
      R7 = R9 - R8;                     // N * 8
      COMPU(R10, R7);
      IF LT JUMP 0x16f84f;              // -> wr_fft_stage.
      RTS;
