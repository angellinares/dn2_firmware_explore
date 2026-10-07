// shapes.asm -- Waverider Milestone 10b-4: MOVE's eleven shapes.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC executor and checked bit for bit against
// dnfw.waverider.live.render_two (scripts/sharc_waverider_m5.py).
//
// Entered by `JUMP` from wr_mod_b (reader_m9.asm) once the voice's phase is stored, and
// left by `JUMP` back to wr_mod_have there, with the shape's value, 0..0xffff, in R1.
// The shapes, sorted by nature (owner, 2026-10-03), as dnfw.waverider.live.MOVE_SHAPES:
//
//   one-shots (the phase stops at its end, in modulator.asm):
//     0 Ramp Up     x
//     1 Ramp Down   0xffff - x
//     2 Exp Up      x^3 / 2^32, float32
//     3 Exp Down    (0xffff - x)^3 / 2^32
//     4 Tri Once    up to 0xffff at half the cycle, then down
//   loops (the phase wraps):
//     5 Up Loop     x
//     6 Down Loop   0xffff - x
//     7 Tri Loop    as Tri Once
//     8 Square      0xffff for the first half, then 0
//   random (a new value on each wrap, and on a note when TRIG is Retrig):
//     9 Rnd Hold    the value, held for the cycle
//    10 Rnd Glide   from the value before to the new one on a smoothstep,
//                   u^2 (3 - 2u) with u = x / 2^16, float32
//
// x is the phase's high half. The random shapes keep, per voice and oscillator, the
// value before (a) and the value now (b) at 0x2df400 + 8 (2t + osc), and one generator
// for all of them at 0x2df500: x = rotate(x, 7) + 0x6d2b79f5, the value x >> 16. That
// is PRST Random's step without the cycle counter, so a render is repeatable and the
// gate can check it. All of it is zero at boot.
//
// In: R15 = the phase after this block, R7 = the phase before it (0 if a note
// restarted it), R11 = the shape (0..10), R6 = 1 if a note started on this voice,
// R9 = t, DM 0x2de6c4 = the oscillator. Out: R1. Clobbers R0, R2, R7, R8, R10, R12,
// I0, I2 (the modulator's own clobbers). Keeps R4, R5, R6, R9, R11, R13, R14, R15,
// I1, I3-I5, M4. Only forms the firmware itself uses, every add with R8-R15 first.
//
// PLACEMENT IS FIXED at PM sw 0x16f800 (DM 0x2df000): the absolute jumps are written
// for it by scripts/sharc_resolve_jumps.py.

.SECTION/PM seg_pmco;

.GLOBAL wr_shape.;
wr_shape.:
      R1 = LSHIFT R15 BY -16;           // x
      R0 = PASS R11;
      R2 = 9;
      COMP(R0, R2);
      IF GE JUMP 0x16f874;              // -> wr_shape_rnd.
      R2 = 5;
      COMP(R0, R2);
      IF LT JUMP 0x16f81f;              // -> wr_shape_once.
      R2 = 8;
      COMP(R0, R2);
      IF EQ JUMP 0x16f863;              // -> wr_shape_sq.
      R2 = 7;
      COMP(R0, R2);
      IF EQ JUMP 0x16f851;              // -> wr_shape_tri.
      R2 = 5;
      R0 = R0 - R2;                     // the ramp loops: 5 -> up, 6 -> down
.GLOBAL wr_shape_once.;
wr_shape_once.:
      R0 = PASS R0;
      IF EQ JUMP 0x16f8e5;              // -> wr_shape_have. (ramp up: x)
      R2 = 1;
      COMP(R0, R2);
      IF EQ JUMP 0x16f849;              // -> wr_shape_down.
      R2 = 4;
      COMP(R0, R2);
      IF EQ JUMP 0x16f851;              // -> wr_shape_tri.
      R2 = 3;
      COMP(R0, R2);
      IF NE JUMP 0x16f83a;              // -> wr_shape_exp. (2, exp up: of x)
      R2 = 0xffff;                      // 3, exp down: of 0xffff - x
      R1 = R2 - R1;
.GLOBAL wr_shape_exp.;
wr_shape_exp.:
      R12 = R12 - R12;
      F0 = FLOAT R1 BY R12;
      F2 = F0 * F0;
      F2 = F2 * F0;
      R12 = 0x2f800000;                 // 2^-32
      F2 = F2 * F12;
      R1 = TRUNC F2;
      JUMP 0x16f8e5;                    // -> wr_shape_have.
