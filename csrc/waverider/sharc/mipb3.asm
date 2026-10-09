// mipb3.asm -- Waverider stage 3: int16 frames in, guarded int16 level rows out.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in) and the post-fixes in scripts/sharc_waverider_m3.py. The two ends of the
// level build around fft3.asm and spec3.asm:
//
// - wr_mipb3_in: two frames of N int16 (a pool table's rows, little-endian) to the split
//   float arrays fft3 reads, frame a as the real part, frame b as the imaginary part.
// - wr_mipb3_out: L floats to one stored row as the reader reads it (dnfw.waverider.mip:
//   [last, x0 .. x(L-1), x0, x1], int16): each value times 2^-S, rounded to nearest
//   (MODE1's TRUNCATE is clear in stock), clipped to +-32767 (the model clips to -32768,
//   one LSB apart at full scale), stored 16 bits. Level 0 is the frame itself (S = 0 from
//   wr_mipb3_in's floats); level k >= 1 is fft3's inverse output, 2N times the model's
//   (spec3.asm), so S = log2 N + 1.
//
// SIMD, PEx the even sample and PEy the odd one: two samples three instructions out (a
// pair's load and conversion beside the previous pair's clip and 16-bit store), two
// points four in (two 16-bit pair loads, two conversions).
//
// Parameter block at DM 0x2e40c0 (byte addresses):
//   in:  +0 frame a  +4 frame b  +8 N  +12 dest re  +16 dest im
//   out: +20 source (floats)  +24 L  +28 the row (int16; L + 3 of them)  +32 S
//
// out_pm reads its source on PM (I8, M8). Clobbers R0-R3, R12, R13 and their S twins,
// I0-I2, I8, I10, M0-M2, M8, M10, the loop counter;
// leaves PEYEN clear. Leaves the C
// runtime's constants (M5-M7, M13-M15), I7 and the L and B registers alone.
//
// Placement: PM sw 0x172400 (DM 0x2e4800, dnfw.waverider.dsp); its jumps are PC-relative, so the
// self-test build loads the same bytes elsewhere.

.SECTION/PM seg_pmco;
.NOCOMPRESS;

// -- in: frames a, b (int16) -> dest re, im (float)
.GLOBAL wr_mipb3_in.;
wr_mipb3_in.:
      R0 = DM(0x2e40c0);
      I0 = R0;                          // frame a
      R0 = DM(0x2e40c4);
      I1 = R0;                          // frame b
      R0 = DM(0x2e40cc);
      I2 = R0;                          // dest re
      R0 = DM(0x2e40d0);
      I10 = R0;                         // dest im
      M0 = 2;                           // a pair of samples: 4 bytes as int16 (scaled by 2) ...
      M2 = 2;                           // ... 8 as floats (scaled by 4)
      M10 = 2;
      R12 = DM(0x2e40c8);               // N
      R12 = LSHIFT R12 BY -1;
      R12 = R12 - 1;                    // the loop: pairs 1 .. N/2 - 1
      BIT SET MODE1 0x200000;           // PEYEN: PEx the even sample, PEy the odd one
      NOP;
      R0 = DM(I0, M0) (SWSE);           // pair 0
      R1 = DM(I1, M0) (SWSE);
      F2 = FLOAT R0;
      F3 = FLOAT R1;
      LCNTR = R12, DO wr_mipb3_in_end. UNTIL LCE (F);
      R0 = DM(I0, M0) (SWSE);           // frame a's next pair
      R1 = DM(I1, M0) (SWSE);           // frame b's
      F2 = FLOAT R0, DM(I2, M2) = R2, PM(I10, M10) = R3;        // the last pair's floats out
.GLOBAL wr_mipb3_in_end.;
wr_mipb3_in_end.:
      F3 = FLOAT R1;
      DM(I2, M2) = R2, PM(I10, M10) = R3;                       // pair N/2 - 1
      BIT CLR MODE1 0x200000;
      NOP;
      RTS;

