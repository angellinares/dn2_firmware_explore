// dclk.asm -- Waverider M10b-2: DCLK, the crossfade at a jump.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC executor and checked bit for bit against
// dnfw.waverider.live.render_two's crossfade (scripts/sharc_waverider_m5.py).
//
// POS and LEV change once a block, so a jump between two blocks (a looping MOVE's reset,
// a Square, a fast knob, another table) switches the wave between two samples: a click.
// DCLK crossfades it: from the jump on, the last block's settings keep playing at the
// same phase and fade out while the new ones fade in, linearly over the DCLK time.
// A jump is POS by more than 2 frames, another table, or the gain by more than 0.1;
// smaller moves pass straight through, untouched. (Until 2026-10-06 this was a 1 ms
// offset declick; the owner chose the crossfade after the measurement in
// docs/waverider-m10-move.md.)
//
// DCLK is HOLD (slot 41, frame offset 250 + 146t, shared): 0 Off, 1..127 a crossfade of
// 1..100 ms, the length in samples from the table at DM 0x2e0e00 and its inverse (the
// DSP has no divide) at 0x2e1000 (dnfw.waverider.live.dclk_lengths, dclk_inverses).
// A block with a note on this voice cancels a fade and starts none (PRST may have
// restarted the oscillator).
//
// wr_dclk_pre (at sw 0x170400): machine9_live.asm's `CJUMP` to the reader comes here,
// once per voice and oscillator, R4 = the reader block. It notes the block's table, pos
// and gain against the last block's (state per voice and oscillator, 64 bytes at DM
// 0x2e1400 + 128t + 64 osc: last table, pos, gain, valid; the fade's old table, pos,
// gain and samples left), then:
// - no fade: `JUMP` on to wr_render5 with the call's frame untouched, as before DCLK;
// - a fade: it renders the new settings into the buffer at 0x2e1c00 and the old ones,
//   from the same phase, into 0x2e1e00 (two calls of the reader), mixes them into the
//   block's out (replacing for osc 1, adding for osc 2), y = n + (o - n) x a with
//   a = (left - i) / length while it is above 0, and returns to the loop itself, as the
//   reader would. Scratch at 0x2e1280..0x2e12c0, a reader block at 0x2e12a0.
//
// Clobbers what the reader does (R0-R15, I0, I2, I4) and I1. Keeps I3, I5, I6, I7.
// Only forms the firmware itself uses, and every add has R8-R15 first (see
// reader_m5.asm).
//
// PLACEMENT IS FIXED at PM sw 0x170400 (DM 0x2e0800).

.SECTION/PM seg_pmco;

.GLOBAL wr_dclk_pre.;
wr_dclk_pre.:
      I4 = R4;
      DM(0x2e1284) = R4;                // the reader block
      // this oscillator's state: 0x2e1400 + 128t + 64 osc
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R0 = LSHIFT R9 BY 7;
      R1 = DM(0x2de6c4);
      R2 = LSHIFT R1 BY 6;
      R12 = PASS R2;
      R0 = R12 + R0;
      R12 = 0x2e1400;
      R0 = R12 + R0;
      DM(0x2e1280) = R0;
      I1 = R0;

      // DCLK (HOLD): the frame's offset 250 + 146t; v = min(word >> 8, 127)
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
      IF EQ JUMP 0x170444;              // -> wr_dclk_low. (2 mod 4: the high half)
      R2 = LSHIFT R2 BY -16;
