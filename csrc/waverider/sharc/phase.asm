// phase.asm -- Waverider page 5's WARP and FM: the two readers, reading each sample's phase
// from PH (DM 0x2e6280, page5.asm's wr_p5_phase writes it) in place of the running phase.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC executor inside the DN2 1.11 image and checked
// bit for bit against dnfw.waverider.live (read_phases; scripts/sharc_waverider_shape.py).
//
// wr_ph_read: reader_m9.asm's wr_render5 jumps here, every reader call. With the PH flag
// (DM 0x2e6014) at 0 it goes on to wr_miph2, as before: three instructions. With it at 1:
//   - wr_ph_miph2 is reader_miph2.asm's reader with two changes: the level is chosen by the
//     increment at DM 0x2e6018 (WARP and FM read faster than inc), and the loop's last
//     instruction loads the next sample's phase from PH, where the reader adds inc.
//   - wr_ph_plain is reader_m9.asm's wr5_plain (a table without the mip flag) with the same
//     load in place of its add.
// After N samples the phase is PH[N], the running phase that wr_p5_phase stored there, so
// the reader block keeps what it kept before. DCLK's second call (the old settings, from the
// same phase) reads the same PH.
//
// Each loop reads PH through I3, kept at DM 0x2e601c and put back after the loop (I3 is the
// type-5 loop's pointer). Clobbers what the readers do (R0-R15, I0, I1, I2, I4, ASTAT).
//
// PLACEMENT IS FIXED at PM sw 0x173480 (DM 0x2e6900): the absolute jumps below are written
// for it by scripts/sharc_resolve_jumps.py.

.SECTION/PM seg_pmco;

.GLOBAL wr_ph_read.;
wr_ph_read.:
      R0 = DM(0x2e6014);
      R0 = PASS R0;
      IF EQ JUMP 0x171a00;              // -> wr_miph2. (no WARP, no FM: the reader as before)
.GLOBAL wr_ph_miph2.;
wr_ph_miph2.:
      I4 = R4;                          // I4 -> parameter block
      R8 = DM(0, I4);                   // table (a byte address; bit 0: mip-mapped)
      R9 = DM(1, I4);                   // phase (kept when N is 0)
      R10 = DM(0x2e6018);               // the level's increment
      R11 = DM(3, I4);                  // pos, Q16
      R12 = DM(4, I4);                  // N
      R0 = DM(5, I4);
      I2 = R0;                          // out

      // the level, k in R13: 0 for a plain table
      R13 = R13 - R13;
      R1 = 1;
      R2 = R8 AND R1;
      IF EQ JUMP 0x1735ff;                   // -> wr_ph_plain. (no flag: opt2's reader; R4 is untouched)
      R8 = R8 - R1;                     // the table's header (dnfw.waverider.table3)
      I1 = R8;
      R14 = DM(1, I1);                  // S, the position's scale (float32)
      R15 = DM(2, I1);                  // F - 1, the last frame
      R2 = DM(3, I1);                   // K - 1: the thresholds to test
      R3 = 0x10;
      R3 = R8 + R3;
      I0 = R3;                          // T[0]
      R3 = 1;
      R2 = PASS R2;
      IF EQ JUMP 0x1734c0;                   // -> wr_ph_level. (one level)
.GLOBAL wr_ph_test.;
wr_ph_test.:
      R1 = DM(I0, M6);                  // T[k]: this level while the increment < T[k]
      COMPU(R10, R1);
      IF LT JUMP 0x1734c0;                   // -> wr_ph_level.
      R13 = R13 + R3;
      R2 = R2 - R3;
      IF NE JUMP 0x1734b5;                   // -> wr_ph_test.

