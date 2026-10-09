// selftest.asm -- does the stage 3 FFT run on the DSP as it runs in the emulator?
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in) and the post-fixes in scripts/sharc_waverider_m3.py. A diagnostic, never a
// mod: the build is scripts/build_selftest.py.
//
// In the idle task (the idle loop's back edge jumps here, as for ddrscan.asm; this goes on
// to idle_load.asm's wr_idle), every call runs the whole level build for two frames
// (dnfw.waverider.selftest's sizes and data, in DDR at boot): fft3 forward, spec3's split,
// then per level spec3's join and an inverse fft3. It folds every output word (both
// spectra, every level of both frames) into a hash, h = rotl(h, 5) XOR word, and keeps the
// first run's as REF: a later run that differs means something changed the computation
// between runs (an interrupt or a task switch that does not keep what this code uses).
// The host compares REF with the emulator's hash of the same build
// (scripts/sharc_selftest_check.py): equal means the silicon runs these forms (SIMD
// multifunction with DM and PM transfers, BITREV, F1-active loops, ...) as the emulator
// models them. Cycles from EMUCLK (PRM "Emulation clock counter": readable in user space).
//
// PUB[0] runs  [1] runs whose hash differs from REF  [2] REF low 27 bits  [3] REF >> 27
// [4] the last hash low 27  [5] its >> 27  [6] forward cycles  [7] split  [8] the levels
// [9] a whole run.  One entry a call goes to reply word 2 of both reply pages as
// IDX << 27 | (value & 0x7ffffff), halves swapped (tools/dn2selftest.py), as ddrscan.asm.
//
// It saves what it and fft3/spec3 change that the idle loop could hold (R0-R15, I0-I6,
// I8-I14, M0-M4, M8-M12, LCNTR) and restores them before wr_idle. It reads M6 (= 1, the C
// runtime's constant) and changes none of M5-M7, M13-M15, I7, L or B.
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16f800 (L1 block 1, byte 0x2df000).
//
// DM (byte addresses, the state block at 0x2df800):
//   0x2df800..  save: R0-R15 (+0), I0-I6 (+0x40), I8-I14 (+0x5c), M0-M4 (+0x78),
//               M8-M12 (+0x8c), LCNTR (+0xa0)
//   0x2df8a4 the level row  0x2df8a8 H (the hash)  0x2df8ac T0  0x2df8b0 T1  0x2df8b4 T2
//   0x2df8b8 levels left  0x2df8bc IDX (the PUB entry last published)
//   0x2df8c0 PUB[0..9]
//   0x2df900 the test: +0 N  +4 log2 N  +8 levels after 0  +12 SRC_RE  +16 SRC_IM
//     +20 DST_RE  +24 DST_IM  +28 TWR  +32 TWI  +36 AR  +40 AI  +44 BR  +48 BI  +52 ZR
//     +56 ZI  +64.. a level a row of 16 bytes: L, log2 L, H, 0

.SECTION/PM seg_pmco;
.NOCOMPRESS;

