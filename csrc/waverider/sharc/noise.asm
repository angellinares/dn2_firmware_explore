// noise.asm -- Waverider page 3: the noise generator (docs/waverider-pages34.md).
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). Run offline in digikit's SHARC executor inside the DN2 1.11 image
// (scripts/sharc_waverider_noise.py), checked bit for bit against
// dnfw.waverider.live.NoiseVoice; it has never run on a DSP.
//
// Entered from sub.asm, after the sub-oscillator (or instead of it at SUB 0), in place of
// its jump to wr_t5v_next. It reads the track's NOIS, TYPE, COLR and DEC (params 54..57,
// FM Tone's records 231..234) from the frame copy at 0x25c48c, offsets 276, 278, 280, 282
// + 146t. A note on this voice (the frame's note mask, offset 34, bit t) restarts the
// envelope at 1.0, whatever NOIS is. With NOIS 0 it does nothing else. Otherwise, a
// sample at a time:
//   x    xorshift32 (<< 13, >> 17, << 5), w = x as a signed int x 2^-31
//   n    TYPE 0 WHT w; 1 PNK P. Kellet's economy filters (three one-poles plus w x 0.1848,
//        x 0.25); 2 BRN a leaky integrator 0.98 b + 0.15 w; 3 DIG +-0.5 by x's top bit
//   lp   lp + (n - lp) x 0.125, and the tilt n - c x lp, c = (COLR - 64) / 64
//   env  unless DEC is Inf (127): y x env, then env x the decay table's factor
// and adds NOIS/100 x y into the track buffer. Then it goes on to wr_t5v_next.
//
// DM (byte addresses, the free tail of L1 block 1 after the sub's state):
//   0x2e2c00  the decay factor per DEC 0..127, float32 (live.noise_decay_table)
//   0x2e2e00  16 voices x 32 bytes: x, pink b0 b1 b2, brown, lp, env, one spare
//             (the image seeds x, live.noise_seeds; the rest zeros)
//
// The forms sub.asm uses: each TYPE is a DO loop. Clobbers R0-R15, I1, I2; I3 and I5
// (the loop's pointers) are not touched.
//
// PLACEMENT IS FIXED at PM sw 0x171300 (DM byte 0x2e2600): the absolute jumps below are
// written for it, and for sub.asm's, by scripts/sharc_resolve_jumps.py.

.SECTION/PM seg_pmco;

.GLOBAL wr_noise.;
wr_noise.:
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R10 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R9 BY 1;
      R10 = R10 + R11;                  // 146t
      R12 = 0x25c5a0;                   // 0x25c48c + 276: NOIS (param 54)
      R10 = R12 + R10;                  // &NOIS, 2-byte aligned
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
      IF NE JUMP 0x171336;              // -> wr_noise_odd.
      R6 = PASS R3;                     // t even: NOIS low half of word 0, TYPE high
      R7 = LSHIFT R3 BY R0;
      R13 = PASS R4;                    //         COLR low half of word 1, DEC high
      R14 = LSHIFT R4 BY R0;
      JUMP 0x17133c;                    // -> wr_noise_halves.
.GLOBAL wr_noise_odd.;
wr_noise_odd.:
      R6 = LSHIFT R3 BY R0;             // t odd:  NOIS high half of word 0
      R7 = PASS R4;                     //         TYPE low half of word 1, COLR high
      R13 = LSHIFT R4 BY R0;
      R14 = PASS R5;                    //         DEC low half of word 2
.GLOBAL wr_noise_halves.;
wr_noise_halves.:
      R12 = 0xffff;
      R6 = R6 AND R12;                  // NOIS, 0..0x7f00
      R7 = R7 AND R12;                  // TYPE
      R13 = R13 AND R12;                // COLR
      R14 = R14 AND R12;                // DEC
      R3 = DM(0x2e3080);                // FSRC NOIS (fsrc.asm's wr_fs_pre): 1.0, the noise plays at gain 1.0

      // this voice's state, 0x2e2e00 + 32t, in I1 from here on
      R2 = LSHIFT R9 BY 5;
      R12 = 0x2e2e00;
      R2 = R12 + R2;
      I1 = R2;

      // a note on this voice restarts the envelope
      R0 = DM(0x25c4ac);                // the frame's offset 32..35: the note mask high
      R0 = LSHIFT R0 BY -16;
      R1 = R1 - R1;
      R1 = R1 - R9;
      R0 = LSHIFT R0 BY R1;             // >> t
      R1 = 1;
      R0 = R0 AND R1;
      IF EQ JUMP 0x171365;              // -> wr_noise_held. (no note)
      R0 = 0x3f800000;                  // 1.0
      DM(6, I1) = R0;
