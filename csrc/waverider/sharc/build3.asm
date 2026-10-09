// build3.asm -- Waverider stage 3: the pool's levels, built on the DSP in its idle time.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in) and the post-fixes in scripts/sharc_waverider_m3.py.
//
// The idle loop's back edge jumps here; this goes on to idle_load.asm's wr_idle. The
// ColdFire (pool.c) loads each pool table as it is stored (int16, frame-major) into the
// load area, then the request directory, its magic last (load.asm writes both):
//
//   0x807ff000  'WRP3'  +4 count  +8 generation  +16 entry[j]: frames | points << 16, 0 none
//   0x80800000 + j x 512 KiB  entry j's table
//
// A new generation starts again at entry 0. Entry by entry this builds the table's levels
// at LEVELS + j x 0x201000 in dnfw.waverider.table3's layout (the header from the
// template for its N, then every level's guarded int16 rows) and only then names it in
// the directory pool.asm reads (BUILT[j] = its address | 1): while an entry is rebuilt it
// is 0, so a voice plays Prim. there and never a half-built table. A geometry outside 1..64
// frames of 64..4096 points (a power of two) stays 0. While the magic is not 'WRP3' (the
// ColdFire clears it before a fill rewrites the tables) nothing is built.
//
// One call does one pair of frames (two frames through one complex FFT, as
// sharc_mipb3_check.py runs it): mipb3's in, fft3 forward, spec3's split, level 0's rows
// from the frames themselves, then per level k >= 1 spec3's join, an fft3 of L points and
// mipb3's out (frame a's level the result's imaginary part, read on PM; frame b's its
// real part). An odd last frame is paired with itself; its twin's rows go to a scratch
// row. Afterwards idle_load.asm's previous-pass time is set to now, so the call counts
// as neither idle time nor one busy stretch.
//
// It saves what it and fft3/spec3/mipb3 change that the idle loop could hold (R0-R15,
// I0-I6, I8-I14, M0-M4, M8-M12) and restores them before wr_idle; it sets its own M0,
// M1 and changes none of M5-M7, M13-M15, I7, L or B. Every array is read on the bus
// that wrote it (scripts/sharc_bus_check.py).
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x172580 (L1 block 1, byte 0x2e4b00); the
// absolute CALLs and JUMPs are written by scripts/sharc_resolve_jumps.py.
//
// DM (byte addresses):
//   0x2e4100  BUILT[0 .. 127]
//   0x2e4300  GEN  +4 J  +8 F (the next frame; 0: entry J not started)  +0xc FRAMES
//     +0x10 POINTS  +0x14 log2 N  +0x18 K  +0x1c TEMPLATE  +0x20 SLOT  +0x24 RAW (frame
//     f's table row)  +0x28 S (log2 N + 1)  +0x2c the level  +0x30 row a  +0x34 row b
//     +0x38 pairs built  +0x3c tables built  +0x40 L  +0x44 log2 L  +0x48 H
//   0x2e4350  ROWS[0 .. 15]: each level's row for frame F
//   0x2e43a0  save: R0-R15, I0-I6 (+0x40), I8-I14 (+0x5c), M0-M4 (+0x78), M8-M12 (+0x8c)
// DDR: the templates at 0x80700000 (1 KB per N, by log2 N - 6: the header with F = 1, a
// record's word 0 the bytes a frame takes before its level, then a build row per level
// at +0x240: L, log2 L, H, a row's bytes), S per F at 0x80701c00, the twiddles (N 4096) at
// 0x80702000 (cos) and 0x80706000 (-sin), the arrays from 0x84800000 32 KB apart: src re,
// src im, dst re, dst im, Ar, Ai, Br, Bi, Zr, Zi, the scratch row.

.SECTION/PM seg_pmco;
.NOCOMPRESS;

.GLOBAL wr_build3.;
wr_build3.:
      DM(0x2e43a0) = R0;
      DM(0x2e43a4) = R1;
      R0 = DM(0x807ff000);
      R1 = 0x57525033;                  // 'WRP3'
      COMP(R0, R1);
      IF NE JUMP wr_build3_quiet.;
      R0 = DM(0x807ff008);
      R1 = DM(0x2e4300);
      COMP(R0, R1);
      IF NE JUMP wr_build3_work.;       // a new generation
      R0 = DM(0x2e4304);
      R1 = 128;
      COMP(R0, R1);
      IF LT JUMP wr_build3_work.;       // entries left
.GLOBAL wr_build3_quiet.;
wr_build3_quiet.:
      R0 = DM(0x2e43a0);
      R1 = DM(0x2e43a4);
      JUMP 0x16f500;                    // -> wr_idle.

