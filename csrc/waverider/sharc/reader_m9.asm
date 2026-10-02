// reader_m9.asm -- Waverider Milestone 9: reader_m5.asm with a gain and a mix. Each
// sample is multiplied by the float at DM 0x2de6c0, which machine9_live.asm writes
// before every call: LEV / 100, so the default level 100 is exactly 1.0 and the output
// is bit-identical to reader_m5.asm's there (M9a). When DM 0x2de6c4 is non-zero (osc 2,
// M9b) the sample is added to what the buffer holds instead of replacing it.
//
// What follows is reader_m5.asm's own description, unchanged:
//
// reader_m5.asm -- Waverider Milestone 5: reader.asm (Milestone 1) restricted to the
// instruction forms the shipping firmware itself uses, for the first flash.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). Run offline in digikit's SHARC executor and checked bit for bit against
// dnfw.waverider.render (float32); it has never run on a DSP.
//
// Same contract as reader.asm -- wr_render(R4 = params), 16 frames x 512 int16, linear
// between samples and between frames; the block is (table, phase, inc, pos, count,
// out) -- and the same arithmetic, in the same order, so it is bit-identical. What
// changed, and why (docs/waverider-m5-dsp.md, "Instruction forms"):
//
// 1. **No DAG1 M0-M3 in a memory access.** Of the firmware's 1,266 16-bit Type 3c
//    accesses, every one names M4-M7; M0-M3 appear in no Type 3a/3c access at all.
//    For M0-M3 selas and selache's own disassembler disagree -- selas's
//    `R3 = DM(I0, M0)` (0x9013) reads to selmap as a load into DADDR, and
//    `R4 = DM(M2, I0)` as `DM(M6, I0)` -- so which one the silicon follows is not
//    known, and reader.asm's frame-row dummy reads and inner-loop taps used them.
//    Here the rows are byte arithmetic on the table pointer (a frame is 1,024 bytes),
//    the firmware's own idiom (`r1 = r4 + r1` at 0x1c9259), and the taps use M4.
// 2. **No pre-modify read and no hardware DO loop (Milestone 5c).** M5's inner loop
//    was `LCNTR = R2, DO ... UNTIL LCE` with pre-modify `DM(M4, I0)` taps. selas
//    encodes that DO with the loop-`mode` bit (bit 23) clear. The firmware sets it
//    on every short straight-line loop (e.g. sw 0x1c9492, `0c0d80000c00`) and
//    clears it on loops with branches in the body. digikit's executor ignores the
//    bit, so the runner cannot tell whether the silicon does. M5 silenced the
//    instrument, and the hardware discriminators placed the fault on this reader
//    path (docs/waverider-dsp-silence.md). 5c counts in software: the count word
//    of the parameter block, decremented and stored each sample, and
//    `IF NE JUMP` back, the form the always-running loop proved on silicon.
//    Each tap is byte arithmetic, then `I0 = Rn`, then `DM(0, I0)` (Type 15b),
//    which also removes the pre-modify form selas mis-compresses outside a loop.
//    The float arithmetic, in the same order, is unchanged, so the result is
//    bit-identical to M5's.
// 3. **An add whose first operand is R8-R15** where the 16-bit form would be a
//    parcel 0xc000..0xc07f, which digikit's decoder can read as the first half of a
//    32-bit Type 2b (runner gap G5); selas then emits a 32-bit form both decoders
//    read alike.
//
// The gate (scripts/sharc_waverider_m5.py) checks that selmap and digikit read every
// instruction here as its source line says.
//
// Parameter block (8 words): table, phase, inc, pos, count, out, f0 row, f1 row. The
// reader counts `count` down to 0 (machine5_live.asm rewrites it every block) and
// keeps the two frame-row addresses in words 6 and 7.
//
// Clobbers R0-R15, I0, I2, I4, ASTAT. Uses M6 = 1, M7 = -1, M14 = 1 as fixed by the
// SHARC C ABI. Not ABI-clean: machine5_live.asm saves what it needs. I3 and I5 are
// the loop's own pointers and are not touched.
//
// PLACEMENT IS FIXED at PM sw 0x16eb00 (L1 block 1, byte 0x2dd600): the absolute
// jumps below are written for it from selas's symbol table. wr_t5v_exit (M9b) is
// machine9_live.asm's, not the reader's.

.SECTION/PM seg_pmco;

