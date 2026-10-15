// page5.asm -- Waverider page 5, the shape (docs/waverider-shape.md): FOLD, NPOS, and the
// shaper's TYPE (Ring, AM) with AMT.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC executor inside the DN2 1.11 image and checked
// bit for bit against dnfw.waverider.live (fold, shaper, npos_offset; scripts/sharc_waverider_shape.py).
//
// The four controls are frame words like the others, at 0x25c48c + 146t:
//   FOLD  sound slot 58, offset 284    NPOS  slot 61, offset 290
//   TYPE  slot 62, offset 292 (>> 8: 0 Off, 1 Ring, 2 AM; others Off)    AMT  slot 48, offset 264
// Each at 0 (every sound's default since page 5) skips its code, so the voice is
// bit-identical to the one before page 5.
//
// Three ways in, each by a JUMP another source sends here instead of where it went:
//
// wr_p5_npos (shapes.asm's way back to wr_mod_have, once per voice and oscillator, every
//   block): NPOS. A xorshift32 per voice and oscillator (DM 0x2e6000 + 4 (2t + osc),
//   seeded by the image, live.npos_seeds) steps once; r = x as a signed int x 2^-31, and
//   POS += trunc(r x w^2 x f32(0x3c00 / 0x7f00^2)), w = the NPOS word, not below 0. MPOS
//   and the loop's min(POS, 0x7800) follow, as for any POS. Registers as shapes.asm keeps
//   them: in R4 = POS, R9 = t; clobbers R0, R2, R7, R8, R10, R12, I0 (the modulator's own).
//
// wr_p5_mid (machine9_live.asm's JUMP to wr_t5v_osc once osc 1 is done): with TYPE 1 or 2
//   and AMT above 0, osc 1's samples are copied to DM 0x2e5e00 (128 floats), for the
//   shaper after osc 2. Clobbers R0-R3, R9-R12, I0, I1.
//
// wr_p5_ran / wr_p5_skip (machine9_live.asm's two ways to the sub, osc 2 run or skipped):
//   the shaper, then FOLD, on the track buffer, then on to sub.asm by the same way in.
//     Ring  y = b + a (o1 o2 / T - b)          AM  y = b + a (o1 (o2 / T + 1) 0.5 - b)
//     with b the buffer, o1 the copy, o2 = b - o1, a = AMT / 0x7f00, T = f32(10^(-11/20)).
//     FOLD  g = (1 + FOLD x f32(7 / 0x7f00)) x f32(1 / T); v = x g + 1; the phase
//           (TRUNC v BY 24) << 6; |w| = (ABS phase >> 1) x 2^-29, 0..2; y = |w| T - T.
//   An osc 2 skipped this block leaves b = o1: o2 is 0. Clobbers R0-R15, I0-I2, as sub.asm
//   does; I3 and I5 (the loop's pointers) are not touched.
//
// The sample loops are hardware loops with straight-line bodies (PRM: such a loop can run
// F1-active; a body under 11 instructions is all ISA, so each sits under .NOCOMPRESS), with
// each branch taken once outside them (one loop per type). Every float result feeds a
// two-operand compute or a store (anomaly 20000072: F0 then a single-operand compute).
//
// DM (byte addresses, after build3.asm):
//   0x2e5e00  osc 1's copy, 128 float32
//   0x2e6000  NPOS's generators, 32 u32 (seeded)
//   0x2e6080  1 when osc 2 ran this block (which way to sub.asm)
//
// PLACEMENT IS FIXED at PM sw 0x172b00 (DM 0x2e5600): the absolute jumps below are written
// for it by scripts/sharc_resolve_jumps.py.

.SECTION/PM seg_pmco;

.GLOBAL wr_p5_npos.;
wr_p5_npos.:
      // NPOS: 0x25c48c + 290 + 146t (R9 = t)
      R10 = LSHIFT R9 BY 7;
      R12 = LSHIFT R9 BY 4;
      R10 = R10 + R12;
      R12 = LSHIFT R9 BY 1;
      R10 = R10 + R12;                  // 146t
      R12 = 0x25c5ae;                   // 0x25c48c + 290
      R0 = R12 + R10;
      R2 = -4;
      R2 = R0 AND R2;
      I0 = R2;
      R2 = DM(0, I0);
      R7 = 2;
      R7 = R0 AND R7;
      R7 = LSHIFT R7 BY 3;              // 16 for the high half
      R12 = R12 - R12;
      R7 = R12 - R7;
      R2 = LSHIFT R2 BY R7;
      R12 = 0xffff;
      R2 = R2 AND R12;                  // the NPOS word
      IF EQ JUMP 0x16ec46;              // -> wr_mod_have. (reader_m9.asm: no NPOS)
      // the generator: 0x2e6000 + 4 (2t + osc)
      R0 = LSHIFT R9 BY 1;
      R12 = DM(0x2de6c4);
      R0 = R12 + R0;
      R0 = LSHIFT R0 BY 2;
      R12 = 0x2e6000;
      R0 = R12 + R0;
      I0 = R0;
      R8 = DM(0, I0);
      R0 = LSHIFT R8 BY 13;
      R8 = R8 XOR R0;
      R0 = LSHIFT R8 BY -17;
      R8 = R8 XOR R0;
      R0 = LSHIFT R8 BY 5;
      R8 = R8 XOR R0;
      DM(0, I0) = R8;
      // depth = w^2 x f32(0x3c00 / 0x7f00^2), r = x x 2^-31
      R12 = R12 - R12;
      F2 = FLOAT R2 BY R12;
      F2 = F2 * F2;
      R12 = 0x3773cb5e;                 // f32(0x3c00 / 0x7f00^2)
      F2 = F2 * F12;
      R12 = -31;
      F8 = FLOAT R8 BY R12;
      F2 = F8 * F2;
      R0 = TRUNC F2;
      R12 = PASS R0;
      R4 = R12 + R4;                    // POS + the offset
      R4 = PASS R4;
      IF GE JUMP 0x16ec46;              // -> wr_mod_have.
      R4 = R4 - R4;                     // not below 0
      JUMP 0x16ec46;                    // -> wr_mod_have.

