// dclk.asm -- Waverider M10b-2: DCLK, the declick.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC executor and checked bit for bit against
// dnfw.waverider.live.declick (scripts/sharc_waverider_m5.py).
//
// POS and LEV change once a block, so a jump between two blocks (a looping MOVE's reset,
// a Square, a fast knob) steps the output between two samples: a click. DCLK takes that
// step out. After a voice's oscillators have played a block, it asks the reader for
// what the last block's settings would have played at this block's first sample (each
// oscillator at the phase it starts this block on), adds what is left of the last
// offset, and subtracts what this block plays there. That offset O is added to the
// block decaying over 1 ms, O x D[i] with D[i] = e^(-i/48) (the table at DM 0x2e0e00),
// and what is left after the block, O x D[N], carries into the next. With nothing
// changed O is exactly 0 and the block is untouched; an oscillator starting or stopping
// fades over the same 1 ms. A block with a note on this voice is left alone (PRST may
// have restarted the oscillator: the old settings have no phase to continue from).
// DCLK is HOLD (slot 41, frame offset 250 + 146t, shared), default 127: On.
//
// Two entries, both from machine9_live.asm:
// - wr_dclk_pre (first, at sw 0x170400): the loop's `CJUMP` to the reader comes here.
//   It notes this oscillator's table, pos, gain and starting phase, and that it ran,
//   then goes on to wr_render5 with the call's frame untouched (R4 = the reader block).
// - wr_dclk_post: the loop's two ways to the next voice after a voice's oscillators
//   (osc 2 done, or osc 2 at LEV 0 not run). It applies DCLK, makes this block's
//   settings the last block's, and goes on to wr_t5v_next.
//
// State (zeros at boot): per voice, 128 bytes at DM 0x2e1200 + 128t: per oscillator
// (osc x 48) the last block's table, pos, gain and whether it ran (+0..+12), then this
// block's table, pos, gain, starting phase and whether it ran (+16..+32); the carry at
// +96. Scratch at 0x2e1180: the voice's state, the oscillator, the expected sample, the
// reader's one-sample output; a reader block at 0x2e11a0.
//
// Clobbers what the reader does (R0-R15, I0, I2, I4) and I1, as the loop allows at both
// sites. Keeps I3, I5, I6, I7. Only forms the firmware itself uses, and every add has
// R8-R15 first (see reader_m5.asm).
//
// PLACEMENT IS FIXED at PM sw 0x170400 (DM 0x2e0800).

.SECTION/PM seg_pmco;

.GLOBAL wr_dclk_pre.;
wr_dclk_pre.:
      // this oscillator's "this block" fields: 0x2e1200 + 128t + 48 osc + 16
      R0 = DM(0x2dde80);
      R1 = 16;
      R0 = R1 - R0;                     // t
      R0 = LSHIFT R0 BY 7;
      R1 = DM(0x2de6c4);
      R2 = LSHIFT R1 BY 5;
      R3 = LSHIFT R1 BY 4;
      R12 = PASS R2;
      R2 = R12 + R3;                    // 48 x osc
      R12 = 0x2e1210;
      R0 = R12 + R0;
      R12 = PASS R2;
      R0 = R12 + R0;
      I1 = R0;
      I4 = R4;                          // the reader block (the reader sets I4 = R4 itself)
      R2 = DM(0, I4);
      DM(0, I1) = R2;                   // table
      R2 = DM(3, I4);
      DM(1, I1) = R2;                   // pos
      R2 = DM(0x2de6c0);
      DM(2, I1) = R2;                   // gain
      R2 = DM(1, I4);
      DM(3, I1) = R2;                   // the phase it starts on
      R2 = 1;
      DM(4, I1) = R2;                   // it ran
      JUMP 0x16eb00;                    // -> wr_render5. (reader_m9.asm, which returns to the loop)