.GLOBAL wr_render5.;
wr_render5.:
      I4 = R4;                          // I4 -> parameter block
      R8 = DM(0, I4);                   // table (a byte address)
      R9 = DM(1, I4);                   // phase
      R10 = DM(2, I4);                  // inc
      R11 = DM(3, I4);                  // pos, Q16
      R12 = DM(4, I4);                  // N
      R0 = DM(5, I4);
      I2 = R0;                          // out

      // Frame rows: f0 = pos >> 16, f1 = min(f0 + 1, 15); a frame is 256 words,
      // 1,024 bytes.
      R0 = LSHIFT R11 BY -16;
      R2 = 1;
      R1 = R0 + R2;
      R2 = 15;
      R1 = MIN(R1, R2);
      R0 = LSHIFT R0 BY 10;
      R1 = LSHIFT R1 BY 10;
      R0 = R8 + R0;
      DM(6, I4) = R0;                   // frame f0's row
      R1 = R1 + R8;
      DM(7, I4) = R1;                   // frame f1's row

      // Frame fraction ff = (pos & 0xffff) * 2^-16, exact in float32.
      R3 = 0xffff;
      R3 = R11 AND R3;
      R2 = -16;
      F11 = FLOAT R3 BY R2;

      R13 = 0x800000;                   // half a sample: w1 = (phase + 2^23) >> 24
      R14 = 0x7fffff;                   // sample fraction mask
      R15 = -23;                        // sample fraction scale, 2^-23
      R8 = -15;                         // int16 -> float full scale, 2^-15
      R12 = PASS R12;
      IF EQ JUMP 0x16ebb5;              // -> wr5_done. (count 0: write nothing)
      R12 = -16;

.GLOBAL wr5_loop.;
wr5_loop.:
      R0 = LSHIFT R9 BY -24;            // w0 = k >> 1
      R0 = LSHIFT R0 BY 2;              // its byte offset in a row
      R1 = R9 + R13;
      R1 = LSHIFT R1 BY -24;            // w1 = (k + 1) >> 1, mod 256
      R1 = LSHIFT R1 BY 2;
      R2 = DM(6, I4);                   // frame f0's row
      R3 = R2 + R0;
      I0 = R3;
      R4 = DM(0, I0);                   // frame f0, word w0
      R3 = R2 + R1;
      I0 = R3;
      R5 = DM(0, I0);                   // frame f0, word w1
      R2 = DM(7, I4);                   // frame f1's row
      R3 = R2 + R0;
      I0 = R3;
      R6 = DM(0, I0);                   // frame f1, word w0
      R3 = R2 + R1;
      I0 = R3;
      R7 = DM(0, I0);                   // frame f1, word w1
      R2 = 16;
      R3 = LSHIFT R9 BY -19;
      R3 = R3 AND R2;                   // shB = 16 * (k & 1)
      R2 = R2 - R3;                     // shA = 16 - shB (M5d: SUB, a stock shape; XOR was not)
      R4 = LSHIFT R4 BY R2;
      R4 = ASHIFT R4 BY R12;            // s00 = sample k
      R5 = LSHIFT R5 BY R3;
      R5 = ASHIFT R5 BY R12;            // s01 = sample k + 1
      F4 = FLOAT R4 BY R8;
      F5 = FLOAT R5 BY R8;
      R6 = LSHIFT R6 BY R2;
      R6 = ASHIFT R6 BY R12;            // s10
      R7 = LSHIFT R7 BY R3;
      R7 = ASHIFT R7 BY R12;            // s11
      F6 = FLOAT R6 BY R8;
      F7 = FLOAT R7 BY R8;
      R0 = R9 AND R14;
      F0 = FLOAT R0 BY R15;             // sample fraction, exact
      F5 = F5 - F4;
      F5 = F0 * F5;
      F4 = F4 + F5;                     // a = s00 + fr * (s01 - s00)
      F7 = F7 - F6;
      F7 = F0 * F7;
      F6 = F6 + F7;                     // b = s10 + fr * (s11 - s10)
      F6 = F6 - F4;
      F6 = F11 * F6;
      F4 = F4 + F6;                     // y = a + ff * (b - a)
      R0 = DM(0x2de6c0);                // M9a: the gain, LEV / 100
      F4 = F0 * F4;                     // y * gain
      R9 = R9 + R10;                    // phase += inc, mod 2^32
      // M9b: osc 2 adds into the buffer osc 1 wrote (DM 0x2de6c4 = 1); osc 1 never
      // reads it, since the dispatch may leave anything there (NaN included)
      R0 = DM(0x2de6c4);
      R0 = PASS R0;
      IF EQ JUMP 0x16ebaa;              // -> wr5_store.
      R1 = DM(0, I2);                   // what osc 1 wrote
      F4 = F4 + F1;
