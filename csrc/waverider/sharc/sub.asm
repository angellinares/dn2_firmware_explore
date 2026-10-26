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
// else osc 1's (0x2ddf00 + 32t). Then it goes on to the noise (noise.asm, wr_noise),
// which goes on to wr_t5v_next.
//
// The shapes (WAVE 0 SIN, 1 TRI, 2 SQR, 3 PLS), as live.sub_value computes them, in
// float32 and in this order: h = (phase << 1 >> 8) x 2^-25, x mod 0.5, exact;
//   SIN  16 h (0.5 - h), negated in the second half (the phase's top bit)
//   TRI  4 a - 1, a = 0.5 - h in the first half, h in the second
//   SQR  +1, then -1
//   PLS  +1 for the first quarter, then f32(-1/3): a 25 % pulse with no DC
//
// DM (byte addresses, the free tail of L1 block 1 after DCLK's state):
//   0x2e24b0  16 phases, a u32 per voice (zeros at boot)
//   0x2e24f0  1 when osc 2 ran this block
//   0x2e24f4  this voice's phase address, across the loop
// (until the polyBLEP, 2026-10-26, at 0x2e2400: the code needed the room)
//
// No DAG1 M0-M3 in a memory access, addresses as byte arithmetic then `In = Rn`, FLOAT
// only with BY, every add with R8-R15 first. The shapes are DO loops, as reader_miph2.asm's
// (until 2026-10-21 software loops, as reader_m9.asm's). Clobbers R0-R15, I1, I2; I3 and I5 (the loop's
// pointers) are not touched.
//
// PLACEMENT IS FIXED at PM sw 0x171000 (DM byte 0x2e2000): the absolute jumps below are
// written for it, and for machine9_live.asm's, by scripts/sharc_resolve_jumps.py.

.SECTION/PM seg_pmco;

.GLOBAL wr_sub_ran.;
wr_sub_ran.:
      R0 = 1;
      DM(0x2e24f0) = R0;
      JUMP 0x17100c;                    // -> wr_sub_go.
.GLOBAL wr_sub_skip.;
wr_sub_skip.:
      R0 = R0 - R0;
      DM(0x2e24f0) = R0;

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
      IF EQ JUMP 0x171300;              // -> wr_noise. (SUB 0: no sub; noise.asm)

      // the gain, SUB / 100, as machine9_live.asm forms LEV's
      R12 = R12 - R12;
      F6 = FLOAT R6 BY R12;
      R12 = DM(0x2de6c8);               // f32(10^(dB/20) / 25600): the trim's factor for this voice (trim.asm)
      F6 = F6 * F12;
      // WAVE >> 8, at most 3 (PLS)
      R13 = LSHIFT R13 BY -8;
      R12 = 3;
      R13 = MIN(R13, R12);
      // the step's shift: -(1 + OCT >> 8), OCT at most 2 (-3 oct, live.SUB_OCTAVES)
      R7 = LSHIFT R7 BY -8;
      R12 = 2;
      R7 = MIN(R7, R12);
      R12 = -1;
      R7 = R12 - R7;

      // the followed oscillator's reader block: osc 2's when SRC and osc 2 ran
      R2 = LSHIFT R9 BY 5;              // 32 bytes a reader block
      R14 = LSHIFT R14 BY -8;
      R14 = PASS R14;
      IF EQ JUMP 0x171083;              // -> wr_sub_osc1.
      R0 = DM(0x2e24f0);
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

      // this voice's phase, 0x2e24b0 + 4t
      R2 = LSHIFT R9 BY 2;
      R12 = 0x2e24b0;
      R2 = R12 + R2;
      DM(0x2e24f4) = R2;
      I1 = R2;
      R11 = DM(0, I1);

      R2 = DM(0x2dde88);                // the track buffer, both oscillators' sum
      I2 = R2;
      R8 = DM(0x2dde24);                // the dispatch's R9: the block size
      R8 = PASS R8;
      IF EQ JUMP 0x1711f2;              // -> wr_sub_done. (count 0: nothing)
      R15 = -25;                        // h's scale, 2^-25

      // opt2 O6 (A2): WAVE can't change within a block, so it is tested once here and each
      // shape runs its own loop (until opt2 every sample walked the compare chain). SQR and
      // PLS don't use h, so their loops skip it. The arithmetic per shape is unchanged.
      R12 = 1;
      R13 = PASS R13;
      IF EQ JUMP 0x17118b;              // -> wr_sub_sin.
      COMP(R13, R12);
      IF EQ JUMP 0x1711bf;              // -> wr_sub_tri.
      JUMP 0x1710b8;                    // -> wr_sub_edge. (SQR and PLS)