.GLOBAL wr_p5_mid.;
wr_p5_mid.:
      CALL 0x172b91;                    // -> wr_p5_shaper_on.
      R0 = PASS R0;
      IF EQ JUMP 0x16ed83;              // -> wr_t5v_osc. (no shaper: nothing to keep)
      // osc 1's samples, two a pass (the block is even: 32)
      R0 = DM(0x2dde88);
      I0 = R0;                          // the track buffer
      R12 = 0x2e5e00;
      I1 = R12;
      R0 = DM(0x2dde24);
      R0 = LSHIFT R0 BY -1;
      LCNTR = R0, DO wr_p5_copy_end. UNTIL LCE;
.NOCOMPRESS;
      R1 = DM(I0, M6);
      R2 = DM(I0, M6);
      DM(I1, M6) = R1;
.GLOBAL wr_p5_copy_end.;
wr_p5_copy_end.:
      DM(I1, M6) = R2;
.COMPRESS;
      JUMP 0x16ed83;                    // -> wr_t5v_osc.

// R0 = the shaper's TYPE (1 Ring, 2 AM) when TYPE is 1 or 2 and AMT above 0, else 0;
// R1 = the AMT word; R9 = t. Clobbers R2, R3, R10-R12, I0.
.GLOBAL wr_p5_shaper_on.;
wr_p5_shaper_on.:
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R10 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R9 BY 1;
      R10 = R10 + R11;                  // 146t
      R12 = 0x25c5b0;                   // 0x25c48c + 292: TYPE
      R2 = R12 + R10;
      R3 = -4;
      R3 = R2 AND R3;
      I0 = R3;
      R0 = DM(0, I0);
      R3 = 2;
      R3 = R2 AND R3;
      R3 = LSHIFT R3 BY 3;
      R12 = R12 - R12;
      R3 = R12 - R3;
      R0 = LSHIFT R0 BY R3;
      R12 = 0xffff;
      R0 = R0 AND R12;
      R0 = LSHIFT R0 BY -8;             // TYPE
      R12 = 0x25c594;                   // 0x25c48c + 264: AMT
      R2 = R12 + R10;
      R3 = -4;
      R3 = R2 AND R3;
      I0 = R3;
      R1 = DM(0, I0);
      R3 = 2;
      R3 = R2 AND R3;
      R3 = LSHIFT R3 BY 3;
      R12 = R12 - R12;
      R3 = R12 - R3;
      R1 = LSHIFT R1 BY R3;
      R12 = 0xffff;
      R1 = R1 AND R12;                  // AMT
      IF EQ JUMP 0x172bee;              // -> wr_p5_off.
      R12 = 1;
      R12 = R0 - R12;
      R3 = 1;
      COMPU(R12, R3);
      IF LE JUMP 0x172bef;              // -> wr_p5_on. (TYPE - 1 in 0..1)
.GLOBAL wr_p5_off.;
wr_p5_off.:
      R0 = R0 - R0;
.GLOBAL wr_p5_on.;
wr_p5_on.:
      RTS;

.GLOBAL wr_p5_ran.;
wr_p5_ran.:
      R0 = 1;
      DM(0x2e6080) = R0;
      JUMP 0x172bfe;                    // -> wr_p5_post.
.GLOBAL wr_p5_skip.;
wr_p5_skip.:
      R0 = R0 - R0;
      DM(0x2e6080) = R0;