.GLOBAL wr5_store.;
wr5_store.:
      DM(I2, M6) = F4;
      R0 = DM(4, I4);
      R1 = 1;
      R0 = R0 - R1;
      DM(4, I4) = R0;                   // samples left
      IF NE JUMP 0x16eb41;              // -> wr5_loop.

.GLOBAL wr5_done.;
wr5_done.:
      // the firmware's return shape (e.g. sw 0x1c9d62..0x1c9d6a): one instruction
      // between the I12 load and the jump, RFRAME in the second delay slot
      I12 = DM(M7, I6);
      DM(1, I4) = R9;                   // phase, for the next block
      JUMP (M14, I12) (DB);
      NOP;
      RFRAME;
.wr_render5..end:
      .type wr_render5.,STT_FUNC;

// M9b: machine9_live.asm's way out, here because its own 1 KB span is full: restore
// what the loop saved, re-execute the two instructions the entry JUMP replaced
// (0x1c9448, 0x1c944a) and go back to the dispatch.
.GLOBAL wr_t5v_exit.;
wr_t5v_exit.:
      R0 = DM(0x2dde00);
      R1 = DM(0x2dde04);
      R2 = DM(0x2dde08);
      R3 = DM(0x2dde0c);
      R4 = DM(0x2dde10);
      R5 = DM(0x2dde14);
      R6 = DM(0x2dde18);
      R7 = DM(0x2dde1c);
      R8 = DM(0x2dde20);
      R9 = DM(0x2dde24);
      R10 = DM(0x2dde28);
      R11 = DM(0x2dde2c);
      R12 = DM(0x2dde30);
      R13 = DM(0x2dde34);
      R14 = DM(0x2dde38);
      R15 = DM(0x2dde3c);
      I0 = DM(0x2dde40);
      I1 = DM(0x2dde44);
      I2 = DM(0x2dde48);
      I3 = DM(0x2dde4c);
      I4 = DM(0x2dde50);
      I5 = DM(0x2dde54);
      I12 = DM(0x2dde58);
      M0 = DM(0x2dde5c);
      M1 = DM(0x2dde60);
      M2 = DM(0x2dde64);
      M3 = DM(0x2dde68);
      M4 = DM(0x2dde6c);

      // the two instructions the entry JUMP replaced (0x1c9448, 0x1c944a)
      I5 = DM(-24, I6);
      R10 = DM(-34, I6);
      JUMP 0x1c944c;
.wr_t5v_exit..end:
      .type wr_t5v_exit.,STT_FUNC;

// M10a: modulator.asm's second half, here because its own span (DM 0x2dee00..0x2df000)
// takes 448 B and the whole is 668: store the phase, form the shape's value, and apply
// MPOS and MLEV, then go back to the loop. Registers as modulator.asm says.
.GLOBAL wr_mod_b.;
wr_mod_b.:
      DM(0, I1) = R15;

      // the shape's value, 0..0xffff, in R1, from x = phase >> 16
      R1 = LSHIFT R15 BY -16;
      R11 = PASS R11;
      IF EQ JUMP 0x16ec50;              // -> wr_mod_down.
      R2 = 1;
      COMP(R11, R2);
      IF EQ JUMP 0x16ec55;              // -> wr_mod_have. (ramp up: x)
      R2 = 4;
      COMP(R11, R2);
      IF EQ JUMP 0x16ec3f;              // -> wr_mod_sq.
      R2 = 0x8000;                      // the triangles
      COMP(R1, R2);
      IF LT JUMP 0x16ec39;              // -> wr_mod_tri.
      R2 = 0xffff;
      R1 = R2 - R1;
.GLOBAL wr_mod_tri.;
wr_mod_tri.:
      R1 = LSHIFT R1 BY 1;
      JUMP 0x16ec55;                    // -> wr_mod_have.
