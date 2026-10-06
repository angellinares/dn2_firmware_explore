// sync.asm -- Waverider M10b-2: SYNC, MOVE locked to the tempo.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC executor and checked bit for bit against
// dnfw.waverider.live.move_step (scripts/sharc_waverider_m5.py).
//
// Entered by `JUMP` from modulator.asm at wr_mod_run, after the phase is loaded (and
// restarted for TRIG Retrig), in place of its RATE arithmetic. It reads this
// oscillator's SYNC (osc 1 MOD, slot 37; osc 2 CHAR, 47: the seventh word of the
// modulator's offset row). Off: back to the free RATE at wr_mod_free. On: RATE
// (0..100) picks a note length through the table at DM 0x2e0400 (one word per RATE,
// k | s << 8: the length's multiplier is 1 << k for s = 0, else (1 + (1 << s)) << k,
// dnfw.waverider.live.sync_table), and the step goes back to wr_mod_inc in R0:
//
//   TRIG Free:   the phase becomes the frame's song position (offset 2644, a u32 in
//                which 2^32 is 384 sixteenths, written by the ColdFire's sync.c) times
//                the multiplier, mod 2^32: the cycle starts on step 1. R0 is the step
//                that takes the phase there.
//   TRIG Retrig: the phase steps by tempo x multiplier x 2^32 / (384 x 2,700,000) a
//                block, in float32 (the tempo is BPM x 120, frame offset 0xd8): the
//                length holds from each note.
//
// In: as modulator.asm at wr_mod_run (R10 = the voice's frame, R15 = the phase, the
// controls it read at 0x2de7c0). Out: R0 = the step. Clobbers R0-R2, R7, R8, R12, I0.
// Keeps everything modulator.asm keeps, and R6, R10, R15, I1. Only forms the firmware
// itself uses, and every add has R8-R15 first (see reader_m5.asm).
//
// PLACEMENT IS FIXED at PM sw 0x170000 (DM 0x2e0000): the absolute jumps below are
// written for it from selas's symbol table.

.SECTION/PM seg_pmco;

.GLOBAL wr_sync.;
wr_sync.:
      // SYNC, through the offset row's seventh word: 0x2de780 + 32 x osc + 24
      R0 = DM(0x2de6c4);
      R0 = LSHIFT R0 BY 5;
      R12 = 0x2de798;
      R0 = R12 + R0;
      I0 = R0;
      R0 = DM(0, I0);                   // a byte offset in the voice's frame
      R0 = R10 + R0;
      R1 = -4;
      R1 = R0 AND R1;
      I0 = R1;
      R1 = DM(0, I0);                   // the word holding it
      R2 = 2;
      R2 = R0 AND R2;
      IF EQ JUMP 0x170023;              // -> wr_sync_low. (2 mod 4: the high half)
      R1 = LSHIFT R1 BY -16;
.GLOBAL wr_sync_low.;
wr_sync_low.:
      R2 = 0xffff;
      R1 = R1 AND R2;
      R1 = PASS R1;
      IF EQ JUMP 0x16f776;              // -> wr_mod_free. (SYNC off: RATE is the free speed)

      // the note length: the table's word for r = min(RATE >> 8, 100)
      R0 = DM(0x2de7c0);
      R0 = LSHIFT R0 BY -8;
      R1 = 100;
      R0 = MIN(R0, R1);
      R0 = LSHIFT R0 BY 2;
      R12 = 0x2e0400;
      R0 = R12 + R0;
      I0 = R0;
      R0 = DM(0, I0);                   // k | s << 8
      R8 = 0xff;
      R8 = R0 AND R8;                   // k
      R7 = LSHIFT R0 BY -8;             // s, 0 for a multiplier of 1 << k

      // TRIG: 0 Retrig, the step from the tempo; 1, 2 Free, the phase from the position
      R0 = DM(0x2de7d0);
      R0 = LSHIFT R0 BY -8;
      R0 = PASS R0;
      IF EQ JUMP 0x170065;              // -> wr_sync_retrig.
      R1 = DM(0x25cee0);                // the position: frame offset 2644 (0x25c48c + 0xa54)
      R7 = PASS R7;
      IF EQ JUMP 0x17005e;              // -> wr_sync_shift.
      R2 = LSHIFT R1 BY R7;
      R12 = PASS R2;
      R1 = R12 + R1;                    // position x (1 + 2^s), mod 2^32
.GLOBAL wr_sync_shift.;
wr_sync_shift.:
      R1 = LSHIFT R1 BY R8;             // x 2^k: the phase this block ends on
      R0 = R1 - R15;                    // the step that takes the phase there
      JUMP 0x16f79c;                    // -> wr_mod_inc.

.GLOBAL wr_sync_retrig.;
wr_sync_retrig.:
      R1 = 1;
      R7 = PASS R7;
      IF EQ JUMP 0x170070;              // -> wr_sync_mult.
      R2 = LSHIFT R1 BY R7;
      R12 = PASS R2;
      R1 = R12 + R1;                    // 1 + 2^s
.GLOBAL wr_sync_mult.;
wr_sync_mult.:
      R1 = LSHIFT R1 BY R8;             // the multiplier
      R0 = DM(0x25c564);                // frame offset 0xd8 (0x25c48c + 0xd8): the tempo, low half
      R2 = 0xffff;
      R0 = R0 AND R2;
      R12 = R12 - R12;
      F0 = FLOAT R0 BY R12;
      F1 = FLOAT R1 BY R12;
      F0 = F0 * F1;
      R12 = 0x40848f8b;                 // f32(2^32 / (384 x 2,700,000))
      F0 = F0 * F12;
      R0 = TRUNC F0;                    // the step
      JUMP 0x16f79c;                    // -> wr_mod_inc.
.wr_sync..end:
      .type wr_sync.,STT_FUNC;