.GLOBAL wr_shape_down.;
wr_shape_down.:
      R2 = 0xffff;
      R1 = R2 - R1;
      JUMP 0x16f8e5;                    // -> wr_shape_have.
.GLOBAL wr_shape_tri.;
wr_shape_tri.:
      R2 = 0x8000;
      COMP(R1, R2);
      IF LT JUMP 0x16f85d;              // -> wr_shape_triup.
      R2 = 0xffff;
      R1 = R2 - R1;
.GLOBAL wr_shape_triup.;
wr_shape_triup.:
      R1 = LSHIFT R1 BY 1;
      JUMP 0x16f8e5;                    // -> wr_shape_have.
.GLOBAL wr_shape_sq.;
wr_shape_sq.:
      R2 = 0x8000;
      COMP(R1, R2);
      IF LT JUMP 0x16f86e;              // -> wr_shape_sqhi.
      R1 = R1 - R1;
      JUMP 0x16f8e5;                    // -> wr_shape_have.
.GLOBAL wr_shape_sqhi.;
wr_shape_sqhi.:
      R1 = 0xffff;
      JUMP 0x16f8e5;                    // -> wr_shape_have.

.GLOBAL wr_shape_rnd.;
wr_shape_rnd.:
      // the voice's pair: a at 0x2df400 + 16t + 8 osc, b after it
      R8 = LSHIFT R9 BY 4;
      R2 = DM(0x2de6c4);
      R2 = LSHIFT R2 BY 3;
      R12 = 0x2df400;
      R8 = R12 + R8;
      R8 = R8 + R2;
      I0 = R8;
      R12 = 4;
      R8 = R12 + R8;
      I2 = R8;
      R10 = DM(0, I0);                  // a
      R0 = DM(0, I2);                   // b
      // a new value on a wrap, or on a note that restarted the shape
      COMPU(R15, R7);
      IF LT JUMP 0x16f8a2;              // -> wr_shape_draw. (wrapped)
      R6 = PASS R6;
      IF EQ JUMP 0x16f8bd;              // -> wr_shape_use. (no note)
      R2 = DM(0x2de7d0);                // TRIG: 0 restarts the shape on a note
      R2 = LSHIFT R2 BY -8;
      R2 = PASS R2;
      IF NE JUMP 0x16f8bd;              // -> wr_shape_use. (Free)
.GLOBAL wr_shape_draw.;
wr_shape_draw.:
      R10 = PASS R0;                    // a = b
      R2 = DM(0x2df500);
      R12 = LSHIFT R2 BY 7;
      R2 = LSHIFT R2 BY -25;
      R2 = R12 + R2;
      R12 = 0x6d2b79f5;
      R2 = R12 + R2;
      DM(0x2df500) = R2;
      R0 = LSHIFT R2 BY -16;            // b, the new value
      DM(0, I0) = R10;
      DM(0, I2) = R0;
.GLOBAL wr_shape_use.;
wr_shape_use.:
      R2 = 9;
      COMP(R11, R2);
      IF NE JUMP 0x16f8c7;              // -> wr_shape_glide.
      R1 = PASS R0;                     // Rnd Hold: b
      JUMP 0x16f8e5;                    // -> wr_shape_have.
.GLOBAL wr_shape_glide.;
wr_shape_glide.:
      // Rnd Glide: a + (b - a) x u^2 (3 - 2u), u = x / 2^16. a and b go to float
      // first: F0 is R0, which holds b
      R12 = R12 - R12;
      F8 = FLOAT R10 BY R12;            // a
      F10 = FLOAT R0 BY R12;            // b
      F0 = FLOAT R1 BY R12;
      R12 = 0x37800000;                 // 2^-16
      F0 = F0 * F12;                    // u
      F2 = F0 * F0;                     // u^2
      R12 = 0x40000000;                 // 2.0
      F7 = F0 * F12;                    // 2u
      R12 = 0x40400000;                 // 3.0
      F7 = F12 - F7;                    // 3 - 2u
      F2 = F2 * F7;                     // the smoothstep
      F10 = F10 - F8;
      F10 = F10 * F2;
      F0 = F8 + F10;
      R1 = TRUNC F0;
.GLOBAL wr_shape_have.;
wr_shape_have.:
      JUMP 0x16ec43;                    // -> wr_mod_have. (reader_m9.asm)
.wr_shape..end:
      .type wr_shape.,STT_FUNC;