.GLOBAL wr_p5_post.;
wr_p5_post.:
      CALL 0x172b91;                    // -> wr_p5_shaper_on.
      R12 = DM(0x2dde88);
      I0 = R12;                         // the track buffer, read
      I2 = R12;                         // and written
      R12 = 0x2e5e00;
      I1 = R12;                         // osc 1's copy
      R13 = DM(0x2dde24);               // the block
      R12 = 0x406314a0;                 // f32(1 / T)
      R8 = PASS R12;
      R12 = R12 - R12;
      F9 = FLOAT R1 BY R12;
      R12 = 0x38010204;                 // f32(1 / 0x7f00)
      F9 = F9 * F12;                    // a
      R0 = PASS R0;
      IF EQ JUMP 0x172c78;              // -> wr_p5_fold.
      R12 = 1;
      COMPU(R0, R12);
      IF NE JUMP 0x172c47;              // -> wr_p5_am.
      // Ring
      LCNTR = R13, DO wr_p5_ring_end. UNTIL LCE;
.NOCOMPRESS;
      R4 = DM(I0, M6);                  // b
      R5 = DM(I1, M6);                  // o1
      F2 = F4 - F5;                     // o2
      F2 = F5 * F2;
      F2 = F2 * F8;                     // o1 o2 / T
      F2 = F2 - F4;
      F2 = F9 * F2;
      F2 = F4 + F2;
.GLOBAL wr_p5_ring_end.;
wr_p5_ring_end.:
      DM(I2, M6) = F2;
.COMPRESS;
      JUMP 0x172c78;                    // -> wr_p5_fold.
.GLOBAL wr_p5_am.;
wr_p5_am.:
      R12 = 2;
      COMPU(R0, R12);
      IF NE JUMP 0x172c78;              // -> wr_p5_fold.
      R10 = 0x3f800000;                 // 1.0
      R11 = 0x3f000000;                 // 0.5
      LCNTR = R13, DO wr_p5_am_end. UNTIL LCE;
.NOCOMPRESS;
      R4 = DM(I0, M6);                  // b
      R5 = DM(I1, M6);                  // o1
      F2 = F4 - F5;                     // o2
      F2 = F2 * F8;
      F2 = F2 + F10;                    // o2 / T + 1
      F2 = F5 * F2;
      F2 = F2 * F11;                    // o1 (o2 / T + 1) / 2
      F2 = F2 - F4;
      F2 = F9 * F2;
      F2 = F4 + F2;
.GLOBAL wr_p5_am_end.;
wr_p5_am_end.:
      DM(I2, M6) = F2;
.COMPRESS;

.GLOBAL wr_p5_fold.;
wr_p5_fold.:
      // FOLD: 0x25c48c + 284 + 146t
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R10 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R9 BY 1;
      R10 = R10 + R11;                  // 146t
      R12 = 0x25c5a8;                   // 0x25c48c + 284
      R2 = R12 + R10;
      R3 = -4;
      R3 = R2 AND R3;
      I0 = R3;
      R0 = DM(0, I0);
      R3 = 2;
      R3 = R2 AND R3;
      R3 = LSHIFT R3 BY 3;
      R12 = R12 - R12;
      R3 = R12 - R3;
      R0 = LSHIFT R0 BY R3;
      R12 = 0xffff;
      R0 = R0 AND R12;                  // FOLD
      IF EQ JUMP 0x172cf2;              // -> wr_p5_out.
      // g / T = (1 + FOLD x f32(7 / 0x7f00)) x f32(1 / T)
      R12 = R12 - R12;
      F1 = FLOAT R0 BY R12;
      R12 = 0x3961c387;                 // f32(7 / 0x7f00)
      F1 = F1 * F12;
      R12 = 0x3f800000;
      F1 = F1 + F12;
      R12 = 0x406314a0;                 // f32(1 / T)
      F8 = F1 * F12;                    // g / T
      R9 = 0x3f800000;                  // 1.0
      R10 = 24;
      R11 = -29;
      R12 = 0x3e904d1c;                 // T = f32(10^(-11/20))
      R0 = DM(0x2dde88);
      I0 = R0;
      I2 = R0;
      R13 = DM(0x2dde24);
      LCNTR = R13, DO wr_p5_fold_end. UNTIL LCE;
.NOCOMPRESS;
      R4 = DM(I0, M6);
      F1 = F4 * F8;                     // x g / T
      F1 = F1 + F9;                     // v = u + 1
      R1 = TRUNC F1 BY R10;
      R1 = LSHIFT R1 BY 6;              // (v / 4 mod 1) x 2^32
      R1 = ABS R1;
      R1 = LSHIFT R1 BY -1;
      F1 = FLOAT R1 BY R11;             // |w|, 0..2
      F1 = F1 * F12;
      F1 = F1 - F12;                    // |w| T - T
.GLOBAL wr_p5_fold_end.;
wr_p5_fold_end.:
      DM(I2, M6) = F1;
.COMPRESS;

.GLOBAL wr_p5_out.;
wr_p5_out.:
      R0 = DM(0x2e6080);
      R0 = PASS R0;
      IF NE JUMP 0x171000;              // -> wr_sub_ran. (sub.asm)
      JUMP 0x171008;                    // -> wr_sub_skip. (sub.asm)
.wr_p5..end:
      .type wr_p5_npos.,STT_FUNC;