.GLOBAL wr_ph_level.;
wr_ph_level.:
      R3 = LSHIFT R13 BY 5;             // k * 32 bytes: its record
      R4 = 0x50;
      R3 = R4 + R3;
      R3 = R8 + R3;
      I1 = R3;
      R4 = DM(0, I1);                   // the level's byte offset in the table
      R8 = R8 + R4;
      R5 = DM(1, I1);                   // b + 1: a row is 2^(b+1) + 6 bytes

      // pos = trunc(POS x S): POS is 0 .. 15 frames, the table F (table3.position)
      F11 = FLOAT R11;
      F11 = F11 * F14;
      R11 = TRUNC F11;

      // Rows: f0 = pos >> 16, f1 = min(f0 + 1, F - 1); row f = table + f * 2^(b+1) + f * 6
      R0 = LSHIFT R11 BY -16;
      R2 = 1;
      R1 = R0 + R2;
      R1 = MIN(R1, R15);
      R2 = LSHIFT R0 BY R5;
      R3 = LSHIFT R0 BY 2;
      R2 = R3 + R2;
      R3 = LSHIFT R0 BY 1;
      R2 = R3 + R2;
      R6 = R8 + R2;                     // row a (frame f0)
      R2 = LSHIFT R1 BY R5;
      R3 = LSHIFT R1 BY 2;
      R2 = R3 + R2;
      R3 = LSHIFT R1 BY 1;
      R2 = R3 + R2;
      R7 = R8 + R2;                     // row b (frame f1)
      DM(6, I4) = R6;
      DM(7, I4) = R7;

      // Frame fraction ff = (pos & 0xffff) * 2^-16, exact in float32, kept in DM 0x2e3204
      R3 = 0xffff;
      R3 = R11 AND R3;
      R2 = -16;
      F3 = FLOAT R3 BY R2;
      DM(0x2e3204) = R3;

      R13 = DM(5, I1);                  // the sample index's shift: i = phase >> (32 - b)
      R14 = DM(4, I1);                  // sample fraction mask
      R15 = DM(6, I1);                  // half the sample fraction's scale
      R11 = PASS R7;                    // row b
      R8 = -15;                         // int16 -> float full scale, 2^-15
      R12 = PASS R12;
      IF EQ JUMP 0x1735f7;                   // -> wr_ph_done. (count 0: write nothing)
      R0 = PASS R12;                    // the count, for LCNTR
      R12 = PASS R6;                    // row a
      DM(0x2e601c) = I3;
      R1 = 0x2e6280;
      I3 = R1;                          // PH
      R9 = DM(I3, M6);                  // PH[0]
      LCNTR = R0, DO wr_ph_last. UNTIL LCE;   // E2-active (the mix branch is in the body)

.GLOBAL wr_ph_loop.;
wr_ph_loop.:
      R0 = R9 AND R14;
      F10 = FLOAT R0 BY R15;            // hfr, half the sample fraction (exact)
      R0 = LSHIFT R9 BY R13;            // i
      R0 = LSHIFT R0 BY 1;              // tap i-1's byte offset in a guarded row
      R1 = R12 + R0;                    // row a, tap i-1
      R0 = R11 + R0;                    // row b, tap i-1
      I0 = R1;
      I1 = R0;
      R4 = DM(I0, M6) (SWSE);           // a[i-1]
      R5 = DM(I0, M6) (SWSE);           // a[i]
      R6 = DM(I0, M6) (SWSE);           // a[i+1]
      R7 = DM(I0, M6) (SWSE);           // a[i+2]
      R0 = DM(I1, M6) (SWSE);           // b[i-1]
      R1 = DM(I1, M6) (SWSE);           // b[i]
      R2 = DM(I1, M6) (SWSE);           // b[i+1]
      R3 = DM(I1, M6) (SWSE);           // b[i+2]
      F4 = FLOAT R4 BY R8;
      F5 = FLOAT R5 BY R8;
      F6 = FLOAT R6 BY R8;
      F7 = FLOAT R7 BY R8;
      F0 = FLOAT R0 BY R8;
      F1 = FLOAT R1 BY R8;
      F2 = FLOAT R2 BY R8;
      F3 = FLOAT R3 BY R8;
      R8 = DM(0x2e3204);                // ff

      // the taps between the frames: t = a + ff * (b - a)
      F0 = F0 - F4;
      F0 = F8 * F0;
      F4 = F4 + F0;                     // ym
      F1 = F1 - F5;
      F1 = F8 * F1;
      F5 = F5 + F1;                     // y0
      F2 = F2 - F6;
      F2 = F8 * F2;
      F6 = F6 + F2;                     // y1
      F3 = F3 - F7;
      F3 = F8 * F3;
      F7 = F7 + F3;                     // y2
      R8 = -15;

      // one Catmull-Rom on the blend, render.hermite's order
      F0 = F5 - F6;                     // t = y0 - y1
      F1 = F0 + F0;
      F0 = F1 + F0;                     // 3t
      F1 = F7 - F4;                     // y2 - ym
      F0 = F0 + F1;                     // c3
      F1 = F6 - F4;                     // c1 = y1 - ym
      F2 = F4 - F5;                     // a = ym - y0
      F2 = F2 + F2;
      F6 = F6 - F5;                     // b = y1 - y0
      F6 = F6 + F6;
      F6 = F6 + F6;
      F2 = F2 + F6;
      F7 = F7 - F5;                     // d = y2 - y0
      F2 = F2 - F7;                     // c2
      F4 = F10 + F10;                   // fr
      F0 = F0 * F4;
      F0 = F0 + F2;
      F0 = F0 * F4;
      F0 = F0 + F1;