// -- out: L floats -> one guarded int16 row
.GLOBAL wr_mipb3_out.;
wr_mipb3_out.:
      R0 = DM(0x2e40d4);
      I0 = R0;                          // source floats
      R0 = DM(0x2e40dc);
      R1 = 2;
      R0 = R0 + R1;
      I2 = R0;                          // the row's x0, after its [last]
      M0 = 2;                           // a pair: 8 bytes as floats ...
      M2 = 2;                           // ... 4 as int16
      M1 = 1;                           // one int16 (the guards, SISD)
      R13 = DM(0x2e40e0);
      R13 = -R13;                       // FIX .. BY -S
      S13 = R13;
      R12 = 32767;
      S12 = R12;
      R3 = DM(0x2e40d8);                // L
      R3 = LSHIFT R3 BY -1;
      R3 = R3 - 1;                      // the loop: pairs 1 .. L/2 - 1
      BIT SET MODE1 0x200000;           // PEYEN: PEx the even sample, PEy the odd one
      NOP;
      F0 = DM(I0, M0);                  // pair 0
      R1 = FIX F0 BY R13;
      LCNTR = R3, DO wr_mipb3_out_end. UNTIL LCE (F);
      F0 = DM(I0, M0), R2 = CLIP R1 BY R12;                     // pair k; pair k-1 clipped
      R1 = FIX F0 BY R13;                                       // pair k times 2^-S, rounded
.GLOBAL wr_mipb3_out_end.;
wr_mipb3_out_end.:
      DM(I2, M2) = R2 (SW);                                     // pair k-1
      NOP;                              // (a FIX result two instructions before its CLIP)
      R2 = CLIP R1 BY R12;
      DM(I2, M2) = R2 (SW);                                     // pair L/2 - 1
      BIT CLR MODE1 0x200000;
      NOP;
      // the guards: [0] = x(L-1), [L+1] = x0, [L+2] = x1 (I2 is at [L+1])
      MODIFY(I2, -2);
      R2 = DM(I2, M1) (SWSE);           // x(L-1), at [L]
      R0 = DM(0x2e40dc);
      I1 = R0;
      DM(I1, M1) = R2 (SW);             // [0]
      R1 = DM(I1, M1) (SWSE);           // x0
      R3 = DM(I1, M1) (SWSE);           // x1
      DM(I2, M1) = R1 (SW);             // [L+1]
      DM(I2, M1) = R3 (SW);             // [L+2]
      RTS;

// -- out_pm: the same from a source written on PM (an imaginary array: one bus per array)
.GLOBAL wr_mipb3_out_pm.;
wr_mipb3_out_pm.:
      R0 = DM(0x2e40d4);
      I8 = R0;                          // source floats, on PM
      R0 = DM(0x2e40dc);
      R1 = 2;
      R0 = R0 + R1;
      I2 = R0;                          // the row's x0, after its [last]
      M8 = 2;                           // a pair: 8 bytes as floats ...
      M2 = 2;                           // ... 4 as int16
      M1 = 1;                           // one int16 (the guards, SISD)
      R13 = DM(0x2e40e0);
      R13 = -R13;                       // FIX .. BY -S
      S13 = R13;
      R12 = 32767;
      S12 = R12;
      R3 = DM(0x2e40d8);                // L
      R3 = LSHIFT R3 BY -1;
      R3 = R3 - 1;                      // the loop: pairs 1 .. L/2 - 1
      BIT SET MODE1 0x200000;           // PEYEN: PEx the even sample, PEy the odd one
      NOP;
      F0 = PM(I8, M8);                  // pair 0
      R1 = FIX F0 BY R13;
      LCNTR = R3, DO wr_mipb3_out_pm_end. UNTIL LCE (F);
      F0 = PM(I8, M8), R2 = CLIP R1 BY R12;                     // pair k; pair k-1 clipped
      R1 = FIX F0 BY R13;                                       // pair k times 2^-S, rounded
.GLOBAL wr_mipb3_out_pm_end.;
wr_mipb3_out_pm_end.:
      DM(I2, M2) = R2 (SW);                                     // pair k-1
      NOP;                              // (a FIX result two instructions before its CLIP)
      R2 = CLIP R1 BY R12;
      DM(I2, M2) = R2 (SW);                                     // pair L/2 - 1
      BIT CLR MODE1 0x200000;
      NOP;
      // the guards: [0] = x(L-1), [L+1] = x0, [L+2] = x1 (I2 is at [L+1])
      MODIFY(I2, -2);
      R2 = DM(I2, M1) (SWSE);           // x(L-1), at [L]
      R0 = DM(0x2e40dc);
      I1 = R0;
      DM(I1, M1) = R2 (SW);             // [0]
      R1 = DM(I1, M1) (SWSE);           // x0
      R3 = DM(I1, M1) (SWSE);           // x1
      DM(I2, M1) = R1 (SW);             // [L+1]
      DM(I2, M1) = R3 (SW);             // [L+2]
      RTS;