// Load plan #3 (2026-10-21): each shape is a hardware loop (LCNTR = R8, the count), with its
// constants in registers and the half test as a conditional compute, so a sample takes no branch.
// R9 takes what the oscillators wrote early, so its load is not used by the next instruction.

// SQR and PLS (2026-10-26, owner: the polyBLEP). Both jump between two levels: SQR +1 then -1
// at a half, PLS +1 then f32(-1/3) at a quarter (the edge E). n = hi while phase < E (unsigned),
// else lo. A block with an edge within a step of a sample (live.sub_near_edge's test) adds the
// polyBLEP: c = max(1 - |x|, 0)^2 with x's sign, x = (phase - edge) / step as int32 x f32(1/step),
// for the rise at 0 (c0) and the fall at E (c1), and y = n + h (c1 - c0), h half the jump (SQR 1,
// PLS 2/3); then gain x y. Any other block plays n as before, bit for bit: away from the edges
// the polyBLEP is a signed zero. 1/step is live.sub_recip's: a seed from the bits, three Newton steps.
.GLOBAL wr_sub_edge.;
wr_sub_edge.:
      R12 = R12 - R12;                  // 0: FLOAT's scale
      R3 = 0x3f800000;                  // hi: +1
      R4 = -0x40800000;                 // lo: -1.0, 0xbf800000
      R5 = 0x80000000;                  // E: a half
      R15 = 0x3f800000;                 // h: 1
      R13 = PASS R13;
      R0 = 2;
      COMP(R13, R0);
      IF EQ JUMP 0x1710d5;              // -> wr_sub_edge_test.
      R4 = -0x41555555;                 // PLS: lo f32(-1/3), 0xbeaaaaab (written signed, as selmap reads it)
      R5 = 0x40000000;                  //      E: a quarter
      R15 = 0x3f2aaaab;                 //      h: f32(2/3)
.GLOBAL wr_sub_edge_test.;
wr_sub_edge_test.:
      // is an edge near? a = phase - step; edge E is when 0 < E - a < (count + 1) step (int32)
      R10 = PASS R10;
      IF EQ JUMP 0x17116c;              // -> wr_sub_naive. (step 0: no edges move)
      R0 = 0x03e00000;                  // live.SUB_BLEP_ALWAYS
      COMPU(R10, R0);
      IF GE JUMP 0x1710fa;              // -> wr_sub_blep. (a big step: every block)
      R2 = R8 + 1;
      R2 = R10 * R2 (SSI);              // (count + 1) step, under 2^31 here
      R0 = R11 - R10;                   // a
      R1 = R12 - R0;                    // the rise's E - a, E = 0
      R1 = PASS R1;                     // (R6 is the gain: test R1 itself)
      IF LE JUMP 0x1710f0;              // -> wr_sub_edge_fall.
      COMP(R1, R2);
      IF LT JUMP 0x1710fa;              // -> wr_sub_blep.
.GLOBAL wr_sub_edge_fall.;
wr_sub_edge_fall.:
      R1 = R5 - R0;                     // the fall's E - a
      R1 = PASS R1;                     // (R6 is the gain: test R1 itself)
      IF LE JUMP 0x17116c;              // -> wr_sub_naive.
      COMP(R1, R2);
      IF GE JUMP 0x17116c;              // -> wr_sub_naive.

.GLOBAL wr_sub_blep.;
wr_sub_blep.:
      // 1/step: the bits' seed, then y (2 - x y) three times (live.sub_recip)
      F7 = FLOAT R10 BY R12;            // x = step
      R1 = 0x7ef311c7;
      R1 = R1 - R7;                     // the seed
      R0 = 0x40000000;                  // 2.0
      F2 = F7 * F1;
      F2 = F0 - F2;
      F1 = F1 * F2;
      F2 = F7 * F1;
      F2 = F0 - F2;
      F1 = F1 * F2;
      F2 = F7 * F1;
      F2 = F0 - F2;
      F1 = F1 * F2;
      F7 = PASS F1;                     // 1/step
      R13 = 0x3f800000;                 // 1.0
      R14 = R14 - R14;                  // +0.0
      LCNTR = R8, DO wr_sub_blep_last. UNTIL LCE;