.GLOBAL wr_noise_held.;
wr_noise_held.:
      R0 = R6 OR R3;
      IF EQ JUMP 0x16eeb3;              // -> wr_t5v_next. (NOIS 0: nothing)

      // the gain, NOIS / 100, as the sub's
      R12 = R12 - R12;
      F6 = FLOAT R6 BY R12;
      R12 = DM(0x2de6c8);               // f32(10^(dB/20) / 25600): the trim's factor for this voice (trim.asm)
      F6 = F6 * F12;
      R3 = PASS R3;
      IF NE R6 = PASS R3;               // FSRC NOIS: gain 1.0
      // TYPE >> 8, at most 3 (DIG)
      R7 = LSHIFT R7 BY -8;
      R12 = 3;
      R7 = MIN(R7, R12);
      // c = (COLR >> 8 - 64) / 64
      R13 = LSHIFT R13 BY -8;
      R12 = 64;
      R13 = R13 - R12;
      R12 = R12 - R12;
      F13 = FLOAT R13 BY R12;
      R12 = 0x3c800000;                 // 1 / 64
      F13 = F13 * F12;
      // DEC >> 8, at most 127; its factor; then R14 = 127 - DEC, 0 at Inf
      R14 = LSHIFT R14 BY -8;
      R12 = 127;
      R14 = MIN(R14, R12);
      R2 = LSHIFT R14 BY 2;
      R12 = 0x2e2c00;
      R2 = R12 + R2;
      I2 = R2;
      R8 = DM(0, I2);                   // F8: the envelope's factor
      R12 = 127;
      R14 = R12 - R14;

      R11 = DM(0, I1);                  // x
      R4 = DM(5, I1);                   // F4: lp
      R5 = DM(6, I1);                   // F5: env

      R2 = DM(0x2dde88);                // the track buffer
      I2 = R2;
      R0 = DM(0x2dde24);                // the dispatch's R9: the block size
      R10 = PASS R0;                    // opt1 O2: the count in R10, which the loop doesn't use
      IF EQ JUMP 0x17154a;              // -> wr_noise_done. (count 0: nothing)
      R15 = -31;                        // w's scale, 2^-31

      // Load plan #3 (2026-10-21): each TYPE is a hardware loop (LCNTR = R10, the count) with no
      // branch in it (until then up to three a sample: TYPE's compare chain, DEC Inf and the back
      // edge). At DEC Inf (R14 = 0) a loop runs with env and its factor at 1.0: y x 1.0 and 1.0 x 1.0
      // are exact, so the output is the same bit for bit, and the envelope as it was is put back
      // after the loop (R9). Each value takes the same operations as before.
      R9 = PASS R5;                     // the envelope as it was
      R14 = PASS R14;
      IF NE JUMP 0x1713bf;              // -> wr_noise_type.
      R5 = 0x3f800000;                  // 1.0
      R8 = 0x3f800000;
.GLOBAL wr_noise_type.;
wr_noise_type.:
      R7 = PASS R7;
      IF EQ JUMP 0x171417;              // -> wr_noise_wht.
      R12 = 1;
      COMP(R7, R12);
      IF EQ JUMP 0x171456;              // -> wr_noise_pink.
      R12 = 2;
      COMP(R7, R12);
      IF EQ JUMP 0x1714ef;              // -> wr_noise_brown.