.GLOBAL wr_dclk_post.;
wr_dclk_post.:
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R0 = LSHIFT R9 BY 7;
      R12 = 0x2e1200;
      R0 = R12 + R0;
      DM(0x2e1180) = R0;                // this voice's state

      // DCLK (HOLD): the frame's offset 250 + 146t
      R10 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R9 BY 1;
      R10 = R10 + R11;                  // 146t
      R12 = 0x25c586;                   // 0x25c48c + 250
      R1 = R12 + R10;
      R2 = -4;
      R2 = R1 AND R2;
      I0 = R2;
      R2 = DM(0, I0);
      R3 = 2;
      R3 = R1 AND R3;
      IF EQ JUMP 0x17046e;              // -> wr_dclk_low. (2 mod 4: the high half)
      R2 = LSHIFT R2 BY -16;
.GLOBAL wr_dclk_low.;
wr_dclk_low.:
      R3 = 0xffff;
      R2 = R2 AND R3;
      IF EQ JUMP 0x17055a;              // -> wr_dclk_off. (DCLK Off)
      // a note on this voice: the block is left alone
      R0 = DM(0x25c4ac);                // the frame's offset 32..35: the note mask high
      R0 = LSHIFT R0 BY -16;
      R1 = R1 - R1;
      R1 = R1 - R9;
      R0 = LSHIFT R0 BY R1;             // >> t
      R1 = 1;
      R0 = R0 AND R1;
      IF NE JUMP 0x17055a;              // -> wr_dclk_off.

      // the sample the last block's settings would play now, oscillator by oscillator
      R0 = R0 - R0;
      DM(0x2e1188) = R0;                // expected = +0.0
      DM(0x2e1184) = R0;                // osc = 0
.GLOBAL wr_dclk_osc.;
wr_dclk_osc.:
      R0 = DM(0x2e1180);
      R1 = DM(0x2e1184);
      R2 = LSHIFT R1 BY 5;
      R3 = LSHIFT R1 BY 4;
      R12 = PASS R2;
      R2 = R12 + R3;                    // 48 x osc
      R12 = PASS R2;
      R0 = R12 + R0;
      I1 = R0;                          // this oscillator's fields
      R2 = DM(3, I1);                   // ran last block?
      R2 = PASS R2;
      IF EQ JUMP 0x1704fe;              // -> wr_dclk_osc_next.
      R2 = DM(0, I1);
      DM(0x2e11a0) = R2;                // table: the last block's
      // the phase: where this oscillator starts this block, or where it stands if it
      // did not run (its reader block: 0x2ddf00 + 32t + 0x900 osc)
      R3 = DM(7, I1);
      R2 = DM(8, I1);                   // ran this block?
      R2 = PASS R2;
      IF NE JUMP 0x1704ca;              // -> wr_dclk_phase.
      R2 = LSHIFT R9 BY 5;
      R12 = 0x2ddf04;
      R2 = R12 + R2;
      R3 = DM(0x2e1184);
      R3 = PASS R3;
      IF EQ JUMP 0x1704c6;              // -> wr_dclk_osc1.
      R12 = 0x900;
      R2 = R12 + R2;
.GLOBAL wr_dclk_osc1.;
wr_dclk_osc1.:
      I0 = R2;
      R3 = DM(0, I0);
.GLOBAL wr_dclk_phase.;
wr_dclk_phase.:
      DM(0x2e11a4) = R3;                // phase
      R2 = R2 - R2;
      DM(0x2e11a8) = R2;                // inc: one sample needs none
      R2 = DM(1, I1);
      DM(0x2e11ac) = R2;                // pos: the last block's
      R2 = 1;
      DM(0x2e11b0) = R2;                // count
      R2 = 0x2e118c;
      DM(0x2e11b4) = R2;                // out: the scratch word
      R2 = DM(2, I1);
      DM(0x2de6c0) = R2;                // gain: the last block's
      R2 = R2 - R2;
      DM(0x2de6c4) = R2;                // replace, not add
      R4 = 0x2e11a0;
      CJUMP 0x16eb00 (DB);              // wr_render5(R4 = the scratch block)
      DM(I7, M7) = R2;
      DM(I7, M7) = 0x1704f3;            // return address - 1: wr_dclk_have. - 1