.GLOBAL wr_build3_work.;
wr_build3_work.:
      DM(0x2e43a8) = R2;
      DM(0x2e43ac) = R3;
      DM(0x2e43b0) = R4;
      DM(0x2e43b4) = R5;
      DM(0x2e43b8) = R6;
      DM(0x2e43bc) = R7;
      DM(0x2e43c0) = R8;
      DM(0x2e43c4) = R9;
      DM(0x2e43c8) = R10;
      DM(0x2e43cc) = R11;
      DM(0x2e43d0) = R12;
      DM(0x2e43d4) = R13;
      DM(0x2e43d8) = R14;
      DM(0x2e43dc) = R15;
      DM(0x2e43e0) = I0;
      DM(0x2e43e4) = I1;
      DM(0x2e43e8) = I2;
      DM(0x2e43ec) = I3;
      DM(0x2e43f0) = I4;
      DM(0x2e43f4) = I5;
      DM(0x2e43f8) = I6;
      DM(0x2e43fc) = I8;
      DM(0x2e4400) = I9;
      DM(0x2e4404) = I10;
      DM(0x2e4408) = I11;
      DM(0x2e440c) = I12;
      DM(0x2e4410) = I13;
      DM(0x2e4414) = I14;
      DM(0x2e4418) = M0;
      DM(0x2e441c) = M1;
      DM(0x2e4420) = M2;
      DM(0x2e4424) = M3;
      DM(0x2e4428) = M4;
      DM(0x2e442c) = M8;
      DM(0x2e4430) = M9;
      DM(0x2e4434) = M10;
      DM(0x2e4438) = M11;
      DM(0x2e443c) = M12;

      // a new generation starts at entry 0
      R0 = DM(0x807ff008);
      R1 = DM(0x2e4300);
      COMP(R0, R1);
      IF EQ JUMP wr_build3_same.;
      DM(0x2e4300) = R0;
      R0 = R0 - R0;
      DM(0x2e4304) = R0;
      DM(0x2e4308) = R0;
.GLOBAL wr_build3_same.;
wr_build3_same.:
      R0 = DM(0x2e4308);
      R0 = PASS R0;
      IF NE JUMP wr_build3_pair.;       // entry J under way
      CALL wr_build3_start.;
      R0 = PASS R0;
      IF EQ JUMP wr_build3_out.;        // nothing to build there: the next entry next call
.GLOBAL wr_build3_pair.;
wr_build3_pair.:
      CALL wr_build3_frames.;

.GLOBAL wr_build3_out.;
wr_build3_out.:
      R2 = DM(0x2e43a8);
      R3 = DM(0x2e43ac);
      R4 = DM(0x2e43b0);
      R5 = DM(0x2e43b4);
      R6 = DM(0x2e43b8);
      R7 = DM(0x2e43bc);
      R8 = DM(0x2e43c0);
      R9 = DM(0x2e43c4);
      R10 = DM(0x2e43c8);
      R11 = DM(0x2e43cc);
      R12 = DM(0x2e43d0);
      R13 = DM(0x2e43d4);
      R14 = DM(0x2e43d8);
      R15 = DM(0x2e43dc);
      I0 = DM(0x2e43e0);
      I1 = DM(0x2e43e4);
      I2 = DM(0x2e43e8);
      I3 = DM(0x2e43ec);
      I4 = DM(0x2e43f0);
      I5 = DM(0x2e43f4);
      I6 = DM(0x2e43f8);
      I8 = DM(0x2e43fc);
      I9 = DM(0x2e4400);
      I10 = DM(0x2e4404);
      I11 = DM(0x2e4408);
      I12 = DM(0x2e440c);
      I13 = DM(0x2e4410);
      I14 = DM(0x2e4414);
      M0 = DM(0x2e4418);
      M1 = DM(0x2e441c);
      M2 = DM(0x2e4420);
      M3 = DM(0x2e4424);
      M4 = DM(0x2e4428);
      M8 = DM(0x2e442c);
      M9 = DM(0x2e4430);
      M10 = DM(0x2e4434);
      M11 = DM(0x2e4438);
      M12 = DM(0x2e443c);
.COMPRESS;
      R0 = EMUCLK;
.NOCOMPRESS;
      DM(0x2de10c) = R0;                // idle_load's previous pass: now
      R0 = DM(0x2e43a0);
      R1 = DM(0x2e43a4);
      JUMP 0x16f500;                    // -> wr_idle.