.GLOBAL wr_dclk_low.;
wr_dclk_low.:
      R3 = 0xffff;
      R2 = R2 AND R3;
      R2 = LSHIFT R2 BY -8;
      R3 = 127;
      R2 = MIN(R2, R3);
      R2 = LSHIFT R2 BY 2;
      DM(0x2e1298) = R2;                // 4 v, for the inverse later
      R12 = 0x2e0e00;
      R2 = R12 + R2;
      I0 = R2;
      R8 = DM(0, I0);                   // the length in samples, 0 for Off
      R8 = PASS R8;
      IF EQ JUMP 0x1704c4;              // -> wr_dclk_nofade. (DCLK Off)
      R3 = DM(0x2dde24);                // the block size
      R2 = 128;
      COMP(R3, R2);
      IF GT JUMP 0x1704c4;              // -> wr_dclk_nofade. (longer than the scratch buffers)
      // a note on this voice: no fade
      R0 = DM(0x25c4ac);                // the frame's offset 32..35: the note mask high
      R0 = LSHIFT R0 BY -16;
      R1 = R1 - R1;
      R1 = R1 - R9;
      R0 = LSHIFT R0 BY R1;             // >> t
      R1 = 1;
      R0 = R0 AND R1;
      IF NE JUMP 0x1704c4;              // -> wr_dclk_nofade.
      R2 = DM(3, I1);                   // a last block to compare with?
      R2 = PASS R2;
      IF EQ JUMP 0x1704c7;              // -> wr_dclk_record.

      // a jump: another table, POS by more than 2 frames, or the gain by more than 0.1
      R0 = DM(0, I4);
      R2 = DM(0, I1);
      COMP(R0, R2);
      IF NE JUMP 0x1704b3;              // -> wr_dclk_start.
      R0 = DM(3, I4);
      R2 = DM(1, I1);
      R0 = R0 - R2;
      R2 = 0x20000;
      COMP(R0, R2);
      IF GT JUMP 0x1704b3;              // -> wr_dclk_start.
      R2 = -131072;
      COMP(R0, R2);
      IF LT JUMP 0x1704b3;              // -> wr_dclk_start.
      R0 = DM(0x2de6c0);
      R2 = DM(2, I1);
      F0 = F0 - F2;
      R2 = 0x3dcccccd;                  // f32(0.1)
      COMP(F0, F2);
      IF GT JUMP 0x1704b3;              // -> wr_dclk_start.
      R2 = -0x42333333;                 // f32(-0.1), 0xbdcccccd
      COMP(F0, F2);
      IF LT JUMP 0x1704b3;              // -> wr_dclk_start.
      JUMP 0x1704c7;                    // -> wr_dclk_record.

.GLOBAL wr_dclk_start.;
wr_dclk_start.:
      // the last block's settings become the fade's old ones, for the whole length
      R2 = DM(0, I1);
      DM(4, I1) = R2;
      R2 = DM(1, I1);
      DM(5, I1) = R2;
      R2 = DM(2, I1);
      DM(6, I1) = R2;
      DM(7, I1) = R8;
      JUMP 0x1704c7;                    // -> wr_dclk_record.
.GLOBAL wr_dclk_nofade.;
wr_dclk_nofade.:
      R2 = R2 - R2;
      DM(7, I1) = R2;                   // no fade
.GLOBAL wr_dclk_record.;
wr_dclk_record.:
      R2 = DM(0, I4);
      DM(0, I1) = R2;                   // this block's table, pos and gain are the last now
      R2 = DM(3, I4);
      DM(1, I1) = R2;
      R2 = DM(0x2de6c0);
      DM(2, I1) = R2;
      R2 = 1;
      DM(3, I1) = R2;
      R2 = DM(7, I1);
      R2 = PASS R2;
      IF GT JUMP 0x1704e4;              // -> wr_dclk_fade.
      R4 = DM(0x2e1284);
      JUMP 0x16eb00;                    // -> wr_render5. (no fade: as before, back to the loop)

.GLOBAL wr_dclk_fade.;
wr_dclk_fade.:
      // 1. the new settings into the first buffer
      R0 = DM(5, I4);
      DM(0x2e1288) = R0;                // the block's own out
      R0 = DM(0x2de6c4);
      DM(0x2e128c) = R0;                // osc 2: add
      R0 = DM(1, I4);
      DM(0x2e1290) = R0;                // the phase this block starts on
      R0 = DM(4, I4);
      DM(0x2e1294) = R0;                // N
      R0 = 0x2e1c00;
      DM(5, I4) = R0;
      R0 = R0 - R0;
      DM(0x2de6c4) = R0;                // replace
      R4 = DM(0x2e1284);
      CJUMP 0x16eb00 (DB);              // wr_render5(R4 = the reader block)
      DM(I7, M7) = R2;
      DM(I7, M7) = 0x17050b;            // return address - 1: wr_dclk_new. - 1
