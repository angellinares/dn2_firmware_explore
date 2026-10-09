// spec3.asm -- Waverider stage 3: two real frames through one complex FFT (fft3.asm).
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in) and the post-fixes in scripts/sharc_waverider_m3.py.
//
// Frame a in the real array, frame b in the imaginary one, one N-point complex FFT gives
// Z = A + iB, A and B the two frames' spectra. Each is Hermitian, so (j = N - k):
//   2A[k] = Z[k] + conj Z[j]        = (Zr[j] + Zr[k], Zi[k] - Zi[j])
//   2B[k] = (Z[k] - conj Z[j]) / i  = (Zi[k] + Zi[j], Zr[j] - Zr[k])
// two add/subtract pairs a bin, no multiply. Back, a level of L points keeping harmonics
// 0 .. H of both frames is one L-point inverse of
//   Z[k] = A[k] + i B[k]            = (Ar - Bi, Ai + Br)       k = 0 .. H
//   Z[L-k] = conj A[k] + i conj B[k] = (Ar + Bi, Br - Ai)       k = 1 .. H
// and zero between: its real part is frame a's level, its imaginary part frame b's.
// One bus per array (the DM and PM caches are not coherent for DDR): join writes
// W = i conj(Z) = (Z's imaginary part, Z's real part), and the caller runs fft3 forward on
// W and reads the result's real and imaginary parts swapped, so W re (DM) and W im (PM)
//   W[k] = (Br + Ai, Ar - Bi)       W[L-k] = (Br - Ai, Ar + Bi)
// and frame a's level is the result's imaginary part, frame b's its real part.
// The scale is left to the caller: split gives 2A and 2B, fft3's inverse is unscaled, so
// a level comes out 2L times the model's irfft(.., L) (a power of two).
//
// SISD, four instructions a bin (two loads and two stores of DM and PM each, the two
// add/subtract pairs beside them), each bin's work one instruction after its loads.
//
// Parameter block at DM 0x2e40a0 (byte addresses):
//   +0 Zr  +4 Zi  +8 N (split) or L (join)  +12 Ar  +16 Ai  +20 Br  +24 Bi  +28 H (join)
// split: Z (N points) -> A, B (bins 0 .. N/2); join: A, B (bins 0 .. H) -> Z (L points),
// H + 1 <= L/2.
//
// Clobbers R0-R7, I0-I3, I8-I11, M0-M3, M8-M10, the loop counter. SISD only.
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x171400 (DM 0x2e2800).

.SECTION/PM seg_pmco;
.NOCOMPRESS;

// -- split: Z -> 2A, 2B
.GLOBAL wr_spec3_split.;
wr_spec3_split.:
      R0 = DM(0x2e40a0);
      I0 = R0;                          // Zr[k], up
      I1 = R0;                          // Zr[j], from 0 then down from N-1
      R1 = DM(0x2e40a4);
      I8 = R1;                          // Zi[k]
      I9 = R1;                          // Zi[j]
      R0 = DM(0x2e40ac);
      I2 = R0;                          // Ar
      R0 = DM(0x2e40b0);
      I10 = R0;                         // Ai
      R0 = DM(0x2e40b4);
      I3 = R0;                          // Br
      R0 = DM(0x2e40b8);
      I11 = R0;                         // Bi
      M0 = 1;
      M8 = 1;
      M1 = -1;
      M9 = -1;
      R2 = DM(0x2e40a8);                // N
      R3 = R2 - 1;
      M2 = R3;                          // j: 0 to N-1 after bin 0
      M10 = R3;
      R2 = LSHIFT R2 BY -1;
      M3 = R2;                          // bins 1 .. N/2: the loop
      R0 = DM(I0, M0), R1 = PM(I8, M8);                         // bin 0
      R2 = DM(I1, M2), R3 = PM(I9, M10);
      F4 = F2 + F0, F5 = F2 - F0;
      F6 = F1 + F3, F7 = F1 - F3, DM(I2, M0) = R4, PM(I11, M8) = R5;    // Ar, Bi
      LCNTR = M3, DO wr_spec3_split_end. UNTIL LCE (F);
      R0 = DM(I0, M0), R1 = PM(I8, M8);                         // Zr[k], Zi[k]
      R2 = DM(I1, M1), R3 = PM(I9, M9);                         // Zr[j], Zi[j]
      F4 = F2 + F0, F5 = F2 - F0, DM(I3, M0) = R6, PM(I10, M8) = R7;    // 2Ar 2Bi; Br Ai of k-1