.GLOBAL wr_selftest.;
wr_selftest.:
      DM(0x2df800) = R0;
      DM(0x2df804) = R1;
      DM(0x2df808) = R2;
      DM(0x2df80c) = R3;
      DM(0x2df810) = R4;
      DM(0x2df814) = R5;
      DM(0x2df818) = R6;
      DM(0x2df81c) = R7;
      DM(0x2df820) = R8;
      DM(0x2df824) = R9;
      DM(0x2df828) = R10;
      DM(0x2df82c) = R11;
      DM(0x2df830) = R12;
      DM(0x2df834) = R13;
      DM(0x2df838) = R14;
      DM(0x2df83c) = R15;
      DM(0x2df840) = I0;
      DM(0x2df844) = I1;
      DM(0x2df848) = I2;
      DM(0x2df84c) = I3;
      DM(0x2df850) = I4;
      DM(0x2df854) = I5;
      DM(0x2df858) = I6;
      DM(0x2df85c) = I8;
      DM(0x2df860) = I9;
      DM(0x2df864) = I10;
      DM(0x2df868) = I11;
      DM(0x2df86c) = I12;
      DM(0x2df870) = I13;
      DM(0x2df874) = I14;
      DM(0x2df878) = M0;
      DM(0x2df87c) = M1;
      DM(0x2df880) = M2;
      DM(0x2df884) = M3;
      DM(0x2df888) = M4;
      DM(0x2df88c) = M8;
      DM(0x2df890) = M9;
      DM(0x2df894) = M10;
      DM(0x2df898) = M11;
      DM(0x2df89c) = M12;
      DM(0x2df8a0) = LCNTR;

      R0 = EMUCLK;
      DM(0x2df8ac) = R0;                // T0
      R0 = R0 - R0;
      DM(0x2df8a8) = R0;                // H = 0

      // -- fft3 forward: SRC -> DST, N points
      R0 = DM(0x2df90c);
      DM(0x2e4060) = R0;
      R0 = DM(0x2df910);
      DM(0x2e4064) = R0;
      R0 = DM(0x2df914);
      DM(0x2e4068) = R0;
      R0 = DM(0x2df918);
      DM(0x2e406c) = R0;
      R0 = DM(0x2df900);
      DM(0x2e4070) = R0;
      R0 = DM(0x2df904);
      DM(0x2e4074) = R0;
      R0 = DM(0x2df91c);
      DM(0x2e4078) = R0;
      R0 = DM(0x2df920);
      DM(0x2e407c) = R0;
      CALL 0x171000;                    // wr_fft3
      R0 = EMUCLK;
      DM(0x2df8b0) = R0;                // T1

      // -- spec3 split: DST -> A, B
      R0 = DM(0x2df914);
      DM(0x2e40a0) = R0;
      R0 = DM(0x2df918);
      DM(0x2e40a4) = R0;
      R0 = DM(0x2df900);
      DM(0x2e40a8) = R0;
      R0 = DM(0x2df924);
      DM(0x2e40ac) = R0;
      R0 = DM(0x2df928);
      DM(0x2e40b0) = R0;
      R0 = DM(0x2df92c);
      DM(0x2e40b4) = R0;
      R0 = DM(0x2df930);
      DM(0x2e40b8) = R0;
      CALL 0x171400;                    // wr_spec3_split
      R0 = EMUCLK;
      DM(0x2df8b4) = R0;                // T2

      R2 = DM(0x2df900);
      R2 = LSHIFT R2 BY -1;
      R2 = R2 + 1;                      // N/2 + 1 bins
      R0 = DM(0x2df924);
      CALL wr_selftest_hash.;           // AR
      R0 = DM(0x2df928);
      CALL wr_selftest_hash.;           // AI
      R0 = DM(0x2df92c);
      CALL wr_selftest_hash.;           // BR
      R0 = DM(0x2df930);
      CALL wr_selftest_hash.;           // BI

      // -- the levels: join, inverse fft3 (ZI, ZR -> DST_IM, DST_RE), hash both
      R0 = 0x2df940;
      DM(0x2df8a4) = R0;                // the level row (IDX's word, reused until publish)
      R1 = DM(0x2df908);                // levels
