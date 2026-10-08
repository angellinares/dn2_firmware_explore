// reader_miph.asm -- reader_mip.asm with 4-point Hermite (Catmull-Rom) interpolation
// between samples, the SHARC study's B2, for the comparison build (owner, 2026-10-08:
// "compare the performance on the machine"). dnfw.waverider.render.hermite is the
// contract, in its operation order.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). Loads at the same address as reader_mip.asm (PM sw 0x171a00); a build
// carries one or the other (dnfw.waverider.mip.INTERP).
//
// Everything but the loop is reader_mip.asm's: the entry, the level, the rows, ff. The
// loop, per sample:
//
// - hfr, half the sample fraction: the fraction converted one power of two lower (the
//   level record's word 6), exact, so the Hermite needs no float constant;
// - per row, four taps at phase - one, phase, phase + one, phase + 2 x one (one sample
//   of phase at this level), each its word read and its half picked as the linear
//   reader picks one, into F4..F7 (ym, y0, y1, y2);
// - the Hermite in adds and subtracts only (render.hermite's docstring), row a's result
//   kept in DM 0x2e3200 while row b's is computed;
// - between frames, the gain, osc 2's mix and the store, as before; the increment is
//   reloaded from the block each sample, since its register holds hfr.
//
// Registers in the loop: R3 = 16, R8 = -15, R9 phase, R10 hfr, R11 the word index's
// shift, R12 = -16, R13 one sample, R14 the fraction mask, R15 the half fraction's scale;
// ff in DM 0x2e3204 (R11 is the shift); R0-R2, R4-R7 scratch. An add whose first operand is R0-R7 is written with the
// operands the other way round (runner gap G5, as reader_m5.asm explains).
//
// Clobbers R0-R15, I0, I1, I2, I4, ASTAT, as reader_mip.asm. PLACEMENT IS FIXED at PM sw
// 0x171a00 (L1 block 1, byte 0x2e3400).

.SECTION/PM seg_pmco;

.GLOBAL wr_miph.;
wr_miph.:
      I4 = R4;                          // I4 -> parameter block
      R8 = DM(0, I4);                   // table (a byte address; bit 0: mip-mapped)
      R9 = DM(1, I4);                   // phase
      R10 = DM(2, I4);                  // inc
      R11 = DM(3, I4);                  // pos, Q16
      R12 = DM(4, I4);                  // N
      R0 = DM(5, I4);
      I2 = R0;                          // out

      // the level, k in R13 (free until its own load below; an add whose first operand is
      // R8-R15 keeps clear of the 16-bit parcels digikit's decoder misreads, runner gap G5):
      // 0 for a plain table
      R13 = R13 - R13;
      R1 = 1;
      R2 = R8 AND R1;
      IF EQ JUMP 0x171a5a;              // -> wr_miph_level. (plain: level 0)
      R8 = R8 - R1;                     // the table's address without the flag
      R2 = 1;
      R1 = 0x808081;                    // T[0] = ceil(2^31 / 255)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph_level.
      R13 = R13 + R2;
      R1 = 0x1020409;                   // T[1] = ceil(2^31 / 127)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph_level.
      R13 = R13 + R2;
      R1 = 0x2082083;                   // T[2] = ceil(2^31 / 63)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph_level.
      R13 = R13 + R2;
      R1 = 0x4210843;                   // T[3] = ceil(2^31 / 31)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph_level.
      R13 = R13 + R2;
      R1 = 0x8888889;                   // T[4] = ceil(2^31 / 15)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph_level.
      R13 = R13 + R2;
      R1 = 0x12492493;                  // T[5] = ceil(2^31 / 7)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph_level.
      R13 = R13 + R2;
      R1 = 0x2aaaaaab;                  // T[6] = ceil(2^31 / 3)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph_level.
      R13 = R13 + R2;                   // level 7, the last

.GLOBAL wr_miph_level.;
wr_miph_level.:
      R3 = LSHIFT R13 BY 5;             // k * 32 bytes: its record
      R4 = 0x2e3100;
      R3 = R4 + R3;
      I1 = R3;
      R4 = DM(0, I1);                   // the level's byte offset in the table
      R8 = R8 + R4;
      R5 = DM(1, I1);                   // log2 of a frame's bytes at this level

      // Frame rows: f0 = pos >> 16, f1 = min(f0 + 1, 15), each frame 2^R5 bytes
      R0 = LSHIFT R11 BY -16;
      R2 = 1;
      R1 = R0 + R2;
      R2 = 15;
      R1 = MIN(R1, R2);
      R0 = LSHIFT R0 BY R5;
      R1 = LSHIFT R1 BY R5;
      R0 = R8 + R0;
      DM(6, I4) = R0;                   // frame f0's row
      R1 = R8 + R1;
      DM(7, I4) = R1;                   // frame f1's row

      // Frame fraction ff = (pos & 0xffff) * 2^-16, exact in float32, kept in DM 0x2e3204:
      // R11 (F11) takes the word index's shift below
      R3 = 0xffff;
      R3 = R11 AND R3;
      R2 = -16;
      F3 = FLOAT R3 BY R2;
      DM(0x2e3204) = R3;

      R11 = DM(2, I1);                  // the word index's shift: w0 = phase >> (33 - b)
      R13 = DM(3, I1);                  // one sample of phase: w1 = (phase + it) >> (33 - b)
      R14 = DM(4, I1);                  // sample fraction mask
      R15 = DM(6, I1);                  // half the sample fraction's scale (Hermite)
      R3 = 16;                          // the loop's 16: shA = 16 - shB

      R8 = -15;                         // int16 -> float full scale, 2^-15
      R12 = PASS R12;
      IF EQ JUMP 0x171c85;              // -> wr_miph_done. (count 0: write nothing)
      R0 = PASS R12;                    // the count, for LCNTR
      R12 = -16;
      LCNTR = R0, DO wr_miph_last. UNTIL LCE;   // E2-active (the mix branch is in the body)