// -- entry J: its geometry, BUILT[J] = 0, the header. R0 = 1: a table to build, its
// first pair now; R0 = 0: none there (J moves on, F stays 0).
.GLOBAL wr_build3_start.;
wr_build3_start.:
      R8 = 1;
      R2 = DM(0x2e4304);                // J
      R3 = LSHIFT R2 BY 2;
      R4 = 0x2e4100;
      R4 = R3 + R4;
      I0 = R4;
      R0 = R0 - R0;
      DM(0, I0) = R0;                   // BUILT[J] = 0 while it is rebuilt
      R1 = DM(0x807ff004);              // the directory's count
      COMP(R2, R1);
      IF GE JUMP wr_build3_skip.;
      R4 = 0x807ff010;
      R4 = R3 + R4;
      I0 = R4;
      R1 = DM(0, I0);                   // frames | points << 16
      R5 = 0xffff;
      R5 = R1 AND R5;                   // F
      R6 = LSHIFT R1 BY -16;            // N
      R7 = 1;
      COMP(R5, R7);
      IF LT JUMP wr_build3_skip.;
      R7 = 64;
      COMP(R5, R7);
      IF GT JUMP wr_build3_skip.;
      COMP(R6, R7);
      IF LT JUMP wr_build3_skip.;
      R7 = 4096;
      COMP(R6, R7);
      IF GT JUMP wr_build3_skip.;
      R7 = R6 - R8;
      R7 = R6 AND R7;
      IF NE JUMP wr_build3_skip.;       // not a power of two
      R7 = LEFTZ R6;
      R9 = 31;
      R7 = R9 - R7;                     // log2 N
      DM(0x2e430c) = R5;
      DM(0x2e4310) = R6;
      DM(0x2e4314) = R7;
      R9 = R8 + R7;
      DM(0x2e4328) = R9;                // S = log2 N + 1
      R9 = -6;
      R10 = R7 + R9;
      R10 = LSHIFT R10 BY 10;
      R9 = 0x80700000;
      R10 = R9 + R10;                   // its template
      DM(0x2e431c) = R10;
      R11 = LSHIFT R2 BY 21;
      R12 = LSHIFT R2 BY 12;
      R11 = R11 + R12;
      R12 = 0x84900000;
      R11 = R11 + R12;                  // its levels: LEVELS + J x 0x201000
      DM(0x2e4320) = R11;
      R12 = LSHIFT R2 BY 19;
      R13 = 0x80800000;
      R12 = R12 + R13;                  // its table as stored: frame 0
      DM(0x2e4324) = R12;

      // the header: the template's first 0x230 bytes, then F, S, F - 1
      I0 = R10;
      I1 = R11;
      M0 = 1;
      LCNTR = 140, DO wr_build3_copy. UNTIL LCE;
      R0 = DM(I0, M0);
.GLOBAL wr_build3_copy.;
wr_build3_copy.:
      DM(I1, M0) = R0;
      I1 = R11;
      DM(0, I1) = R5;                   // F
      R14 = R5 - R8;                    // F - 1
      R13 = LSHIFT R14 BY 2;
      R15 = 0x80701c00;
      R13 = R15 + R13;
      I2 = R13;
      R0 = DM(0, I2);
      DM(1, I1) = R0;                   // S for F (table3.scale)
      DM(2, I1) = R14;
      R4 = DM(3, I1);                   // K - 1
      R4 = R8 + R4;
      DM(0x2e4318) = R4;                // K

      // each record's word 0: 0x400 + F x a frame's bytes before the level (exact in
      // float32: under 2^24); each level's row of frame 0 at that offset
      F2 = FLOAT R5;
      R3 = 0x50;
      R3 = R11 + R3;
      I0 = R3;
      M1 = 8;                           // a record: 32 bytes
      R0 = 0x2e4350;
      I2 = R0;
      R15 = 0x400;
      LCNTR = R4, DO wr_build3_rec. UNTIL LCE;
      R0 = DM(0, I0);
      F0 = FLOAT R0;
      F0 = F0 * F2;
      R0 = FIX F0;
      R0 = R15 + R0;
      DM(I0, M1) = R0;                  // the level's offset in the table
      R0 = R11 + R0;
.GLOBAL wr_build3_rec.;
wr_build3_rec.:
      DM(I2, M0) = R0;                  // ROWS[k]
      R0 = 1;
      RTS;
.GLOBAL wr_build3_skip.;
wr_build3_skip.:
      R2 = DM(0x2e4304);
      R2 = R8 + R2;
      DM(0x2e4304) = R2;                // the next entry
      R0 = R0 - R0;
      RTS;