.GLOBAL wr_selftest_level.;
wr_selftest_level.:
      DM(0x2df8b8) = R1;                // levels left
      R0 = DM(0x2df8a4);
      I0 = R0;
      R3 = DM(0, I0);                   // L
      R4 = DM(1, I0);                   // log2 L
      R5 = DM(2, I0);                   // H
      R0 = DM(0x2df934);
      DM(0x2e40a0) = R0;                // ZR
      R0 = DM(0x2df938);
      DM(0x2e40a4) = R0;                // ZI
      DM(0x2e40a8) = R3;                // L
      R0 = DM(0x2df924);
      DM(0x2e40ac) = R0;
      R0 = DM(0x2df928);
      DM(0x2e40b0) = R0;
      R0 = DM(0x2df92c);
      DM(0x2e40b4) = R0;
      R0 = DM(0x2df930);
      DM(0x2e40b8) = R0;
      DM(0x2e40bc) = R5;                // H
      CALL 0x171469;                    // wr_spec3_join (dnfw.waverider.selftest checks it)
      R0 = DM(0x2df8a4);
      I0 = R0;
      R3 = DM(0, I0);
      R4 = DM(1, I0);
      R0 = DM(0x2df938);
      DM(0x2e4060) = R0;                // source re: ZI (the inverse)
      R0 = DM(0x2df934);
      DM(0x2e4064) = R0;                // source im: ZR
      R0 = DM(0x2df918);
      DM(0x2e4068) = R0;                // dest re: DST_IM
      R0 = DM(0x2df914);
      DM(0x2e406c) = R0;                // dest im: DST_RE
      DM(0x2e4070) = R3;
      DM(0x2e4074) = R4;
      R0 = DM(0x2df91c);
      DM(0x2e4078) = R0;
      R0 = DM(0x2df920);
      DM(0x2e407c) = R0;
      CALL 0x171000;                    // wr_fft3
      R0 = DM(0x2df8a4);
      I0 = R0;
      R2 = DM(0, I0);                   // L words each
      R0 = DM(0x2df914);
      CALL wr_selftest_hash.;           // frame a's level
      R0 = DM(0x2df8a4);
      I0 = R0;
      R2 = DM(0, I0);
      R0 = DM(0x2df918);
      CALL wr_selftest_hash.;           // frame b's level
      R0 = DM(0x2df8a4);
      R1 = 16;
      R0 = R0 + R1;
      DM(0x2df8a4) = R0;                // the next row
      R1 = DM(0x2df8b8);
      R1 = R1 - 1;
      IF NE JUMP wr_selftest_level.;

      // -- the run's cycles and hash
      R0 = EMUCLK;
      R1 = DM(0x2df8b4);
      R1 = R0 - R1;
      DM(0x2df8e0) = R1;                // PUB[8]: the levels
      R1 = DM(0x2df8ac);
      R1 = R0 - R1;
      DM(0x2df8e4) = R1;                // PUB[9]: the run
      R1 = DM(0x2df8b0);
      R2 = DM(0x2df8ac);
      R1 = R1 - R2;
      DM(0x2df8d8) = R1;                // PUB[6]: forward
      R1 = DM(0x2df8b4);
      R2 = DM(0x2df8b0);
      R1 = R1 - R2;
      DM(0x2df8dc) = R1;                // PUB[7]: split
      R0 = DM(0x2df8a8);                // H
      R1 = LSHIFT R0 BY -27;
      DM(0x2df8d4) = R1;                // PUB[5]
      R1 = 0x7ffffff;
      R1 = R0 AND R1;
      DM(0x2df8d0) = R1;                // PUB[4]
      R1 = DM(0x2df8c0);                // runs before this one
      R1 = PASS R1;
      IF NE JUMP wr_selftest_compare.;
      R1 = LSHIFT R0 BY -27;            // the first run: REF
      DM(0x2df8cc) = R1;                // PUB[3]
      R1 = 0x7ffffff;
      R1 = R0 AND R1;
      DM(0x2df8c8) = R1;                // PUB[2]
      JUMP wr_selftest_counted.;
.GLOBAL wr_selftest_compare.;
wr_selftest_compare.:
      R1 = DM(0x2df8c8);
      R2 = DM(0x2df8d0);
      COMP(R1, R2);
      IF NE JUMP wr_selftest_differs.;
      R1 = DM(0x2df8cc);
      R2 = DM(0x2df8d4);
      COMP(R1, R2);
      IF EQ JUMP wr_selftest_counted.;