.GLOBAL wr_miph_loop.;
wr_miph_loop.:
      R0 = R9 AND R14;
      F10 = FLOAT R0 BY R15;            // hfr: half the sample fraction
      R2 = DM(6, I4);                   // frame f0's row
      // ym: sample k - 1
      R0 = R9 - R13;
      R1 = R0 AND R13;                  // the phase's bit for the sample's parity
      IF NE R1 = PASS R3;               // shB = 16 * parity
      R0 = LSHIFT R0 BY R11;            // its word index
      R0 = LSHIFT R0 BY 2;
      R0 = R2 + R0;                     // its word's address
      I0 = R0;
      R1 = R3 - R1;                     // shA = 16 - shB
      R0 = DM(0, I0);
      R0 = LSHIFT R0 BY R1;
      R0 = ASHIFT R0 BY R12;
      F4 = FLOAT R0 BY R8;
      // y0: sample k
      R0 = PASS R9;
      R1 = R0 AND R13;                  // the phase's bit for the sample's parity
      IF NE R1 = PASS R3;               // shB = 16 * parity
      R0 = LSHIFT R0 BY R11;            // its word index
      R0 = LSHIFT R0 BY 2;
      R0 = R2 + R0;                     // its word's address
      I0 = R0;
      R1 = R3 - R1;                     // shA = 16 - shB
      R0 = DM(0, I0);
      R0 = LSHIFT R0 BY R1;
      R0 = ASHIFT R0 BY R12;
      F5 = FLOAT R0 BY R8;
      // y1: sample k + 1
      R0 = R9 + R13;
      R1 = R0 AND R13;                  // the phase's bit for the sample's parity
      IF NE R1 = PASS R3;               // shB = 16 * parity
      R0 = LSHIFT R0 BY R11;            // its word index
      R0 = LSHIFT R0 BY 2;
      R0 = R2 + R0;                     // its word's address
      I0 = R0;
      R1 = R3 - R1;                     // shA = 16 - shB
      R0 = DM(0, I0);
      R0 = LSHIFT R0 BY R1;
      R0 = ASHIFT R0 BY R12;
      F6 = FLOAT R0 BY R8;
      // y2: sample k + 2
      R0 = R9 + R13;
      R0 = R13 + R0;
      R1 = R0 AND R13;                  // the phase's bit for the sample's parity
      IF NE R1 = PASS R3;               // shB = 16 * parity
      R0 = LSHIFT R0 BY R11;            // its word index
      R0 = LSHIFT R0 BY 2;
      R0 = R2 + R0;                     // its word's address
      I0 = R0;
      R1 = R3 - R1;                     // shA = 16 - shB
      R0 = DM(0, I0);
      R0 = LSHIFT R0 BY R1;
      R0 = ASHIFT R0 BY R12;
      F7 = FLOAT R0 BY R8;
      // the Hermite (render.hermite, in its order)
      F0 = F5 - F6;                     // t = y0 - y1
      F1 = F0 + F0;
      F0 = F1 + F0;                     // (t + t) + t
      F1 = F7 - F4;
      F0 = F0 + F1;                     // c3 = 3t + (y2 - ym)
      F1 = F6 - F4;                     // c1 = y1 - ym
      F2 = F4 - F5;                     // a = ym - y0
      F2 = F2 + F2;
      F6 = F6 - F5;                     // b = y1 - y0
      F6 = F6 + F6;
      F6 = F6 + F6;
      F2 = F2 + F6;                     // (a + a) + 4b
      F7 = F7 - F5;                     // d = y2 - y0
      F2 = F2 - F7;                     // c2
      F4 = F10 + F10;                   // fr = hfr + hfr, exact
      F0 = F0 * F4;
      F0 = F0 + F2;
      F0 = F0 * F4;
      F0 = F0 + F1;
      F0 = F0 * F10;
      F0 = F0 + F5;                     // the row's sample
      DM(0x2e3200) = R0;                // a, while b is computed
      R2 = DM(7, I4);                   // frame f1's row
      // ym: sample k - 1
      R0 = R9 - R13;
      R1 = R0 AND R13;                  // the phase's bit for the sample's parity
      IF NE R1 = PASS R3;               // shB = 16 * parity
      R0 = LSHIFT R0 BY R11;            // its word index
      R0 = LSHIFT R0 BY 2;
      R0 = R2 + R0;                     // its word's address
      I0 = R0;
      R1 = R3 - R1;                     // shA = 16 - shB
      R0 = DM(0, I0);
      R0 = LSHIFT R0 BY R1;
      R0 = ASHIFT R0 BY R12;
      F4 = FLOAT R0 BY R8;
      // y0: sample k
      R0 = PASS R9;
      R1 = R0 AND R13;                  // the phase's bit for the sample's parity
      IF NE R1 = PASS R3;               // shB = 16 * parity
      R0 = LSHIFT R0 BY R11;            // its word index
      R0 = LSHIFT R0 BY 2;
      R0 = R2 + R0;                     // its word's address
      I0 = R0;
      R1 = R3 - R1;                     // shA = 16 - shB
      R0 = DM(0, I0);
      R0 = LSHIFT R0 BY R1;
      R0 = ASHIFT R0 BY R12;
      F5 = FLOAT R0 BY R8;
      // y1: sample k + 1
      R0 = R9 + R13;
      R1 = R0 AND R13;                  // the phase's bit for the sample's parity
      IF NE R1 = PASS R3;               // shB = 16 * parity
      R0 = LSHIFT R0 BY R11;            // its word index
      R0 = LSHIFT R0 BY 2;
      R0 = R2 + R0;                     // its word's address
      I0 = R0;
      R1 = R3 - R1;                     // shA = 16 - shB
      R0 = DM(0, I0);
      R0 = LSHIFT R0 BY R1;
      R0 = ASHIFT R0 BY R12;
      F6 = FLOAT R0 BY R8;
      // y2: sample k + 2
      R0 = R9 + R13;
      R0 = R13 + R0;
      R1 = R0 AND R13;                  // the phase's bit for the sample's parity
      IF NE R1 = PASS R3;               // shB = 16 * parity
      R0 = LSHIFT R0 BY R11;            // its word index
      R0 = LSHIFT R0 BY 2;
      R0 = R2 + R0;                     // its word's address
      I0 = R0;
      R1 = R3 - R1;                     // shA = 16 - shB
      R0 = DM(0, I0);
      R0 = LSHIFT R0 BY R1;
      R0 = ASHIFT R0 BY R12;
      F7 = FLOAT R0 BY R8;
      // the Hermite (render.hermite, in its order)
      F0 = F5 - F6;                     // t = y0 - y1
      F1 = F0 + F0;
      F0 = F1 + F0;                     // (t + t) + t
      F1 = F7 - F4;
      F0 = F0 + F1;                     // c3 = 3t + (y2 - ym)
      F1 = F6 - F4;                     // c1 = y1 - ym
      F2 = F4 - F5;                     // a = ym - y0
      F2 = F2 + F2;
      F6 = F6 - F5;                     // b = y1 - y0
      F6 = F6 + F6;
      F6 = F6 + F6;
      F2 = F2 + F6;                     // (a + a) + 4b
      F7 = F7 - F5;                     // d = y2 - y0
      F2 = F2 - F7;                     // c2
      F4 = F10 + F10;                   // fr = hfr + hfr, exact
      F0 = F0 * F4;
      F0 = F0 + F2;
      F0 = F0 * F4;
      F0 = F0 + F1;
      F0 = F0 * F10;
      F0 = F0 + F5;                     // the row's sample
