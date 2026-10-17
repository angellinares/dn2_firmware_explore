// formant.asm -- Waverider page 5, TYPE Formant: five resonators in cascade on IIR0
// (dnfw.waverider.formant; owner 2026-10-17).
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC engine inside the DN2 1.11 image and checked
// bit for bit against dnfw.waverider.formant (scripts/sharc_formant_check.py).
//
// wr_fm_coef: one voice's cascade for this block, in formant.leveled's float32 order.
//   In:  R4 = AMT's word (the vowel), R5 = P1's word (the shift), R6 = 1 on a note, else 0,
//        I1 = the voice's state (word 0 the glided position, float32; word 1: 1 once set),
//        I2 = the voice's IIR0 coefficients, 5 biquads of 7 words (A0, A1, B1, A2, B2, s1, s2).
//   Out: the position glided (formant.glide), words 0..4 of each biquad written, the states
//        (words 5 and 6) left as IIR0 saved them. Clobbers R0-R15, I0; I3, I4 and I5 are
//        not touched. Every float result feeds a two-operand compute or a store (anomaly
//        20000072), and F0 is never a float result.
//
// The steps, each rounded to float32:
//   target = MIN(FLOAT AMT x f32(4 / 0x7f00), 4);  p = target on a note or the first block,
//            else MIN(MAX(target, last - 0.125), last + 0.125)
//   v = MIN(P1 >> 8, 127), shift = SHIFTS[v];  i = MIN(TRUNC p, 3), f = p - i
//   per formant k: F = MIN((Fa + dF f) x shift, 21600), BW = BWa + dBW f
//     x = BW x f32(pi / 48000);  r = ((( -1/6 x + 0.5) x - 1) x + 1);  C = 0 - r r
//     u = (F x f32(2 pi / 48000))^2;  c = COS8, then c = c u + COSk for k = 7..0
//     B = (r + r) c;  A0 = (1 - B) - C
//   level: pj = 8 p, j = MIN(TRUNC pj, 31), fp = pj - j, k = v >> 4, fs = (v AND 15) x 0.0625
//     l0 = L[j][k] + (L[j+1][k] - L[j][k]) fp, l1 the same in column k + 1,
//     level = l0 + (l1 - l0) fs;  the first biquad's A0 = A0 x level
//
// DDR (byte addresses; only the core reads them, through the DM bus):
//   0x8070a000  the vowel pairs: for i = 0..3, 20 float32: Fa[5], dF[5], BWa[5], dBW[5]
//   0x8070a200  SHIFTS, 128 float32 (2^(v / 127))
//   0x8070a400  the level table, 33 rows x 9 columns, float32 (formant_levels.json)
//
// Every instruction is 48 bits (.NOCOMPRESS): a 16-bit short compute with bits 11..7 zero,
// such as R2 = R2 + R3 (0xc023), has the bit pattern of a 32-bit Type 2b too, and digikit's
// executor read 0xc023 0xc026 as one 32-bit instruction (2026-10-17).
//
// PLACEMENT IS FIXED at PM sw 0x173800 (DM 0x2e7000): the absolute jumps below are written
// for it by scripts/sharc_resolve_jumps.py.

.SECTION/PM seg_pmco;
.NOCOMPRESS;

.GLOBAL wr_fm_coef.;
wr_fm_coef.:
      // the target position
      R12 = 0xffff;
      R4 = R4 AND R12;
      R12 = R12 - R12;
      F1 = FLOAT R4 BY R12;
      R12 = 0x39010204;                 // f32(4 / 0x7f00)
      F1 = F1 * F12;
      R12 = 0x40800000;                 // 4.0
      F1 = MIN(F1, F12);                // target
      // the glide
      R2 = DM(1, I1);                   // 1 once the position is set
      R2 = PASS R2;
      IF EQ JUMP 0x173839;              // -> wr_fm_take.
      R6 = PASS R6;
      IF NE JUMP 0x173839;              // -> wr_fm_take. (a note: at once)
      R2 = DM(0, I1);                   // last
      R12 = 0x3e000000;                 // 0.125
      F3 = F2 - F12;
      F1 = MAX(F1, F3);
      F3 = F2 + F12;
      F1 = MIN(F1, F3);