.GLOBAL wr_selftest_differs.;
wr_selftest_differs.:
      R1 = DM(0x2df8c4);
      R1 = R1 + 1;
      DM(0x2df8c4) = R1;                // PUB[1]
.GLOBAL wr_selftest_counted.;
wr_selftest_counted.:
      R1 = DM(0x2df8c0);
      R1 = R1 + 1;
      DM(0x2df8c0) = R1;                // PUB[0]: runs

      // -- publish one entry a call
      R3 = DM(0x2df8bc);                // IDX
      R3 = R3 + 1;
      R4 = 10;
      COMPU(R3, R4);
      IF LT JUMP wr_selftest_keep.;
      R3 = R3 - R3;
.GLOBAL wr_selftest_keep.;
wr_selftest_keep.:
      DM(0x2df8bc) = R3;
      R4 = LSHIFT R3 BY 2;
      R5 = 0x2df8c0;                    // PUB
      R4 = R4 + R5;
      I0 = R4;
      R4 = DM(0, I0);                   // PUB[IDX]
      R5 = 0x7ffffff;
      R4 = R4 AND R5;
      R5 = LSHIFT R3 BY 27;
      R4 = R4 OR R5;                    // IDX << 27 | value
      R5 = LSHIFT R4 BY 16;
      R4 = LSHIFT R4 BY -16;
      R4 = R4 OR R5;                    // halves swapped, as reply word 0
      DM(0x2c49d8) = R4;                // reply word 2, both pages
      DM(0x2c59d8) = R4;

      R0 = DM(0x2df800);
      R1 = DM(0x2df804);
      R2 = DM(0x2df808);
      R3 = DM(0x2df80c);
      R4 = DM(0x2df810);
      R5 = DM(0x2df814);
      R6 = DM(0x2df818);
      R7 = DM(0x2df81c);
      R8 = DM(0x2df820);
      R9 = DM(0x2df824);
      R10 = DM(0x2df828);
      R11 = DM(0x2df82c);
      R12 = DM(0x2df830);
      R13 = DM(0x2df834);
      R14 = DM(0x2df838);
      R15 = DM(0x2df83c);
      I0 = DM(0x2df840);
      I1 = DM(0x2df844);
      I2 = DM(0x2df848);
      I3 = DM(0x2df84c);
      I4 = DM(0x2df850);
      I5 = DM(0x2df854);
      I6 = DM(0x2df858);
      I8 = DM(0x2df85c);
      I9 = DM(0x2df860);
      I10 = DM(0x2df864);
      I11 = DM(0x2df868);
      I12 = DM(0x2df86c);
      I13 = DM(0x2df870);
      I14 = DM(0x2df874);
      M0 = DM(0x2df878);
      M1 = DM(0x2df87c);
      M2 = DM(0x2df880);
      M3 = DM(0x2df884);
      M4 = DM(0x2df888);
      M8 = DM(0x2df88c);
      M9 = DM(0x2df890);
      M10 = DM(0x2df894);
      M11 = DM(0x2df898);
      M12 = DM(0x2df89c);
      LCNTR = DM(0x2df8a0);
      JUMP 0x16f500;                    // -> wr_idle

// -- H = rotl(H, 5) XOR word, over R2 words from R0 (clobbers R1, R3, R4, I0)
.GLOBAL wr_selftest_hash.;
wr_selftest_hash.:
      I0 = R0;
      R1 = DM(0x2df8a8);
      LCNTR = R2, DO wr_selftest_hash_end. UNTIL LCE;
      R3 = DM(I0, M6);                  // M6 = 1, the C runtime's constant
      R4 = LSHIFT R1 BY 5;
      R1 = LSHIFT R1 BY -27;
      R1 = R1 OR R4;
.GLOBAL wr_selftest_hash_end.;
wr_selftest_hash_end.:
      R1 = R1 XOR R3;
      DM(0x2df8a8) = R1;
      RTS;
