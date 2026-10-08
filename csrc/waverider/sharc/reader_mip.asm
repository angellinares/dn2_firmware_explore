// reader_mip.asm -- Waverider's wavetable reader with mip-mapped tables (the SHARC
// study's B1; dnfw.waverider.mip is the contract, dnfw.waverider.render the reader).
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). reader_m9.asm's entry jumps here, so every caller (machine9_live through
// dclk.asm, and dclk.asm's own two calls) reaches it with the same block in R4 and the
// same return: the contract is reader_m9.asm's, (table, phase, inc, pos, count, out,
// f0 row, f1 row), plus:
//
// - **A mip-mapped table** has bit 0 of its address set (the directory and the pool's
//   entries carry it). Its eight levels follow one another: level k is 16 frames of
//   points(k) int16 (512, 512, 512, 256, 128, 64, 32, 16), at the byte offset the
//   level record holds. A table without the bit plays level 0: today's reader, bit
//   for bit.
// - **The level** is chosen once a block from the increment: the lowest k with
//   inc < T[k] (T[k] = ceil(2^31 / top harmonic of k); T[7] = 0xffffffff), as
//   dnfw.waverider.mip.level_for.
// - **Each level's constants** come from its record (DM 0x2e3100 + 32k): the byte
//   offset, the frame row's shift (log2 of a frame's bytes), the word index's shift
//   (-(33 - b) for 2^b points), one sample of phase (2^(32 - b)), the fraction mask
//   (2^(32 - b) - 1) and its scale (-(32 - b)). Level 0's are today's literals
//   (0, 10, -24, 0x800000, 0x7fffff, -23).
// - **The odd/even sample select** is `R3 = R9 AND R13` (the phase's bit for k & 1)
//   then `IF NE R3 = PASS R2` (16), in place of opt2's shift and AND: the same two
//   instructions, without a per-level shift amount.
//
// The rest is opt2's reader_m9.asm unchanged: the hardware loop with its 48-bit tail,
// the paired loads, the gain at DM 0x2de6c0, osc 2's mix at 0x2de6c4.
//
// Clobbers R0-R15, I0, I1, I2, I4, ASTAT, as reader_m9.asm. PLACEMENT IS FIXED at PM sw
// 0x171a00 (L1 block 1, byte 0x2e3400): the absolute jumps are written for it.

.SECTION/PM seg_pmco;

.GLOBAL wr_mip.;
wr_mip.:
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
      IF EQ JUMP 0x171a5a;              // -> wr_mip_level. (plain: level 0)
      R8 = R8 - R1;                     // the table's address without the flag
      R2 = 1;
      R1 = 0x808081;                    // T[0] = ceil(2^31 / 255)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_mip_level.
      R13 = R13 + R2;
      R1 = 0x1020409;                   // T[1] = ceil(2^31 / 127)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_mip_level.
      R13 = R13 + R2;
      R1 = 0x2082083;                   // T[2] = ceil(2^31 / 63)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_mip_level.
      R13 = R13 + R2;
      R1 = 0x4210843;                   // T[3] = ceil(2^31 / 31)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_mip_level.
      R13 = R13 + R2;
      R1 = 0x8888889;                   // T[4] = ceil(2^31 / 15)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_mip_level.
      R13 = R13 + R2;
      R1 = 0x12492493;                  // T[5] = ceil(2^31 / 7)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_mip_level.
      R13 = R13 + R2;
      R1 = 0x2aaaaaab;                  // T[6] = ceil(2^31 / 3)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_mip_level.
      R13 = R13 + R2;                   // level 7, the last

.GLOBAL wr_mip_level.;
wr_mip_level.:
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
      R15 = DM(5, I1);                  // sample fraction scale
      R8 = -15;                         // int16 -> float full scale, 2^-15
      R12 = PASS R12;
      IF EQ JUMP 0x171b39;              // -> wr_mip_done. (count 0: write nothing)
      R0 = PASS R12;                    // the count, for LCNTR
      R12 = -16;
      LCNTR = R0, DO wr_mip_last. UNTIL LCE;   // E2-active (the mix branch is in the body)