// -- frames F and F + 1 of entry J: every level's rows
.GLOBAL wr_build3_frames.;
wr_build3_frames.:
      R0 = DM(0x2e4324);
      DM(0x2e40c0) = R0;                // mipb3 in: frame a
      R1 = DM(0x2e4310);
      R1 = LSHIFT R1 BY 1;              // a frame's bytes
      R8 = 1;
      R2 = DM(0x2e4308);
      R3 = R8 + R2;                     // F + 1
      R4 = DM(0x2e430c);
      COMP(R3, R4);
      IF GE JUMP wr_build3_twin.;       // F is the last frame: b = a
      R0 = R1 + R0;
.GLOBAL wr_build3_twin.;
wr_build3_twin.:
      DM(0x2e40c4) = R0;                // frame b
      R0 = DM(0x2e4310);
      DM(0x2e40c8) = R0;                // N
      R0 = 0x84800000;
      DM(0x2e40cc) = R0;                // src re
      R0 = 0x84808000;
      DM(0x2e40d0) = R0;                // src im
      CALL 0x172400;                    // -> wr_mipb3_in.

      R0 = 0x84800000;
      DM(0x2e4060) = R0;                // fft3: src re
      R0 = 0x84808000;
      DM(0x2e4064) = R0;                // src im
      R0 = 0x84810000;
      DM(0x2e4068) = R0;                // dst re
      R0 = 0x84818000;
      DM(0x2e406c) = R0;                // dst im
      R0 = DM(0x2e4310);
      DM(0x2e4070) = R0;                // M = N
      R0 = DM(0x2e4314);
      DM(0x2e4074) = R0;
      R0 = 0x80702000;
      DM(0x2e4078) = R0;                // TWR
      R0 = 0x80706000;
      DM(0x2e407c) = R0;                // TWI
      CALL 0x171c00;                    // -> wr_fft3.

      R0 = 0x84810000;
      DM(0x2e40a0) = R0;                // split: Z re
      R0 = 0x84818000;
      DM(0x2e40a4) = R0;                // Z im
      R0 = DM(0x2e4310);
      DM(0x2e40a8) = R0;                // N
      R0 = 0x84820000;
      DM(0x2e40ac) = R0;                // Ar
      R0 = 0x84828000;
      DM(0x2e40b0) = R0;                // Ai
      R0 = 0x84830000;
      DM(0x2e40b4) = R0;                // Br
      R0 = 0x84838000;
      DM(0x2e40b8) = R0;                // Bi
      CALL 0x172280;                    // -> wr_spec3_split.

      // level 0: the frames themselves (S = 0)
      R13 = R13 - R13;
      CALL wr_build3_rows.;
      R0 = 0x84800000;
      DM(0x2e40d4) = R0;                // out: src re (frame a)
      R0 = DM(0x2e4310);
      DM(0x2e40d8) = R0;                // L = N
      R0 = DM(0x2e4330);
      DM(0x2e40dc) = R0;                // row a
      R0 = R0 - R0;
      DM(0x2e40e0) = R0;                // S = 0
      CALL 0x172457;                    // -> wr_mipb3_out.
      R0 = 0x84808000;
      DM(0x2e40d4) = R0;                // src im (frame b), on PM
      R0 = DM(0x2e4334);
      DM(0x2e40dc) = R0;                // row b
      CALL 0x1724cf;                    // -> wr_mipb3_out_pm.

      R0 = 1;
      DM(0x2e432c) = R0;                // level 1
