// formant.asm -- Waverider page 5, TYPE Formant: five resonators in cascade on IIR0
// (dnfw.waverider.formant; owner 2026-10-17).
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC engine inside the DN2 1.11 image and checked
// bit for bit against dnfw.waverider.formant (scripts/sharc_formant_check.py).
//
// The voice runs on IIR0 one voice late (live.render_two's order): page5.asm's way to the sub
// comes to wr_fm_post after FOLD. It first collects the voice IIR0 is filtering (wr_fm_collect:
// wait for ACDONE, then track = e x IO + track, where the sub and the noise have added in).
// Then, for TYPE 3 (Formant) and a block of 32 or less, it computes this voice's cascade
// (wr_fm_coef), copies the block to IO, scales the track by d (P2's dry part), and starts
// IIR0 (legacy, one channel, Save State) on IO in place. The sub, the noise and the next
// voice run while IIR0 works. machine9_live.asm's way out of the loop comes to wr_fm_end,
// which collects the last voice. Clobbers R0-R15, I0-I2; I3, I4 and I5 are not touched.
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
// L1 (byte addresses; IIR0 reads them at 0x28000000 + the address, as word addresses):
//   0x2e7660  the voices' IIR0 coefficients, 16 x 5 biquads x 7 words (140 bytes a voice)
//   0x2e7f20  IO: the block IIR0 filters in place, 32 float32
//   0x2e7fa0  the TCB, 13 words (legacy: CHNPTR, COEF LEN MOD IDX, OUT BASE LEN MOD IDX,
//             IN BASE LEN MOD IDX, CTL2); a run writes its indexes back, so each start
//             writes them again
//   0x2e7fd4  in flight: the voice's track buffer (0: none), e, N, its coefficients, P2
// IIR0's registers at 0x310c4000: CTL1 + 0, DMASTAT + 4, CHNPTR + 0x70.
//
// DDR (byte addresses; only the core reads them, through the DM bus):
//   0x8070ac00  the voices' glide state, 16 x 2 words (the position, 1 once set)
//   0x8070a000  the vowel pairs: for i = 0..3, 20 float32: Fa[5], dF[5], BWa[5], dBW[5]
//   0x8070a200  SHIFTS, 128 float32 (2^(v / 127))
//   0x8070a400  the level table, 33 rows x 9 columns, float32 (formant_levels.json)
//
// wr_fm_coef is all 48 bits (.NOCOMPRESS): a 16-bit short compute with bits 11..7 zero,
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

// page5.asm's way to the sub (wr_p5_out) comes here. From here on selas may use the 16- and
// 32-bit forms, except that every Rn = Rn op Rm here has n of 8 or more: a 16-bit short compute
// with n under 8 and op ADD has bits 11..7 zero, Type 2b's pattern too (see wr_fm_coef). The
// float steps stay 48 bits.
.COMPRESS;
.GLOBAL wr_fm_post.;
wr_fm_post.:
      CALL 0x173ab8;                    // -> wr_fm_collect.
      CALL 0x172caf;                    // -> wr_p5_t146. (R9 = t, R10 = 146t; wr_p5_word keeps both)
      R12 = 0x25c5b0;                   // 0x25c48c + 292: TYPE
      R2 = R12 + R10;
      CALL 0x172cc4;                    // -> wr_p5_word.
      R0 = LSHIFT R0 BY -8;
      R1 = 3;
      COMP(R0, R1);
      IF NE JUMP 0x173aa8;              // -> wr_fm_out. (not the Formant)
      R13 = DM(0x2dde24);               // N
      R1 = 32;
      COMP(R13, R1);
      IF GT JUMP 0x173aa8;              // -> wr_fm_out. (longer than IO)
      R12 = 0x25c5b2;                   // 0x25c48c + 294: P2
      R2 = R12 + R10;
      CALL 0x172cc4;                    // -> wr_p5_word.
      DM(0x2e7fe4) = R0;                // P2, for after the coefficients
      R12 = 0x25c5b4;                   // 0x25c48c + 296: P1
      R2 = R12 + R10;
      CALL 0x172cc4;                    // -> wr_p5_word.
      R5 = PASS R0;
      R12 = 0x25c594;                   // 0x25c48c + 264: AMT
      R2 = R12 + R10;
      CALL 0x172cc4;                    // -> wr_p5_word.
      R4 = PASS R0;
      // a note on this voice: the frame's note mask (offset 34), bit t, as noise.asm reads it
      R0 = DM(0x25c4ac);
      R0 = LSHIFT R0 BY -16;
      R11 = R11 - R11;
      R11 = R11 - R9;
      R0 = LSHIFT R0 BY R11;            // >> t
      R1 = 1;
      R6 = R0 AND R1;
      // the voice's glide state and coefficients
      R8 = LSHIFT R9 BY 3;
      R12 = 0x8070ac00;
      R8 = R8 + R12;
      I1 = R8;
      R8 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 3;
      R8 = R8 + R11;
      R11 = LSHIFT R9 BY 2;
      R8 = R8 + R11;                    // 140 t
      R12 = 0x2e7660;
      R8 = R8 + R12;
      I2 = R8;
      DM(0x2e7fe0) = R8;                // the coefficients, for the TCB
      CALL 0x173800;                    // -> wr_fm_coef.
      // d and e from P2
      R0 = DM(0x2e7fe4);
      R12 = R12 - R12;