.GLOBAL wr_mod_sq.;
wr_mod_sq.:
      R2 = 0x8000;
      COMP(R1, R2);
      IF LT JUMP 0x16ec4a;              // -> wr_mod_sqhi.
      R1 = R1 - R1;
      JUMP 0x16ec55;                    // -> wr_mod_have.
.GLOBAL wr_mod_sqhi.;
wr_mod_sqhi.:
      R1 = 0xffff;
      JUMP 0x16ec55;                    // -> wr_mod_have.
.GLOBAL wr_mod_down.;
wr_mod_down.:
      R2 = 0xffff;
      R1 = R2 - R1;
.GLOBAL wr_mod_have.;
wr_mod_have.:
      // MPOS: POS += (MPOS - 0x3200) x shape x 0x7800 / (0x3200 x 0xffff)
      R0 = DM(0x2de7c4);
      R2 = 0x3200;
      R0 = R0 - R2;
      IF EQ JUMP 0x16ec72;              // -> wr_mod_lev. (no depth: POS untouched)
      R12 = R12 - R12;
      F0 = FLOAT R0 BY R12;
      F2 = FLOAT R1 BY R12;
      F0 = F0 * F2;
      R12 = 0x38199a33;                 // f32(0x7800 / (0x3200 x 0xffff))
      F0 = F0 * F12;
      R0 = TRUNC F0;
      R12 = PASS R0;
      R4 = R12 + R4;
      R4 = PASS R4;
      IF GE JUMP 0x16ec72;              // -> wr_mod_lev.
      R4 = R4 - R4;
.GLOBAL wr_mod_lev.;
wr_mod_lev.:
      // MLEV: LEV x (1 - MLEV/0x7f00 x (1 - shape/0xffff))
      R0 = DM(0x2de7c8);
      R0 = PASS R0;
      IF EQ JUMP 0x16ec95;              // -> wr_mod_done. (no depth: LEV untouched)
      R12 = R12 - R12;
      F0 = FLOAT R0 BY R12;
      R12 = 0x38010204;                 // f32(1 / 0x7f00)
      F0 = F0 * F12;
      R12 = R12 - R12;
      F2 = FLOAT R1 BY R12;
      R12 = 0x37800080;                 // f32(1 / 0xffff)
      F2 = F2 * F12;
      R12 = 0x3f800000;                 // 1.0
      F2 = F12 - F2;
      F0 = F0 * F2;
      F0 = F12 - F0;
      R12 = R12 - R12;
      F2 = FLOAT R14 BY R12;
      F2 = F2 * F0;
      R14 = TRUNC F2;
.GLOBAL wr_mod_done.;
wr_mod_done.:
      // PRST (m10a3): on a note, the oscillator's phase -- Off leaves it, On restarts
      // it at 0 (every note starts alike), Random sets it from the cycle counter.
      // The reader reads it from its block's phase word, DM(1, I4).
      R6 = PASS R6;
      IF EQ JUMP 0x16ecca;              // -> wr_mod_back. (no note)
      R0 = DM(0x2de7d4);
      R0 = LSHIFT R0 BY -8;
      R0 = PASS R0;
      IF EQ JUMP 0x16ecca;              // -> wr_mod_back. (Off: free-running)
      R1 = 1;
      COMP(R0, R1);
      IF EQ JUMP 0x16ecc7;              // -> wr_mod_zero.
      // Random: x = rotate(x, 7) + EMUCLK + 0x9e3779b9, the state at DM 0x2ddea0
      // (the cycle counter alone repeats: a block starts in step with the audio
      // interrupt, and the emulator's reads 0)
      R0 = DM(0x2ddea0);
      R1 = LSHIFT R0 BY 7;
      R0 = LSHIFT R0 BY -25;
      R12 = PASS R1;
      R0 = R12 + R0;
      R1 = EMUCLK;
      R12 = PASS R0;
      R0 = R12 + R1;
      R12 = 0x9e3779b9;
      R0 = R12 + R0;
      DM(0x2ddea0) = R0;
      DM(1, I4) = R0;
      JUMP 0x16ecca;                    // -> wr_mod_back.
.GLOBAL wr_mod_zero.;
wr_mod_zero.:
      R0 = R0 - R0;
      DM(1, I4) = R0;
.GLOBAL wr_mod_back.;
wr_mod_back.:
      JUMP 0x16edf3;                    // -> wr_t5v_modded. (machine9_live.asm)
.wr_mod_b..end:
      .type wr_mod_b.,STT_FUNC;