.GLOBAL wr_build3_level.;
wr_build3_level.:
      R13 = DM(0x2e432c);
      R1 = DM(0x2e4318);
      COMP(R13, R1);
      IF GE JUMP wr_build3_levels_done.;
      CALL wr_build3_rows.;
      R0 = 0x84840000;
      DM(0x2e40a0) = R0;                // join: Z re (W = i conj Z, spec3.asm)
      R0 = 0x84848000;
      DM(0x2e40a4) = R0;                // Z im
      R0 = DM(0x2e4340);
      DM(0x2e40a8) = R0;                // L
      R0 = 0x84820000;
      DM(0x2e40ac) = R0;
      R0 = 0x84828000;
      DM(0x2e40b0) = R0;
      R0 = 0x84830000;
      DM(0x2e40b4) = R0;
      R0 = 0x84838000;
      DM(0x2e40b8) = R0;
      R0 = DM(0x2e4348);
      DM(0x2e40bc) = R0;                // H
      CALL 0x1722e9;                    // -> wr_spec3_join.

      R0 = 0x84840000;
      DM(0x2e4060) = R0;                // fft3: Z re
      R0 = 0x84848000;
      DM(0x2e4064) = R0;                // Z im
      R0 = 0x84810000;
      DM(0x2e4068) = R0;
      R0 = 0x84818000;
      DM(0x2e406c) = R0;
      R0 = DM(0x2e4340);
      DM(0x2e4070) = R0;                // M = L
      R0 = DM(0x2e4344);
      DM(0x2e4074) = R0;
      R0 = 0x80702000;
      DM(0x2e4078) = R0;
      R0 = 0x80706000;
      DM(0x2e407c) = R0;
      CALL 0x171c00;                    // -> wr_fft3.

      R0 = 0x84818000;
      DM(0x2e40d4) = R0;                // out: frame a's level, the result's imaginary part (PM)
      R0 = DM(0x2e4340);
      DM(0x2e40d8) = R0;                // L
      R0 = DM(0x2e4330);
      DM(0x2e40dc) = R0;                // row a
      R0 = DM(0x2e4328);
      DM(0x2e40e0) = R0;                // S = log2 N + 1
      CALL 0x1724cf;                    // -> wr_mipb3_out_pm.
      R0 = 0x84810000;
      DM(0x2e40d4) = R0;                // frame b's level, the real part (DM)
      R0 = DM(0x2e4334);
      DM(0x2e40dc) = R0;                // row b
      CALL 0x172457;                    // -> wr_mipb3_out.

      R8 = 1;
      R0 = DM(0x2e432c);
      R0 = R8 + R0;
      DM(0x2e432c) = R0;
      JUMP wr_build3_level.;

.GLOBAL wr_build3_levels_done.;
wr_build3_levels_done.:
      R8 = 1;
      R0 = DM(0x2e4310);
      R0 = LSHIFT R0 BY 2;              // two frames' bytes
      R1 = DM(0x2e4324);
      R1 = R0 + R1;
      DM(0x2e4324) = R1;                // RAW: the next pair
      R0 = DM(0x2e4338);
      R0 = R8 + R0;
      DM(0x2e4338) = R0;                // pairs built
      R9 = 2;
      R0 = DM(0x2e4308);
      R0 = R9 + R0;
      DM(0x2e4308) = R0;                // F += 2
      R1 = DM(0x2e430c);
      COMP(R0, R1);
      IF LT JUMP wr_build3_more.;
      // the table is whole: name it
      R2 = DM(0x2e4304);
      R3 = LSHIFT R2 BY 2;
      R4 = 0x2e4100;
      R4 = R3 + R4;
      I0 = R4;
      R0 = DM(0x2e4320);
      R0 = R8 OR R0;
      DM(0, I0) = R0;                   // BUILT[J] = its levels | 1
      R2 = R8 + R2;
      DM(0x2e4304) = R2;                // J + 1
      R0 = R0 - R0;
      DM(0x2e4308) = R0;                // F = 0
      R0 = DM(0x2e433c);
      R0 = R8 + R0;
      DM(0x2e433c) = R0;                // tables built
.GLOBAL wr_build3_more.;
wr_build3_more.:
      RTS;

// -- level R13 (k): L, log2 L, H to the state; row a = ROWS[k], row b the next row (the
// scratch row when frame b is frame a's twin); ROWS[k] moves on two rows
.GLOBAL wr_build3_rows.;
wr_build3_rows.:
      R0 = LSHIFT R13 BY 4;
      R1 = DM(0x2e431c);
      R0 = R1 + R0;
      R1 = 0x240;
      R0 = R1 + R0;
      I0 = R0;                          // the template's build row k
      R2 = DM(0, I0);
      DM(0x2e4340) = R2;                // L
      R2 = DM(1, I0);
      DM(0x2e4344) = R2;                // log2 L
      R2 = DM(2, I0);
      DM(0x2e4348) = R2;                // H
      R5 = DM(3, I0);                   // a row's bytes
      R0 = LSHIFT R13 BY 2;
      R1 = 0x2e4350;
      R0 = R1 + R0;
      I1 = R0;
      R6 = DM(0, I1);
      DM(0x2e4330) = R6;                // row a
      R7 = R5 + R6;                     // row b
      R8 = 1;
      R9 = DM(0x2e4308);
      R9 = R8 + R9;
      R10 = DM(0x2e430c);
      COMP(R9, R10);
      IF LT JUMP wr_build3_rowb.;
      R7 = 0x84850000;                  // frame a's twin: the scratch row
.GLOBAL wr_build3_rowb.;
wr_build3_rowb.:
      DM(0x2e4334) = R7;
      R5 = LSHIFT R5 BY 1;
      R6 = R5 + R6;
      DM(0, I1) = R6;                   // ROWS[k]: two rows on
      RTS;
.wr_build3..end:
