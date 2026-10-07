// sub.asm -- Waverider page 3: the sub-oscillator (docs/waverider-pages34.md).
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). Run offline in digikit's SHARC executor inside the DN2 1.11 image
// (scripts/sharc_waverider_sub.py), checked bit for bit against
// dnfw.waverider.live.render_sub; it has never run on a DSP.
//
// Entered from machine9_live.asm once a type-5 track's oscillators are done, instead of
// its jump to wr_t5v_next: at wr_sub_ran when osc 2 ran this block, at wr_sub_skip when
// osc 2 was skipped (LEV2 0). It reads the track's SUB, OCT, WAVE and SRC (params 50..53,
// FM Tone's records, which a WaveTone-type sound doesn't have) from the frame copy at
// 0x25c48c, offsets 268, 270, 272, 274 + 146t. With SUB 0 it does nothing. Otherwise it
// adds SUB/100 x shape(phase) into the track buffer the oscillators wrote, a sample at a
// time, and steps its own phase by the followed oscillator's increment >> (1 + OCT):
// osc 2's (its reader block, 0x2de800 + 32t, word 2) when SRC is 1 and osc 2 ran,
// else osc 1's (0x2ddf00 + 32t). Then it goes on to wr_t5v_next.
//
// The shapes (WAVE 0 SIN, 1 TRI, 2 SQR, 3 PLS), as live.sub_value computes them, in
// float32 and in this order: h = (phase << 1 >> 8) x 2^-25, x mod 0.5, exact;
//   SIN  16 h (0.5 - h), negated in the second half (the phase's top bit)
//   TRI  4 a - 1, a = 0.5 - h in the first half, h in the second
//   SQR  +1, then -1
//   PLS  +1 for the first quarter, then f32(-1/3): a 25 % pulse with no DC
//
// DM (byte addresses, the free tail of L1 block 1 after DCLK's state):
//   0x2e2400  16 phases, a u32 per voice (zeros at boot)
//   0x2e2440  1 when osc 2 ran this block
//   0x2e2444  this voice's phase address, across the loop
//   0x2e2448  samples left (the loop counts in software, as reader_m9.asm does)
//
// Only forms the firmware itself uses, as reader_m9.asm says: no DO loop, no DAG1
// M0-M3 in a memory access, addresses as byte arithmetic then `In = Rn`, FLOAT only
// with BY, every add with R8-R15 first. Clobbers R0-R15, I1, I2; I3 and I5 (the loop's
// pointers) are not touched.
//
// PLACEMENT IS FIXED at PM sw 0x171000 (DM byte 0x2e2000): the absolute jumps below are
// written for it, and for machine9_live.asm's, by scripts/sharc_resolve_jumps.py.

.SECTION/PM seg_pmco;

.GLOBAL wr_sub_ran.;
wr_sub_ran.:
      R0 = 1;
      DM(0x2e2440) = R0;
      JUMP 0x17100c;                    // -> wr_sub_go.
.GLOBAL wr_sub_skip.;
wr_sub_skip.:
      R0 = R0 - R0;
      DM(0x2e2440) = R0;

.GLOBAL wr_sub_go.;
wr_sub_go.:
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R10 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R9 BY 1;
      R10 = R10 + R11;                  // 146t
      R12 = 0x25c598;                   // 0x25c48c + 268: SUB (param 50)
      R10 = R12 + R10;                  // &SUB, 2-byte aligned
      R1 = 2;
      R1 = R10 AND R1;                  // 2 when t is odd
      R4 = -4;
      R2 = R10 AND R4;
      I1 = R2;
      R3 = DM(0, I1);
      R4 = DM(1, I1);
      R5 = DM(2, I1);
      R0 = -16;
      R1 = PASS R1;
      IF NE JUMP 0x171042;              // -> wr_sub_odd.
      R6 = PASS R3;                     // t even: SUB low half of word 0, OCT high
      R7 = LSHIFT R3 BY R0;
      R13 = PASS R4;                    //         WAVE low half of word 1, SRC high
      R14 = LSHIFT R4 BY R0;
      JUMP 0x171048;                    // -> wr_sub_halves.
.GLOBAL wr_sub_odd.;
wr_sub_odd.:
      R6 = LSHIFT R3 BY R0;             // t odd:  SUB high half of word 0
      R7 = PASS R4;                     //         OCT low half of word 1, WAVE high
      R13 = LSHIFT R4 BY R0;
      R14 = PASS R5;                    //         SRC low half of word 2
.GLOBAL wr_sub_halves.;
wr_sub_halves.:
      R12 = 0xffff;
      R6 = R6 AND R12;                  // SUB, 0..0x7f00
      R7 = R7 AND R12;                  // OCT
      R13 = R13 AND R12;                // WAVE
      R14 = R14 AND R12;                // SRC
      R6 = PASS R6;
      IF EQ JUMP 0x16eea7;              // -> wr_t5v_next. (SUB 0: nothing)

      // the gain, SUB / 100, as machine9_live.asm forms LEV's
      R12 = R12 - R12;
      F6 = FLOAT R6 BY R12;
      R12 = 0x3823d70a;                 // f32(1 / 25600)
      F6 = F6 * F12;
      // WAVE >> 8, at most 3 (PLS)
      R13 = LSHIFT R13 BY -8;
      R12 = 3;
      R13 = MIN(R13, R12);
      // the step's shift: -(1 + OCT >> 8), OCT at most 1
      R7 = LSHIFT R7 BY -8;
      R12 = 1;
      R7 = MIN(R7, R12);
      R12 = -1;
      R7 = R12 - R7;

      // the followed oscillator's reader block: osc 2's when SRC and osc 2 ran
      R2 = LSHIFT R9 BY 5;              // 32 bytes a reader block
      R14 = LSHIFT R14 BY -8;
      R14 = PASS R14;
      IF EQ JUMP 0x171083;              // -> wr_sub_osc1.
      R0 = DM(0x2e2440);
      R0 = PASS R0;
      IF EQ JUMP 0x171083;              // -> wr_sub_osc1.
      R12 = 0x2de800;
      JUMP 0x171086;                    // -> wr_sub_followed.