.GLOBAL wr_dclk_new.;
wr_dclk_new.:
      R4 = DM(0x2e1284);
      I4 = R4;
      R0 = DM(0x2e1288);
      DM(5, I4) = R0;
      // 2. the old settings, from the same phase, into the second buffer
      R0 = DM(0x2e1280);
      I1 = R0;
      R2 = DM(4, I1);
      DM(0x2e12a0) = R2;                // table
      R2 = DM(0x2e1290);
      DM(0x2e12a4) = R2;                // phase
      R2 = DM(2, I4);
      DM(0x2e12a8) = R2;                // inc
      R2 = DM(5, I1);
      DM(0x2e12ac) = R2;                // pos
      R2 = DM(0x2e1294);
      DM(0x2e12b0) = R2;                // count
      R2 = 0x2e1e00;
      DM(0x2e12b4) = R2;                // out
      R2 = DM(6, I1);
      DM(0x2de6c0) = R2;                // gain
      R4 = 0x2e12a0;
      CJUMP 0x16eb00 (DB);              // wr_render5(R4 = the scratch block)
      DM(I7, M7) = R2;
      DM(I7, M7) = 0x17054a;            // return address - 1: wr_dclk_old. - 1
.GLOBAL wr_dclk_old.;
wr_dclk_old.:
      // 3. y = n + (o - n) x (left - i) / length, while left - i > 0; into the block's out
      R0 = DM(0x2e1280);
      I1 = R0;
      R8 = DM(7, I1);                   // samples left
      R2 = DM(0x2e1298);
      R12 = 0x2e1000;
      R2 = R12 + R2;
      I0 = R2;
      R6 = DM(0, I0);                   // 1 / length
      R10 = 0x2e1c00;                   // n
      R11 = 0x2e1e00;                   // o
      R13 = DM(0x2e1288);               // the block's out
      R14 = DM(0x2e1294);               // N
      R15 = DM(0x2e128c);               // add?
      R5 = R5 - R5;
.GLOBAL wr_dclk_mix.;
wr_dclk_mix.:
      I0 = R10;
      R1 = DM(0, I0);                   // n
      R8 = PASS R8;
      IF LE JUMP 0x170580;              // -> wr_dclk_mixed. (the fade is over: n)
      I0 = R11;
      R2 = DM(0, I0);                   // o
      F2 = F2 - F1;
      F3 = FLOAT R8 BY R5;
      F3 = F3 * F6;                     // a
      F2 = F2 * F3;
      F1 = F1 + F2;
.GLOBAL wr_dclk_mixed.;
wr_dclk_mixed.:
      R15 = PASS R15;
      IF EQ JUMP 0x170589;              // -> wr_dclk_put.
      I0 = R13;
      R2 = DM(0, I0);
      F1 = F1 + F2;                     // osc 2 adds to what osc 1 wrote
.GLOBAL wr_dclk_put.;
wr_dclk_put.:
      I0 = R13;
      DM(0, I0) = R1;
      R12 = 4;
      R10 = R12 + R10;
      R11 = R12 + R11;
      R13 = R12 + R13;
      R12 = 1;
      R8 = R8 - R12;
      R14 = R14 - R12;
      IF NE JUMP 0x17056e;              // -> wr_dclk_mix.
      R8 = PASS R8;
      IF GE JUMP 0x1705a1;              // -> wr_dclk_left.
      R8 = R8 - R8;
.GLOBAL wr_dclk_left.;
wr_dclk_left.:
      DM(7, I1) = R8;                   // what is left of the fade
      R0 = DM(0x2e128c);
      DM(0x2de6c4) = R0;                // the oscillator flag, as the loop left it
      // back to the loop, the reader's return shape
      I12 = DM(M7, I6);
      JUMP (M14, I12) (DB);
      NOP;
      RFRAME;
.wr_dclk..end:
      .type wr_dclk_pre.,STT_FUNC;