.NOCOMPRESS;
      F1 = FLOAT R0 BY R12;
      R12 = 0x38010204;                 // f32(1 / 0x7f00)
      F1 = F1 * F12;
      R12 = 0x3f800000;                 // 1.0
      F1 = MIN(F1, F12);                // d
      F2 = F12 - F1;                    // e
.COMPRESS;
      // IO = the block; the track = d x the block
      R13 = DM(0x2dde24);               // N
      R12 = DM(0x2dde88);
      I0 = R12;
      I2 = R12;
      DM(0x2e7fd4) = R12;               // in flight: this voice's track
      DM(0x2e7fd8) = R2;                // e
      DM(0x2e7fdc) = R13;               // N
      R12 = 0x2e7f20;
      I1 = R12;
      LCNTR = R13, DO wr_fm_in_end. UNTIL LCE;
.NOCOMPRESS;
      R3 = DM(I0, M6);
      DM(I1, M6) = R3;
      F3 = F1 * F3;
.GLOBAL wr_fm_in_end.;
wr_fm_in_end.:
      DM(I2, M6) = R3;
.COMPRESS;
      // the TCB: COEFIDX, OUTIDX, INIDX and CTL2 again (word addresses: 0x28000000 + DM, >> 2)
      R12 = 0x28000000;
      R8 = DM(0x2e7fe0);
      R8 = R8 + R12;
      R8 = LSHIFT R8 BY -2;
      DM(0x2e7fac) = R8;                // COEFIDX (TCB + 3)
      R3 = 0x0a0b9fc8;                  // (0x28000000 + 0x2e7f20) >> 2: IO
      DM(0x2e7fbc) = R3;                // OUTIDX (TCB + 7)
      DM(0x2e7fcc) = R3;                // INIDX (TCB + 11)
      R8 = -1;
      R8 = R8 + R13;
      R8 = LSHIFT R8 BY 14;             // (N - 1) << 14
      R12 = 4;                          // five biquads
      R8 = R8 OR R12;
      DM(0x2e7fd0) = R8;                // CTL2 (TCB + 12)
      // start: CTL1 = 0, read DMASTAT, CHNPTR = TCB + 12, CTL1 = EN | DMAEN | SS
      R12 = 0x310c4000;
      I0 = R12;
      R12 = R12 - R12;
      DM(0, I0) = R12;
      R2 = DM(1, I0);
      R2 = 0x0a0b9ff4;                  // (0x28000000 + 0x2e7fa0) >> 2, + 12
      DM(28, I0) = R2;                  // CHNPTR (+ 0x70)
      R2 = 0x501;                       // EN | DMAEN | SS
      DM(0, I0) = R2;
.GLOBAL wr_fm_out.;
wr_fm_out.:
      R0 = DM(0x2e6000);                // 1 when osc 2 ran: which way to the sub, as page5.asm went
      R0 = PASS R0;
      IF NE JUMP 0x171000;              // -> wr_sub_ran. (sub.asm)
      JUMP 0x171008;                    // -> wr_sub_skip. (sub.asm)

// machine9_live.asm's way out of the loop comes here: the last voice in flight.
.GLOBAL wr_fm_end.;
wr_fm_end.:
      CALL 0x173ab8;                    // -> wr_fm_collect.
      JUMP 0x16ebe6;                    // -> wr_t5v_exit.

// The voice in flight, if any: wait for IIR0's ACDONE (at most 100,000 reads; past that the
// dry part, the sub and the noise stay as they are), CTL1 = 0, then track = e x IO + track.
// Clobbers R0-R3, R8, R11-R13, I0-I2.
.GLOBAL wr_fm_collect.;
wr_fm_collect.:
      R0 = DM(0x2e7fd4);
      R0 = PASS R0;
      IF EQ JUMP 0x173b01;              // -> wr_fm_none.
      R12 = 0x310c4004;                 // DMASTAT
      I0 = R12;
      R3 = 0x40;                        // ACDONE
      R8 = 100000;
      R13 = -1;
.GLOBAL wr_fm_poll.;
wr_fm_poll.:
      R2 = DM(0, I0);
      R11 = R2 AND R3;
      IF NE JUMP 0x173ad9;              // -> wr_fm_done.
      R8 = R8 + R13;
      IF GT JUMP 0x173acb;              // -> wr_fm_poll.
      JUMP 0x173afd;                    // -> wr_fm_clear. (never finished)
.GLOBAL wr_fm_done.;
wr_fm_done.:
      R12 = R12 - R12;
      DM(-1, I0) = R12;                 // CTL1 = 0
      I1 = R0;                          // the track, read
      I2 = R0;                          // and written
      R12 = 0x2e7f20;
      I0 = R12;                         // IO: IIR0's output
      R1 = DM(0x2e7fd8);                // e
      R13 = DM(0x2e7fdc);               // N
      LCNTR = R13, DO wr_fm_mix_end. UNTIL LCE;
.NOCOMPRESS;
      R2 = DM(I0, M6);
      R3 = DM(I1, M6);
      F2 = F1 * F2;
      F2 = F2 + F3;
.GLOBAL wr_fm_mix_end.;
wr_fm_mix_end.:
      DM(I2, M6) = R2;
.COMPRESS;
.GLOBAL wr_fm_clear.;
wr_fm_clear.:
      R12 = R12 - R12;
      DM(0x2e7fd4) = R12;               // nothing in flight
.GLOBAL wr_fm_none.;
wr_fm_none.:
      RTS;
.wr_fm..end:
      .type wr_fm_coef.,STT_FUNC;