// DIG: +-0.5 by x's top bit, as x's sign bit on 0.5's pattern (0x3f000000 or 0xbf000000)
.GLOBAL wr_noise_dig.;
wr_noise_dig.:
      LCNTR = R10, DO wr_noise_dig_last. UNTIL LCE;
      R0 = LSHIFT R11 BY 13;
      R11 = R11 XOR R0;
      R0 = LSHIFT R11 BY -17;
      R11 = R11 XOR R0;
      R0 = LSHIFT R11 BY 5;
      R11 = R11 XOR R0;
      R1 = LSHIFT R11 BY -31;
      R1 = LSHIFT R1 BY 31;
      R12 = 0x3f000000;                 // +0.5
      R1 = R1 OR R12;
.NOCOMPRESS;                            // a hardware loop's last 11 instructions are 48-bit (PRM 4-42)
      R3 = DM(0, I2);                   // what the oscillators and the sub wrote
      F2 = F1 - F4;
      R12 = 0x3e000000;                 // 0.125
      F2 = F2 * F12;
      F4 = F4 + F2;                     // lp
      F2 = F13 * F4;
      F1 = F1 - F2;                     // n - c x lp
      F1 = F1 * F5;                     // x env (1.0 at DEC Inf)
      F5 = F5 * F8;                     // env x its factor (1.0 x 1.0 at DEC Inf)
      F1 = F6 * F1;                     // gain x y
      F1 = F3 + F1;
.GLOBAL wr_noise_dig_last.;
wr_noise_dig_last.:
      DM(I2, M6) = F1;
.COMPRESS;
      JUMP 0x171546;                    // -> wr_noise_end.

// WHT: n = w
.GLOBAL wr_noise_wht.;
wr_noise_wht.:
      LCNTR = R10, DO wr_noise_wht_last. UNTIL LCE;
      R0 = LSHIFT R11 BY 13;
      R11 = R11 XOR R0;
      R0 = LSHIFT R11 BY -17;
      R11 = R11 XOR R0;
      R0 = LSHIFT R11 BY 5;
      R11 = R11 XOR R0;
      F1 = FLOAT R11 BY R15;            // w, -1 .. 1 (opt1 O3: into F1, not F0: anomaly 20000072)
.NOCOMPRESS;                            // a hardware loop's last 11 instructions are 48-bit (PRM 4-42)
      R3 = DM(0, I2);                   // what the oscillators and the sub wrote
      F2 = F1 - F4;
      R12 = 0x3e000000;                 // 0.125
      F2 = F2 * F12;
      F4 = F4 + F2;                     // lp
      F2 = F13 * F4;
      F1 = F1 - F2;                     // n - c x lp
      F1 = F1 * F5;                     // x env (1.0 at DEC Inf)
      F5 = F5 * F8;                     // env x its factor (1.0 x 1.0 at DEC Inf)
      F1 = F6 * F1;                     // gain x y
      F1 = F3 + F1;
.GLOBAL wr_noise_wht_last.;
wr_noise_wht_last.:
      DM(I2, M6) = F1;
.COMPRESS;
      JUMP 0x171546;                    // -> wr_noise_end.

// PNK: P. Kellet's economy filters
.GLOBAL wr_noise_pink.;
wr_noise_pink.:
      LCNTR = R10, DO wr_noise_pink_last. UNTIL LCE;
      R0 = LSHIFT R11 BY 13;
      R11 = R11 XOR R0;
      R0 = LSHIFT R11 BY -17;
      R11 = R11 XOR R0;
      R0 = LSHIFT R11 BY 5;
      R11 = R11 XOR R0;
      F1 = FLOAT R11 BY R15;            // w, -1 .. 1 (opt1 O3: into F1, not F0: anomaly 20000072)
      R0 = PASS R1;                     // w in R0 too, as before
      R2 = DM(1, I1);
      R12 = 0x3f7f65fe;                 // 0.99765
      F2 = F2 * F12;
      R12 = 0x3dcad8a1;                 // 0.0990460
      F3 = F0 * F12;
      F2 = F2 + F3;
      DM(1, I1) = R2;
      R1 = PASS R2;                     // b0
      R2 = DM(2, I1);
      R12 = 0x3f76872b;                 // 0.96300
      F2 = F2 * F12;
      R12 = 0x3e97d0ff;                 // 0.2965164
      F3 = F0 * F12;
      F2 = F2 + F3;
      DM(2, I1) = R2;
      F1 = F1 + F2;                     // b0 + b1
      R2 = DM(3, I1);
      R12 = 0x3f11eb85;                 // 0.57000
      F2 = F2 * F12;
      R12 = 0x3f86be97;                 // 1.0526913
      F3 = F0 * F12;
      F2 = F2 + F3;
      DM(3, I1) = R2;
      F1 = F1 + F2;                     // + b2
      R12 = 0x3e3d3c36;                 // 0.1848
      F3 = F0 * F12;
      F1 = F1 + F3;
      R12 = 0x3e800000;                 // 0.25
      F1 = F1 * F12;
