// fft2.asm -- Waverider stage 3: fft.asm's transform, SIMD with hardware loops.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). The same in-place radix-2 complex FFT as fft.asm (bit reversal, then
// decimation-in-time stages; SIGN -1.0 gives the unscaled inverse), written from the
// manuals (SC58x/2158x PRM) for speed:
//
// - SIMD (MODE1 PEYEN, PRM "DAG Transfers in SIMD Mode", Table 6-10): in byte-addressed
//   memory a load moves the explicit word to the named register and the word 4 bytes on
//   to its complement. Complex data is (re, im) pairs, so `R2 = DM(I0, M0)` puts re in
//   PEx and im in PEy, and `S5 = DM(...)` (PEy named) gives the pair swapped (S5 = re,
//   R5 = im).
// - With w = wr + i wi = e^(-2 pi i t / NMAX) (wr = cos, wi = -sin), the twiddles are
//   stored (-wi, wi, wr, wr) = (sin, -sin, cos, cos): Fb = (-wi, wi), Fa = (wr, wr), so
//   with y and its swap ys, t = Fa y + Fb ys = (wr yr - wi yi, wr yi + wi yr) is w y in
//   two multiplies and an add, both halves at once. The inverse takes a second table
//   with w conjugated, (-sin, sin, cos, cos): every register is in use in the loops.
// - In byte-addressed memory the DAG scales an offset or a modifier by the access size
//   (a 32-bit access: x 4), so M0 and M4 hold words, a byte step / 4.
// - Hardware loops (`LCNTR = .., DO .. UNTIL LCE`) for the stages, the twiddles and the
//   butterflies. A loop's last 11 instructions must be 48-bit (PRM 4-42): the loops sit
//   under .NOCOMPRESS. No conditional branch runs in SIMD (a branch there needs its
//   condition true in both elements, PRM "Conditional Branches").
// - Post-modify addressing walks the butterflies (I1/I0 read b and a, I2/I3 write them,
//   M0 = the span in bytes), so the innermost loop does no pointer arithmetic.
//
// Parameter block at DM 0x2e4040 (byte addresses):
//   +0 data   +4 M (complex points)   +8 log2 M   +12 TW (16-byte entries: the
//   forward table, or the inverse one)   +16 the first stage's twiddle stride in words
//   (NMAX/2 entries x 4 words)
// TW forward: (sin, -sin, cos, cos) of 2 pi t / NMAX, t = 0 .. NMAX/2 - 1; inverse:
// (-sin, sin, cos, cos).
//
// Clobbers R0-R15 and S0-S15, I0-I4, M0, M4, the loop counters; leaves MODE1's PEYEN
// clear. Not ABI-clean: the caller saves what it needs.
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16fc00 (DM 0x2df800).

.SECTION/PM seg_pmco;

.GLOBAL wr_fft2.;
wr_fft2.:
      R8 = DM(0x2e4040);                // data
      R9 = DM(0x2e4044);                // M

      // -- the indices' bits reversed (SISD, as fft.asm)
      R10 = R10 - R10;                  // i
      R11 = R11 - R11;                  // j

.GLOBAL wr_fft2_rev.;
wr_fft2_rev.:
      COMPU(R10, R11);
      IF GE JUMP 0x16fc2b;              // -> wr_fft2_noswap.
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

.GLOBAL wr_fft2_noswap.;
wr_fft2_noswap.:
      R12 = LSHIFT R9 BY -1;

.GLOBAL wr_fft2_carry.;
wr_fft2_carry.:
      R13 = R11 AND R12;
      IF EQ JUMP 0x16fc3a;              // -> wr_fft2_carried.
      R11 = R11 - R12;
      R12 = LSHIFT R12 BY -1;
      JUMP 0x16fc2e;                    // -> wr_fft2_carry.

.GLOBAL wr_fft2_carried.;
wr_fft2_carried.:
      R11 = R11 + R12;
      R7 = 1;
      R10 = R10 + R7;
      COMPU(R10, R9);
      IF LT JUMP 0x16fc08;              // -> wr_fft2_rev.

      // -- the stages, in SIMD. R10 half and R11 span (bytes), R15 the twiddles of the
      //    stage (half in points), R12 the butterflies per twiddle (M / span points),
      //    R14 the twiddle stride (words); R13 walks a = data + 8 k; R9 = 8.
      R10 = 8;
      R11 = 16;
      R15 = 1;
      R12 = LSHIFT R9 BY -1;
      R9 = 8;
      R14 = DM(0x2e4050);
      R7 = DM(0x2e4048);                // log2 M: the stages
      BIT SET MODE1 0x200000;           // PEYEN: SIMD from the next instruction on
      NOP;
.NOCOMPRESS;
      LCNTR = R7, DO wr_fft2_stage_end. UNTIL LCE;
      R7 = LSHIFT R11 BY -2;
      M0 = R7;                          // each pointer's step: the span, in words
      M4 = R14;                         // the twiddle stride, in words
      R7 = DM(0x2e404c);                // TW
      I4 = R7;
      R13 = PASS R8;                    // a for k = 0
      LCNTR = R15, DO wr_fft2_k_end. UNTIL LCE;
      R0 = DM(2, I4);                   // Fa = (wr, wr), 8 bytes on
      R1 = DM(I4, M4);                  // Fb = (-wi, wi); I4 to the next twiddle
      I0 = R13;
      I3 = R13;
      R7 = R13 + R10;                   // b = a + half
      I1 = R7;
      I2 = R7;
      LCNTR = R12, DO wr_fft2_bfly_end. UNTIL LCE;
      R4 = DM(0, I1);                   // y = (yr, yi)
      S5 = DM(I1, M0);                  // ys = (yi, yr); b += span
      F6 = F0 * F4;                     // (wr yr, wr yi)
      F7 = F1 * F5;                     // (-wi yi, wi yr)
      R2 = DM(I0, M0);                  // x = (xr, xi); a += span
      F6 = F6 + F7;                     // t = w y
      F3 = F2 - F6;
      F2 = F2 + F6;
      DM(I2, M0) = R3;                  // b = x - t
.GLOBAL wr_fft2_bfly_end.;
wr_fft2_bfly_end.:
      DM(I3, M0) = R2;                  // a = x + t
.GLOBAL wr_fft2_k_end.;
wr_fft2_k_end.:
      R13 = R13 + R9;                   // the next k
      R10 = LSHIFT R10 BY 1;
      R11 = LSHIFT R11 BY 1;
      R15 = LSHIFT R15 BY 1;
      R12 = LSHIFT R12 BY -1;
.GLOBAL wr_fft2_stage_end.;
wr_fft2_stage_end.:
      R14 = LSHIFT R14 BY -1;
.COMPRESS;
      BIT CLR MODE1 0x200000;
      NOP;
      RTS;