.GLOBAL wr_dclk_have.;
wr_dclk_have.:
      R0 = DM(0x2e1188);
      R1 = DM(0x2e118c);
      F0 = F0 + F1;
      DM(0x2e1188) = R0;                // expected += what the old settings play
.GLOBAL wr_dclk_osc_next.;
wr_dclk_osc_next.:
      R1 = DM(0x2e1184);
      R12 = 1;
      R1 = R12 + R1;
      DM(0x2e1184) = R1;
      R2 = 2;
      COMP(R1, R2);
      IF LT JUMP 0x17048c;              // -> wr_dclk_osc.

      // O = carry + (expected - what this block plays first)
      R0 = DM(0x2e1180);
      I1 = R0;
      R3 = DM(0x2dde88);                // the voice's buffer
      I0 = R3;
      R1 = DM(0, I0);
      R0 = DM(0x2e1188);
      F0 = F0 - F1;
      R2 = DM(24, I1);                  // the carry
      F0 = F2 + F0;
      F0 = PASS F0;
      IF EQ JUMP 0x17055a;              // -> wr_dclk_off. (nothing changed: the block is untouched)
      R13 = DM(0x2dde24);               // N, the block size
      R2 = 128;
      COMP(R13, R2);
      IF GT JUMP 0x17055a;              // -> wr_dclk_off. (past the table: left alone)
      R10 = 0x2e0e00;                   // D[0]
      R11 = PASS R3;                    // the buffer
.GLOBAL wr_dclk_ramp.;
wr_dclk_ramp.:
      I0 = R11;
      R1 = DM(0, I0);
      I0 = R10;
      R2 = DM(0, I0);
      F2 = F0 * F2;
      F1 = F1 + F2;                     // y + O x D[i]
      I0 = R11;
      DM(0, I0) = R1;
      R12 = 4;
      R10 = R12 + R10;
      R11 = R12 + R11;
      R12 = 1;
      R13 = R13 - R12;
      IF NE JUMP 0x170534;              // -> wr_dclk_ramp.
      I0 = R10;
      R2 = DM(0, I0);                   // D[N]
      F2 = F0 * F2;
      DM(24, I1) = R2;                  // the carry: O x D[N]
      JUMP 0x170562;                    // -> wr_dclk_shift.

.GLOBAL wr_dclk_off.;
wr_dclk_off.:
      R0 = DM(0x2e1180);
      I1 = R0;
      R2 = R2 - R2;
      DM(24, I1) = R2;                  // no carry
.GLOBAL wr_dclk_shift.;
wr_dclk_shift.:
      // this block's settings become the last block's, for both oscillators
      R0 = DM(0x2e1180);
      I1 = R0;
      R2 = DM(4, I1);
      DM(0, I1) = R2;
      R2 = DM(5, I1);
      DM(1, I1) = R2;
      R2 = DM(6, I1);
      DM(2, I1) = R2;
      R2 = DM(8, I1);
      DM(3, I1) = R2;
      R2 = R2 - R2;
      DM(8, I1) = R2;
      R2 = DM(16, I1);
      DM(12, I1) = R2;
      R2 = DM(17, I1);
      DM(13, I1) = R2;
      R2 = DM(18, I1);
      DM(14, I1) = R2;
      R2 = DM(20, I1);
      DM(15, I1) = R2;
      R2 = R2 - R2;
      DM(20, I1) = R2;
      JUMP 0x16eea7;                    // -> wr_t5v_next.
.wr_dclk..end:
      .type wr_dclk_pre.,STT_FUNC;