.NOCOMPRESS;                            // a hardware loop's last 11 instructions are 48-bit (PRM 4-42)
      R1 = DM(0x2e3200);                // a
      F0 = F0 - F1;
      R2 = DM(0x2e3204);                // ff (R11 holds the word index's shift here, so F11 can't)
      F0 = F2 * F0;
      F0 = F1 + F0;                     // y = a + ff * (b - a)
      R1 = DM(0x2de6c0);                // the gain, LEV / 100
      F0 = F1 * F0;                     // y * gain
      // osc 2 adds into the buffer osc 1 wrote (DM 0x2de6c4 = 1)
      R1 = DM(0x2de6c4);
      R1 = PASS R1;
      IF EQ JUMP 0x171c79;              // -> wr_miph_store.
      R2 = DM(0, I2);                   // what osc 1 wrote
      F0 = F0 + F2;
.GLOBAL wr_miph_store.;
wr_miph_store.:
      DM(I2, M6) = F0;
      R0 = DM(2, I4);                   // inc
.GLOBAL wr_miph_last.;
wr_miph_last.:
      R9 = R9 + R0;                     // phase += inc, mod 2^32 (the loop's last instruction)
.COMPRESS;
      R0 = R0 - R0;
      DM(4, I4) = R0;                   // 0: the count word as the software loop left it

.GLOBAL wr_miph_done.;
wr_miph_done.:
      I12 = DM(M7, I6);
      DM(1, I4) = R9;                   // phase, for the next block
      JUMP (M14, I12) (DB);
      NOP;
      RFRAME;
.wr_miph..end:
      .type wr_miph.,STT_FUNC;