.GLOBAL wr_sub_osc1.;
wr_sub_osc1.:
      R12 = 0x2ddf00;
.GLOBAL wr_sub_followed.;
wr_sub_followed.:
      R2 = R12 + R2;
      I1 = R2;
      R10 = DM(2, I1);                  // its inc, this block's
      R10 = LSHIFT R10 BY R7;           // the sub's step: inc >> (1 + OCT)

      // this voice's phase, 0x2e2400 + 4t
      R2 = LSHIFT R9 BY 2;
      R12 = 0x2e2400;
      R2 = R12 + R2;
      DM(0x2e2444) = R2;
      I1 = R2;
      R11 = DM(0, I1);

      R2 = DM(0x2dde88);                // the track buffer, both oscillators' sum
      I2 = R2;
      R8 = DM(0x2dde24);                // the dispatch's R9: the block size
      DM(0x2e2448) = R8;
      R8 = PASS R8;
      IF EQ JUMP 0x17111f;              // -> wr_sub_done. (count 0: nothing)
      R15 = -25;                        // h's scale, 2^-25

.GLOBAL wr_sub_loop.;
wr_sub_loop.:
      R0 = LSHIFT R11 BY 1;
      R0 = LSHIFT R0 BY -8;
      F0 = FLOAT R0 BY R15;             // h = x mod 0.5, exact
      R13 = PASS R13;
      IF EQ JUMP 0x1710d7;              // -> wr_sub_sin.
      R12 = 1;
      COMP(R13, R12);
      IF EQ JUMP 0x1710ec;              // -> wr_sub_tri.
      R12 = 2;
      COMP(R13, R12);
      IF EQ JUMP 0x171101;              // -> wr_sub_sqr.
      R1 = 0x3f800000;                  // PLS: +1 for the first quarter
      R2 = 0x40000000;
      COMPU(R11, R2);
      IF LT JUMP 0x17110b;              // -> wr_sub_have.
      R1 = -0x41555555;                 // f32(-1/3), 0xbeaaaaab (written signed, as selmap reads it)
      JUMP 0x17110b;                    // -> wr_sub_have.
.GLOBAL wr_sub_sin.;
wr_sub_sin.:
      R12 = 0x3f000000;                 // 0.5
      F1 = F12 - F0;
      F1 = F0 * F1;
      R12 = 0x41800000;                 // 16.0
      F1 = F1 * F12;
      R2 = PASS R11;
      IF GE JUMP 0x17110b;              // -> wr_sub_have. (the first half)
      R12 = R12 - R12;                  // +0.0
      F1 = F12 - F1;
      JUMP 0x17110b;                    // -> wr_sub_have.
.GLOBAL wr_sub_tri.;
wr_sub_tri.:
      R2 = PASS R11;
      IF LT JUMP 0x1710f5;              // -> wr_sub_tri_a. (the second half: a = h)
      R12 = 0x3f000000;                 // 0.5
      F0 = F12 - F0;                    // the first half: a = 0.5 - h
.GLOBAL wr_sub_tri_a.;
wr_sub_tri_a.:
      R12 = 0x40800000;                 // 4.0
      F1 = F0 * F12;
      R12 = 0x3f800000;                 // 1.0
      F1 = F1 - F12;
      JUMP 0x17110b;                    // -> wr_sub_have.
.GLOBAL wr_sub_sqr.;
wr_sub_sqr.:
      R1 = 0x3f800000;                  // +1
      R2 = PASS R11;
      IF GE JUMP 0x17110b;              // -> wr_sub_have.
      R1 = -0x40800000;                 // -1.0, 0xbf800000
.GLOBAL wr_sub_have.;
wr_sub_have.:
      F1 = F6 * F1;                     // gain x shape
      R2 = DM(0, I2);                   // what the oscillators wrote
      F1 = F2 + F1;
      DM(I2, M6) = F1;
      R11 = R11 + R10;                  // phase += step, mod 2^32
      R0 = DM(0x2e2448);
      R1 = 1;
      R0 = R0 - R1;
      DM(0x2e2448) = R0;                // samples left
      IF NE JUMP 0x1710ae;              // -> wr_sub_loop.

.GLOBAL wr_sub_done.;
wr_sub_done.:
      R2 = DM(0x2e2444);
      I1 = R2;
      DM(0, I1) = R11;                  // the phase, for the next block
      JUMP 0x16eea7;                    // -> wr_t5v_next.
.wr_sub_ran..end:
      .type wr_sub_ran.,STT_FUNC;
