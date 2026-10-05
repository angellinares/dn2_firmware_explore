// modulator.asm -- Waverider Milestone 10a: MOVE, the per-oscillator modulator.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC executor and checked bit for bit against
// dnfw.waverider.live.render_two (scripts/sharc_waverider_m5.py).
//
// Entered by `JUMP` from machine9_live.asm once per voice and oscillator, after the
// loop has read POS (R4, 0..0x7800) and LEV (R14, 0..0x7f00), and left by `JUMP` back
// to wr_t5v_modded in the loop. It reads this oscillator's four M10 controls and TRIG
// from the frame copy, steps the voice's phase, and offsets R4 and scales R14:
//
//   RATE  (osc 1 PD1 slot 29, osc 2 PD2 35; 0..100): the time one cycle takes,
//         1 s at 50 and x2 per 10 down: inc = F[r mod 10] << (r div 10), F baked at
//         DM 0x2de7d8 (dnfw.waverider.live.MOVE_RATE).
//   MPOS  (OFS1 28 / OFS2 34; 0..100, 50 = none): POS += (MPOS - 50) x shape x
//         0x7800 / (50 x 0xffff), in float32, truncated; not below 0.
//   MLEV  (DRIF 38 / NLEV 43; 0..127, 0 = none): LEV x (1 - MLEV/127 x (1 - shape)).
//   MOVE  (ATK 40 / BASE 44; 0..10 since M10b-4, the ColdFire's range hook): the
//         shape, computed by shapes.asm; past 10 is 10. The five one-shots (0..4)
//         stop at their end (the phase saturates); 5.. wrap. (M10a read 0..127 in
//         five bands of about 25; M10b-1 had five shapes, 0..4.)
//   TRIG  (TYPE 46, shared; 0..2, default 0): 0 restarts the phase on a note on this
//         voice (the frame's note-trigger mask, offset 34, bit t); 1, 2 free-running.
//   SYNC  (MOD 37 / CHAR 47; Off / On, M10b-2): sync.asm, entered at wr_mod_run, steps
//         the phase from the tempo and the song position instead of RATE's table.
//   PRST  (RSET 39, shared; Off / On / Random, default On): the OSCILLATOR's phase on
//         a note -- left running, restarted at 0, or set from the cycle counter.
//         Applied by wr_mod_b to the reader block's phase word (DM(1, I4)).
//         (TRIG and PRST until 2026-10-02's m10a3: TRIG was RSET, and the oscillators
//         never restarted, so the same note could start anywhere in its cycle.)
//
// MPOS 50 and MLEV 0 -- every sound's defaults -- skip their arithmetic entirely, so
// R4 and R14 come back untouched and a default sound is bit-identical to M9's.
//
// In: R9 = t (the voice), R4 = POS, R14 = LEV, DM 0x2de6c4 = the oscillator (0, 1).
// Out: R4, R14; R6 = 1 if a note started on this voice in this block (for wr_mod_b).
// Clobbers R0-R2, R6-R8, R10-R12, R15, I0-I2. Keeps R5, R9, R13, I3-I5,
// M4. Only forms the firmware itself uses, and every add has R8-R15 first (see
// reader_m5.asm).
//
// DM (byte addresses, the directory block's tail, written by the build):
//   0x2ddea0  PRST Random's generator state (wr_mod_b), zero at boot
//   0x2de700  16 voices x 2 oscillators: the phase, a u32 (zeros at boot)
//   0x2de780  per oscillator, 32 bytes: the frame byte offsets (168 + 2s) of RATE,
//             MPOS, MLEV, MOVE, TRIG and PRST, then SYNC (sync.asm reads that one)
//   0x2de7c0  the six 16-bit values this call read, one a word
//   0x2de7d8  F[0..9], the rate table
//
// PLACEMENT IS FIXED at PM sw 0x16f700 (DM 0x2dee00): the absolute jumps below are
// written for it from selas's symbol table. The second half, wr_mod_b (from storing
// the phase on), is in reader_m9.asm's span, as wr_t5v_exit is: 668 B did not fit.

.SECTION/PM seg_pmco;

.GLOBAL wr_mod.;
wr_mod.:
      // the voice's frame: 0x25c48c + 146t
      R10 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R9 BY 1;
      R10 = R10 + R11;
      R12 = 0x25c48c;
      R10 = R12 + R10;
      // this oscillator's offsets, 0x2de780 + 32 x osc; the values go to 0x2de7c0
      R0 = DM(0x2de6c4);
      R0 = LSHIFT R0 BY 5;
      R12 = 0x2de780;
      R0 = R12 + R0;
      I1 = R0;
      R12 = 0x2de7c0;
      I2 = R12;
      R15 = 6;