.NOCOMPRESS;                            // a hardware loop's last 11 instructions are 48-bit (PRM 4-42)
      R9 = DM(0, I2);                   // what the oscillators wrote
      F0 = FLOAT R11 BY R12;            // the rise's distance, phase - 0
      R1 = R11 - R5;                    // the fall's, phase - E
      F0 = F0 * F7;                     // x0
      F1 = FLOAT R1 BY R12;
      F1 = F1 * F7;                     // x1
      F2 = ABS F0;
      F2 = F13 - F2;
      F2 = MAX(F2, F14);
      F2 = F2 * F2;
      F2 = F2 COPYSIGN F0;              // c0
      F8 = ABS F1;
      F8 = F13 - F8;
      F8 = MAX(F8, F14);
      F8 = F8 * F8;
      F8 = F8 COPYSIGN F1;              // c1
      F8 = F8 - F2;                     // c1 - c0
      F8 = F15 * F8;                    // h (c1 - c0)
      R0 = PASS R4;                     // n: lo
      COMPU(R11, R5);
      IF LT R0 = PASS R3;               //    hi before the edge
      F0 = F0 + F8;                     // y = n + h (c1 - c0)
      F0 = F6 * F0;                     // gain x y
      F0 = F9 + F0;
      DM(I2, M6) = F0;
.GLOBAL wr_sub_blep_last.;
wr_sub_blep_last.:
      R11 = R11 + R10;                  // phase += step, mod 2^32
.COMPRESS;
      JUMP 0x1711f2;                    // -> wr_sub_done.

.GLOBAL wr_sub_naive.;
wr_sub_naive.:
      F3 = F6 * F3;                     // gain x hi
      F4 = F6 * F4;                     // gain x lo
      LCNTR = R8, DO wr_sub_naive_last. UNTIL LCE;
.NOCOMPRESS;
      R9 = DM(0, I2);                   // what the oscillators wrote
      R1 = PASS R4;
      COMPU(R11, R5);
      IF LT R1 = PASS R3;               // hi before the edge
      F1 = F9 + F1;
      DM(I2, M6) = F1;
.GLOBAL wr_sub_naive_last.;
wr_sub_naive_last.:
      R11 = R11 + R10;                  // phase += step, mod 2^32
.COMPRESS;
      JUMP 0x1711f2;                    // -> wr_sub_done.

.GLOBAL wr_sub_sin.;
wr_sub_sin.:
      R3 = 0x3f000000;                  // 0.5
      R4 = 0x41800000;                  // 16.0
      R5 = R5 - R5;                     // +0.0
      LCNTR = R8, DO wr_sub_sin_last. UNTIL LCE;
.NOCOMPRESS;
      R0 = LSHIFT R11 BY 1;
      R0 = LSHIFT R0 BY -8;
      F0 = FLOAT R0 BY R15;             // h = x mod 0.5, exact
      F1 = F3 - F0;
      F1 = F0 * F1;
      R9 = DM(0, I2);                   // what the oscillators wrote
      F1 = F1 * F4;
      R2 = PASS R11;
      IF LT F1 = F5 - F1;               // the second half: negated, as +0.0 - F1
      F1 = F6 * F1;                     // gain x shape
      F1 = F9 + F1;
      DM(I2, M6) = F1;
.GLOBAL wr_sub_sin_last.;
wr_sub_sin_last.:
      R11 = R11 + R10;                  // phase += step, mod 2^32
.COMPRESS;
      JUMP 0x1711f2;                    // -> wr_sub_done.

.GLOBAL wr_sub_tri.;
wr_sub_tri.:
      R3 = 0x3f000000;                  // 0.5
      R4 = 0x40800000;                  // 4.0
      R5 = 0x3f800000;                  // 1.0
      LCNTR = R8, DO wr_sub_tri_last. UNTIL LCE;
.NOCOMPRESS;
      R0 = LSHIFT R11 BY 1;
      R0 = LSHIFT R0 BY -8;
      F0 = FLOAT R0 BY R15;             // h = x mod 0.5, exact
      R9 = DM(0, I2);                   // what the oscillators wrote (a data move after the F0 compute: anomaly 20000072)
      R2 = PASS R11;
      IF GE F0 = F3 - F0;               // the first half: a = 0.5 - h; the second: a = h
      F1 = F0 * F4;
      F1 = F1 - F5;
      F1 = F6 * F1;                     // gain x shape
      F1 = F9 + F1;
      DM(I2, M6) = F1;
.GLOBAL wr_sub_tri_last.;
wr_sub_tri_last.:
      R11 = R11 + R10;                  // phase += step, mod 2^32
.COMPRESS;
      JUMP 0x1711f2;                    // -> wr_sub_done.

.GLOBAL wr_sub_done.;
wr_sub_done.:
      R2 = DM(0x2e24f4);
      I1 = R2;
      DM(0, I1) = R11;                  // the phase, for the next block
      JUMP 0x171300;                    // -> wr_noise. (noise.asm)
.wr_sub_ran..end:
      .type wr_sub_ran.,STT_FUNC;