.NOCOMPRESS;                            // a hardware loop's last 11 instructions are 48-bit (PRM 4-42)
      F0 = F0 * F10;
      F0 = F0 + F5;                     // y
      R1 = DM(0x2de6c0);                // the gain, LEV / 100
      F0 = F1 * F0;                     // y * gain
      // osc 2 adds into the buffer osc 1 wrote (DM 0x2de6c4 = 1)
      R1 = DM(0x2de6c4);
      R1 = PASS R1;
      IF EQ JUMP 0x1735eb;                   // -> wr_ph_store.
      R2 = DM(0, I2);                   // what osc 1 wrote
      F0 = F0 + F2;
.GLOBAL wr_ph_store.;
wr_ph_store.:
      DM(I2, M6) = F0;
.GLOBAL wr_ph_last.;
wr_ph_last.:
      R9 = DM(I3, M6);                  // the next sample's phase (PH[N] after the last)
.COMPRESS;
      I3 = DM(0x2e601c);
      R0 = R0 - R0;
      DM(4, I4) = R0;                   // 0: the count word as the software loop left it

.GLOBAL wr_ph_done.;
wr_ph_done.:
      I12 = DM(M7, I6);
      DM(1, I4) = R9;                   // phase, for the next block
      JUMP (M14, I12) (DB);
      NOP;
      RFRAME;

// reader_m9.asm's wr5_plain (opt2's linear reader, for a table without the mip flag), with
// the phase from PH.
.GLOBAL wr_ph_plain.;
wr_ph_plain.:
      I4 = R4;                          // I4 -> parameter block
      R8 = DM(0, I4);                   // table (a byte address)
      R9 = DM(1, I4);                   // phase (kept when N is 0)
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
      IF EQ JUMP 0x1735f7;                   // -> wr_ph_done. (count 0: write nothing)
      R0 = PASS R12;                    // the count, for LCNTR
      R12 = -16;
      DM(0x2e601c) = I3;
      R1 = 0x2e6280;
      I3 = R1;                          // PH
      R9 = DM(I3, M6);                  // PH[0]
      LCNTR = R0, DO wr_ph_plast. UNTIL LCE;   // E2-active (the mix branch is in the body)

.GLOBAL wr_ph_ploop.;
wr_ph_ploop.:
      R0 = LSHIFT R9 BY -24;            // w0 = k >> 1
      R0 = LSHIFT R0 BY 2;              // its byte offset in a row
      R1 = R9 + R13, R2 = DM(6, I4);    // with frame f0's row
      R1 = LSHIFT R1 BY -24;            // w1 = (k + 1) >> 1, mod 256
      R1 = LSHIFT R1 BY 2;
      R4 = R2 + R0;                     // frame f0, word w0's address
      R5 = R2 + R1, R2 = DM(7, I4);     // frame f0, word w1's; with frame f1's row (the add reads the old R2)
      I0 = R4;
      I1 = R5;
      R6 = R2 + R0;                     // frame f1, word w0's address
      R7 = R2 + R1;                     // frame f1, word w1's
      R2 = 16;
      R3 = LSHIFT R9 BY -19;
      R3 = R3 AND R2;                   // shB = 16 * (k & 1)
      R2 = R2 - R3, R4 = DM(0, I0);     // shA = 16 - shB; with frame f0, word w0
      R4 = LSHIFT R4 BY R2, R5 = DM(0, I1);   // with frame f0, word w1
      I0 = R6;
      I1 = R7;
      R4 = ASHIFT R4 BY R12;            // s00 = sample k
      R5 = LSHIFT R5 BY R3;
      R5 = ASHIFT R5 BY R12;            // s01 = sample k + 1
      F4 = FLOAT R4 BY R8, R6 = DM(0, I0);    // with frame f1, word w0
      F5 = FLOAT R5 BY R8, R7 = DM(0, I1);    // with frame f1, word w1
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
.NOCOMPRESS;                            // a hardware loop's last 11 instructions are 48-bit (PRM 4-42)
      F6 = F6 - F4;
      F6 = F11 * F6;
      F4 = F4 + F6;                     // y = a + ff * (b - a)
      R0 = DM(0x2de6c0);                // the gain, LEV / 100
      F4 = F0 * F4;                     // y * gain
      R0 = DM(0x2de6c4);
      R0 = PASS R0;
      IF EQ JUMP 0x1736d8;                   // -> wr_ph_pstore.
      R1 = DM(0, I2);                   // what osc 1 wrote
      F4 = F4 + F1;
.GLOBAL wr_ph_pstore.;
wr_ph_pstore.:
      DM(I2, M6) = F4;
.GLOBAL wr_ph_plast.;
wr_ph_plast.:
      R9 = DM(I3, M6);                  // the next sample's phase (PH[N] after the last)
.COMPRESS;
      I3 = DM(0x2e601c);
      R0 = R0 - R0;
      DM(4, I4) = R0;                   // 0: the count word as the software loop left it
      JUMP 0x1735f7;                         // -> wr_ph_done.
.wr_ph..end:
      .type wr_ph_read.,STT_FUNC;