.GLOBAL wr_fm_take.;
wr_fm_take.:
      DM(0, I1) = R1;                   // p
      R2 = 1;
      DM(1, I1) = R2;
      // P1: v and the shift
      R12 = 0xffff;
      R5 = R5 AND R12;
      R11 = LSHIFT R5 BY -8;
      R12 = 127;
      R11 = MIN(R11, R12);              // v
      R2 = LSHIFT R11 BY 2;
      R12 = 0x8070a200;                 // SHIFTS
      R2 = R2 + R12;
      I0 = R2;
      R13 = DM(0, I0);                  // shift
      // the vowel pair: i and f
      R12 = R12 - R12;
      R8 = TRUNC F1 BY R12;
      R12 = 3;
      R8 = MIN(R8, R12);                // i
      R12 = R12 - R12;
      F9 = FLOAT R8 BY R12;
      F9 = F1 - F9;                     // f
      R2 = LSHIFT R8 BY 6;
      R3 = LSHIFT R8 BY 4;
      R2 = R2 + R3;                     // 80 i: the pair's 20 floats
      R12 = 0x8070a000;
      R2 = R2 + R12;
      I0 = R2;
      R10 = 28;                         // a biquad's 7 words, in bytes
      LCNTR = 5, DO wr_fm_k_end. UNTIL LCE;
      // F and BW
      R2 = DM(5, I0);                   // dF
      F2 = F2 * F9;
      R3 = DM(0, I0);                   // Fa
      F2 = F3 + F2;
      F2 = F2 * F13;                    // x shift
      R12 = 0x46a8c000;                 // 21600.0, 0.45 x the rate
      F2 = MIN(F2, F12);                // F
      R3 = DM(15, I0);                  // dBW
      F3 = F3 * F9;
      R4 = DM(10, I0);                  // BWa
      F3 = F4 + F3;                     // BW
      R12 = 0x3889421e;                 // f32(pi / 48000)
      F3 = F3 * F12;                    // x
      // r = exp(-x): 1 - x + x^2/2 - x^3/6
      R4 = 0xbe2aaaab;                  // f32(-1/6)
      F4 = F4 * F3;
      R12 = 0x3f000000;                 // 0.5
      F4 = F4 + F12;
      F4 = F4 * F3;
      R12 = 0x3f800000;                 // 1.0
      F4 = F4 - F12;
      F4 = F4 * F3;
      F4 = F4 + F12;                    // r
      F5 = F4 * F4;
      R6 = R6 - R6;                     // 0.0
      F5 = F6 - F5;                     // C = -r r
      // cos(w), w = F x 2 pi / 48000: Horner in u = w^2
      R12 = 0x3909421e;                 // f32(2 pi / 48000)
      F2 = F2 * F12;                    // w
      F2 = F2 * F2;                     // u
      R7 = 0x29573f9f;                 // COS_TERMS[8], 1 / 16!
      R12 = 0xad49cba5;                 // COS_TERMS[7], -1 / 14!
      F7 = F7 * F2;
      F7 = F7 + F12;
      R12 = 0x310f76c7;                 // COS_TERMS[6], 1 / 12!
      F7 = F7 * F2;
      F7 = F7 + F12;
      R12 = 0xb493f27e;                 // COS_TERMS[5], -1 / 10!
      F7 = F7 * F2;
      F7 = F7 + F12;
      R12 = 0x37d00d01;                 // COS_TERMS[4], 1 / 8!
      F7 = F7 * F2;
      F7 = F7 + F12;
      R12 = 0xbab60b61;                 // COS_TERMS[3], -1 / 6!
      F7 = F7 * F2;
      F7 = F7 + F12;
      R12 = 0x3d2aaaab;                 // COS_TERMS[2], 1 / 4!
      F7 = F7 * F2;
      F7 = F7 + F12;
      R12 = 0xbf000000;                 // -0.5
      F7 = F7 * F2;
      F7 = F7 + F12;
      R12 = 0x3f800000;                 // 1.0
      F7 = F7 * F2;
      F7 = F7 + F12;                    // cos(w)
      // B and A0
      F4 = F4 + F4;                     // r + r
      F4 = F4 * F7;                     // B
      F6 = F12 - F4;                    // 1 - B
      F6 = F6 - F5;                     // A0
      DM(0, I2) = R6;
      R12 = R12 - R12;
      DM(1, I2) = R12;                  // A1 = 0
      DM(2, I2) = R4;                   // B1 = B
      DM(3, I2) = R12;                  // A2 = 0
      DM(4, I2) = R5;                   // B2 = C
      R2 = I2;
      R2 = R2 + R10;
      I2 = R2;                          // the next biquad
.GLOBAL wr_fm_k_end.;
wr_fm_k_end.:
      R2 = DM(I0, M6);                  // the next formant's column
      // the level, bilinear on the table
      R12 = 0x41000000;                 // 8.0
      F2 = F1 * F12;                    // pj
      R12 = R12 - R12;
      R3 = TRUNC F2 BY R12;
      R12 = 31;
      R3 = MIN(R3, R12);                // j
      R12 = R12 - R12;
      F4 = FLOAT R3 BY R12;
      F4 = F2 - F4;                     // fp
      R6 = LSHIFT R11 BY -4;            // k
      R7 = 15;
      R7 = R11 AND R7;
      F7 = FLOAT R7 BY R12;
      R12 = 0x3d800000;                 // 0.0625
      F7 = F7 * F12;                    // fs
      R2 = LSHIFT R3 BY 3;
      R2 = R2 + R3;                     // 9 j
      R2 = R2 + R6;
      R2 = LSHIFT R2 BY 2;
      R12 = 0x8070a400;                 // the level table
      R2 = R2 + R12;
      I0 = R2;
      R2 = DM(0, I0);                   // L[j][k]
      R3 = DM(9, I0);                   // L[j+1][k]
      R5 = DM(1, I0);                   // L[j][k+1]
      R6 = DM(10, I0);                  // L[j+1][k+1]
      F3 = F3 - F2;
      F3 = F3 * F4;
      F2 = F2 + F3;                     // l0
      F6 = F6 - F5;
      F6 = F6 * F4;
      F5 = F5 + F6;                     // l1
      F5 = F5 - F2;
      F5 = F5 * F7;
      F2 = F2 + F5;                     // the level
      R3 = DM(-35, I2);                 // the first biquad's A0
      F3 = F3 * F2;
      DM(-35, I2) = R3;
      RTS;
.wr_fm..end:
      .type wr_fm_coef.,STT_FUNC;