.GLOBAL wr_spec3_split_end.;
wr_spec3_split_end.:
      F6 = F1 + F3, F7 = F1 - F3, DM(I2, M0) = R4, PM(I11, M8) = R5;    // 2Br 2Ai; Ar Bi of k
      DM(I3, M0) = R6, PM(I10, M8) = R7;                        // Br Ai of N/2
      RTS;

// -- join: A, B (0 .. H) -> Z (L points)
.GLOBAL wr_spec3_join.;
wr_spec3_join.:
      R0 = DM(0x2e40ac);
      I0 = R0;                          // Ar
      R0 = DM(0x2e40b0);
      I8 = R0;                          // Ai
      R0 = DM(0x2e40b4);
      I1 = R0;                          // Br
      R0 = DM(0x2e40b8);
      I9 = R0;                          // Bi
      R0 = DM(0x2e40a0);
      I2 = R0;                          // Zr[k], up
      R1 = DM(0x2e40a8);                // L
      R3 = R1 - 1;
      R3 = LSHIFT R3 BY 2;
      R3 = R0 + R3;
      I3 = R3;                          // Zr[L-k], down from L-1
      R0 = DM(0x2e40a4);
      I10 = R0;                         // Zi[k]
      R3 = R1 - 1;
      R3 = LSHIFT R3 BY 2;
      R3 = R0 + R3;
      I11 = R3;                         // Zi[L-k]
      M0 = 1;
      M8 = 1;
      M1 = -1;
      M9 = -1;
      R2 = DM(0x2e40bc);                // H: the loop, bins 1 .. H
      R3 = R2 + R2;
      R3 = R3 + 1;
      R3 = R1 - R3;
      M2 = R3;                          // L - 2H - 1 zeros between
      R2 = DM(I1, M0), R1 = PM(I8, M8);                         // bin 0: Br, Ai
      F5 = F2 + F1, F4 = F2 - F1, R0 = DM(I0, M0), R3 = PM(I9, M8);     // Ar, Bi
      F7 = F0 + F3, F6 = F0 - F3, DM(I2, M0) = R5;              // W[0] re
      R2 = DM(0x2e40bc);
      LCNTR = R2, DO wr_spec3_join_end. UNTIL LCE (F);
      R2 = DM(I1, M0), R1 = PM(I8, M8);                         // Br, Ai
      F5 = F2 + F1, F4 = F2 - F1, R0 = DM(I0, M0), R3 = PM(I9, M8);     // Br +- Ai; Ar, Bi
      F7 = F0 + F3, F6 = F0 - F3, DM(I2, M0) = R5, PM(I10, M8) = R6;    // Ar +- Bi; W[k] re, W[k-1] im
.GLOBAL wr_spec3_join_end.;
wr_spec3_join_end.:
      DM(I3, M1) = R4, PM(I11, M9) = R7;                        // W[L-k]
      PM(I10, M8) = R6;                                         // W[H] im
      R0 = R0 - R0;
      LCNTR = M2, DO wr_spec3_zero_end. UNTIL LCE (F);
.GLOBAL wr_spec3_zero_end.;
wr_spec3_zero_end.:
      DM(I2, M0) = R0, PM(I10, M8) = R0;                        // H+1 .. L-H-1
      RTS;