.GLOBAL wr_mod_read.;
wr_mod_read.:
      R0 = DM(I1, M6);                  // a byte offset in the voice's frame
      R0 = R10 + R0;
      R1 = -4;
      R1 = R0 AND R1;
      I0 = R1;
      R1 = DM(0, I0);                   // the word holding it
      R2 = 2;
      R2 = R0 AND R2;
      IF EQ JUMP 0x16f739;              // -> wr_mod_low. (2 mod 4: the high half)
      R1 = LSHIFT R1 BY -16;
.GLOBAL wr_mod_low.;
wr_mod_low.:
      R2 = 0xffff;
      R1 = R1 AND R2;
      DM(I2, M6) = R1;
      R2 = 1;
      R15 = R15 - R2;
      IF NE JUMP 0x16f724;              // -> wr_mod_read.

      // the phase: 0x2de700 + 8t + 4 x osc
      R0 = LSHIFT R9 BY 3;
      R1 = DM(0x2de6c4);
      R1 = LSHIFT R1 BY 2;
      R12 = 0x2de700;
      R0 = R12 + R0;
      R0 = R0 + R1;
      I1 = R0;
      R15 = DM(0, I1);

      // the voice's note-trigger bit, for TRIG and PRST: R6 = 1 if a note started
      R0 = DM(0x25c4ac);                // the frame's offset 32..35: the note mask high
      R0 = LSHIFT R0 BY -16;
      R1 = R1 - R1;
      R1 = R1 - R9;
      R0 = LSHIFT R0 BY R1;             // >> t
      R1 = 1;
      R6 = R0 AND R1;
      IF EQ JUMP 0x16f773;              // -> wr_mod_run. (no note)
      // TRIG: 0 restarts the shape on a note; 1, 2 free-running
      R0 = DM(0x2de7d0);
      R0 = LSHIFT R0 BY -8;
      R0 = PASS R0;
      IF NE JUMP 0x16f773;              // -> wr_mod_run. (free-running)
      R15 = R15 - R15;
.GLOBAL wr_mod_run.;
wr_mod_run.:
      // M10b-2: SYNC (sync.asm) gives the step itself when it is on, at wr_mod_inc
      JUMP 0x170000;                    // -> wr_sync. (sync.asm)
.GLOBAL wr_mod_free.;
wr_mod_free.:
      // RATE: r = word >> 8, k = r div 10, j = r mod 10, inc = F[j] << k
      R0 = DM(0x2de7c0);
      R0 = LSHIFT R0 BY -8;
      R1 = 100;
      R0 = MIN(R0, R1);
      R8 = R8 - R8;
      R1 = 10;
.GLOBAL wr_mod_div.;
wr_mod_div.:
      COMP(R0, R1);
      IF LT JUMP 0x16f78e;              // -> wr_mod_divd.
      R0 = R0 - R1;
      R2 = 1;
      R8 = R8 + R2;
      JUMP 0x16f783;                    // -> wr_mod_div.
.GLOBAL wr_mod_divd.;
wr_mod_divd.:
      R0 = LSHIFT R0 BY 2;
      R12 = 0x2de7d8;
      R0 = R12 + R0;
      I0 = R0;
      R0 = DM(0, I0);                   // F[j]
      R0 = LSHIFT R0 BY R8;             // the increment

.GLOBAL wr_mod_inc.;
wr_mod_inc.:
      // MOVE: the shape, 0..10, in R11 (M10b: the control steps shape by shape;
      // a value past 10 -- an LFO's overshoot -- is the last shape)
      R1 = DM(0x2de7cc);
      R11 = LSHIFT R1 BY -8;
      R2 = 10;
      COMP(R11, R2);
      IF GT R11 = PASS R2;
.GLOBAL wr_mod_shape.;
wr_mod_shape.:
      // step the phase; a one-shot (shapes 0..4) stops at the end
      R7 = PASS R15;
      R15 = R15 + R0;
      R2 = 5;
      COMP(R11, R2);
      IF GE JUMP 0x16ec18;              // -> wr_mod_b. (looping: wraps)
      COMPU(R15, R7);
      IF GE JUMP 0x16ec18;              // -> wr_mod_b.
      R15 = -1;
      // the rest (MPOS, MLEV) is wr_mod_b, after wr_t5v_exit in reader_m9.asm's
      // span, which hands the shape's value to shapes.asm (R7 = the phase before)
      JUMP 0x16ec18;                    // -> wr_mod_b.
.wr_mod..end:
      .type wr_mod.,STT_FUNC;