.GLOBAL wr_mip_loop.;
wr_mip_loop.:
      R0 = LSHIFT R9 BY R11;            // w0 = k >> 1
      R0 = LSHIFT R0 BY 2;              // its byte offset in a row
      R1 = R9 + R13, R2 = DM(6, I4);    // with frame f0's row
      R1 = LSHIFT R1 BY R11;            // w1 = (k + 1) >> 1, mod the level's words
      R1 = LSHIFT R1 BY 2;
      R4 = R2 + R0;                     // frame f0, word w0's address
      R5 = R2 + R1, R2 = DM(7, I4);     // frame f0, word w1's; with frame f1's row (the add reads the old R2)
      I0 = R4;
      I1 = R5;
      R6 = R2 + R0;                     // frame f1, word w0's address
      R7 = R2 + R1;                     // frame f1, word w1's
      R2 = 16;
      R3 = R9 AND R13;                  // the phase's bit for k & 1
      IF NE R3 = PASS R2;               // shB = 16 * (k & 1)
      R2 = R2 - R3, R4 = DM(0, I0);     // shA = 16 - shB; with frame f0, word w0
      R4 = LSHIFT R4 BY R2, R5 = DM(0, I1);   // with frame f0, word w1
      I0 = R6;
      I1 = R7;
      R4 = ASHIFT R4 BY R12;            // s00 = sample k
      R5 = LSHIFT R5 BY R3;
      R5 = ASHIFT R5 BY R12;            // s01 = sample k + 1
      F4 = FLOAT R4 BY R8, R6 = DM(0, I0);    // with frame f1, word w0
      F5 = FLOAT R5 BY R8, R7 = DM(0, I1);    // with frame f1, word w1
      R6 = LSHIFT R6 BY R2;
      R6 = ASHIFT R6 BY R12;            // s10
      R7 = LSHIFT R7 BY R3;
      R7 = ASHIFT R7 BY R12;            // s11
      F6 = FLOAT R6 BY R8;
      F7 = FLOAT R7 BY R8;
      R0 = R9 AND R14;
      F0 = FLOAT R0 BY R15;             // sample fraction (exact at level 0; rounded above)
      F5 = F5 - F4;
      F5 = F0 * F5;
      F4 = F4 + F5;                     // a = s00 + fr * (s01 - s00)
      F7 = F7 - F6;
      F7 = F0 * F7;
      F6 = F6 + F7;                     // b = s10 + fr * (s11 - s10)
.NOCOMPRESS;                            // a hardware loop's last 11 instructions are 48-bit (PRM 4-42)
      F6 = F6 - F4;
      R2 = DM(0x2e3204);                // ff (R11 holds the word index's shift here, so F11 can't)
      F6 = F2 * F6;
      F4 = F4 + F6;                     // y = a + ff * (b - a)
      R0 = DM(0x2de6c0);                // the gain, LEV / 100
      F4 = F0 * F4;                     // y * gain
      // osc 2 adds into the buffer osc 1 wrote (DM 0x2de6c4 = 1)
      R0 = DM(0x2de6c4);
      R0 = PASS R0;
      IF EQ JUMP 0x171b30;              // -> wr_mip_store.
      R1 = DM(0, I2);                   // what osc 1 wrote
      F4 = F4 + F1;
.GLOBAL wr_mip_store.;
wr_mip_store.:
      DM(I2, M6) = F4;
.GLOBAL wr_mip_last.;
wr_mip_last.:
      R9 = R9 + R10;                    // phase += inc, mod 2^32 (the loop's last instruction)
.COMPRESS;
      R0 = R0 - R0;
      DM(4, I4) = R0;                   // 0: the count word as the software loop left it

.GLOBAL wr_mip_done.;
wr_mip_done.:
      I12 = DM(M7, I6);
      DM(1, I4) = R9;                   // phase, for the next block
      JUMP (M14, I12) (DB);
      NOP;
      RFRAME;
.wr_mip..end:
      .type wr_mip.,STT_FUNC;