.NOCOMPRESS;                            // a hardware loop's last 11 instructions are 48-bit (PRM 4-42)
      R3 = DM(0, I2);                   // what the oscillators and the sub wrote
      F2 = F1 - F4;
      R12 = 0x3e000000;                 // 0.125
      F2 = F2 * F12;
      F4 = F4 + F2;                     // lp
      F2 = F13 * F4;
      F1 = F1 - F2;                     // n - c x lp
      F1 = F1 * F5;                     // x env (1.0 at DEC Inf)
      F5 = F5 * F8;                     // env x its factor (1.0 x 1.0 at DEC Inf)
      F1 = F6 * F1;                     // gain x y
      F1 = F3 + F1;
.GLOBAL wr_noise_pink_last.;
wr_noise_pink_last.:
      DM(I2, M6) = F1;
.COMPRESS;
      JUMP 0x171546;                    // -> wr_noise_end.

// BRN: a leaky integrator
.GLOBAL wr_noise_brown.;
wr_noise_brown.:
      LCNTR = R10, DO wr_noise_brown_last. UNTIL LCE;
      R0 = LSHIFT R11 BY 13;
      R11 = R11 XOR R0;
      R0 = LSHIFT R11 BY -17;
      R11 = R11 XOR R0;
      R0 = LSHIFT R11 BY 5;
      R11 = R11 XOR R0;
      F1 = FLOAT R11 BY R15;            // w, -1 .. 1 (opt1 O3: into F1, not F0: anomaly 20000072)
      R0 = PASS R1;                     // w in R0 too, as before
      R2 = DM(4, I1);
      R12 = 0x3f7ae148;                 // 0.98
      F2 = F2 * F12;
      R12 = 0x3e19999a;                 // 0.15
      F3 = F0 * F12;
      F2 = F2 + F3;
      DM(4, I1) = R2;
      R1 = PASS R2;
.NOCOMPRESS;                            // a hardware loop's last 11 instructions are 48-bit (PRM 4-42)
      R3 = DM(0, I2);                   // what the oscillators and the sub wrote
      F2 = F1 - F4;
      R12 = 0x3e000000;                 // 0.125
      F2 = F2 * F12;
      F4 = F4 + F2;                     // lp
      F2 = F13 * F4;
      F1 = F1 - F2;                     // n - c x lp
      F1 = F1 * F5;                     // x env (1.0 at DEC Inf)
      F5 = F5 * F8;                     // env x its factor (1.0 x 1.0 at DEC Inf)
      F1 = F6 * F1;                     // gain x y
      F1 = F3 + F1;
.GLOBAL wr_noise_brown_last.;
wr_noise_brown_last.:
      DM(I2, M6) = F1;
.COMPRESS;

.GLOBAL wr_noise_end.;
wr_noise_end.:
      R14 = PASS R14;
      IF EQ R5 = PASS R9;               // DEC Inf: the envelope as it was

.GLOBAL wr_noise_done.;
wr_noise_done.:
      DM(0, I1) = R11;                  // x, lp, env for the next block
      DM(5, I1) = R4;
      DM(6, I1) = R5;
      R0 = DM(0x2e3080);
      R0 = PASS R0;
      IF NE RTS;                        // FSRC NOIS: back to fsrc.asm's wr_fs_pre
      JUMP 0x16eeb3;                    // -> wr_t5v_next.
.wr_noise..end:
      .type wr_noise.,STT_FUNC;
