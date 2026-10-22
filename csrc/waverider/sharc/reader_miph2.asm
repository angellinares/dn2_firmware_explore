// reader_miph2.asm -- reader_miph.asm's Hermite (Catmull-Rom) reader, made cheaper
// (owner, 2026-10-08: "let's build it and see"). dnfw.waverider.render's "hermite2" is
// the contract, in its operation order.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). Loads at the same address as reader_mip.asm (PM sw 0x171a00); a build
// carries one reader (dnfw.waverider.mip.INTERP).
//
// What changes against reader_miph.asm, which spent ~96 of its ~160 instructions a sample
// fetching its eight taps (an address, the odd/even half of a packed word, two shifts, a
// FLOAT each):
//
// - **16-bit loads.** The tables are in DDR, which the DAGs address by byte, so a load can
//   take one int16 sign-extended: `R4 = DM(I0, M6) (SWSE)`, and the post-modify by M6 = 1
//   is scaled by the access to the next int16 (PRM 6-6, "Enhanced Modify Instruction for
//   Address Scaling"). A row's four taps are four loads from one address.
// - **Guarded rows.** Each stored row is [its last sample, the frame, its first two]
//   (dnfw.waverider.mip.row_points), so taps i-1 .. i+2 never wrap: tap i-1 is at byte
//   2i of the row. A row is 2^(b+1) + 6 bytes (the level record's word 1, plus the guards).
// - **One cubic.** The four taps are blended between the frames first, t = a + ff (b - a),
//   then one Catmull-Rom on the blend: the same curve in exact arithmetic (it is linear in
//   its samples), half the cubics.
// - **A plain table** (no flag: every pool table until stage 3) has no levels and no
//   guards, so it goes to opt2's reader (reader_m9.asm's wr5_plain), which plays it as
//   before, bit for bit. Only R4 matters there; this entry has not changed it.
// - **The 28 kHz limit** (dnfw.waverider.mip.LIMITS): T[k] = ceil(28 kHz / top(k)) in
//   phase units, so a level keeps harmonics to 28 kHz; those past 24 kHz fold back above
//   20 kHz.
//
// Registers in the loop: R8 ff (load plan #2, 2026-10-21: the taps are floated without their
// 2^-15 full scale, which DM 0x2e3204's gain carries; until then R8 was -15 and ff was read
// each sample), R9 phase, R10 hfr, R11 row b, R12 row a, R13 the sample index's shift
// (-(32 - b)), R14 the fraction mask, R15 half the fraction's scale; R0-R7 the taps and
// scratch. An integer add whose first operand is its own R0-R7 destination is written the
// other way round (runner gap G5, as reader_m5.asm explains).
//
// Clobbers R0-R15, I0, I1, I2, I4, ASTAT, as reader_mip.asm. PLACEMENT IS FIXED at PM sw
// 0x171a00 (L1 block 1, byte 0x2e3400).

.SECTION/PM seg_pmco;

.GLOBAL wr_miph2.;
wr_miph2.:
      I4 = R4;                          // I4 -> parameter block
      R8 = DM(0, I4);                   // table (a byte address; bit 0: mip-mapped)
      R9 = DM(1, I4);                   // phase
      R10 = DM(2, I4);                  // inc
      R11 = DM(3, I4);                  // pos, Q16
      R12 = DM(4, I4);                  // N
      R0 = DM(5, I4);
      I2 = R0;                          // out

      // the level, k in R13: 0 for a plain table
      R13 = R13 - R13;
      R1 = 1;
      R2 = R8 AND R1;
      IF EQ JUMP 0x16eb03;              // -> wr5_plain. (no flag: opt2's reader, reader_m9.asm; R4 is untouched)
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
      IF EQ JUMP 0x171a38;              // -> wr_miph2_level. (one level)
.GLOBAL wr_miph2_test.;
wr_miph2_test.:
      R1 = DM(I0, M6);                  // T[k]: this level while inc < T[k]
      COMPU(R10, R1);
      IF LT JUMP 0x171a38;              // -> wr_miph2_level.
      R13 = R13 + R3;
      R2 = R2 - R3;
      IF NE JUMP 0x171a2d;              // -> wr_miph2_test.

.GLOBAL wr_miph2_level.;
wr_miph2_level.:
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

      // Frame fraction ff = (pos & 0xffff) * 2^-16, exact in float32
      R3 = 0xffff;
      R3 = R11 AND R3;
      R2 = -16;
      F3 = FLOAT R3 BY R2;
      // #2: ff stays in R8 for the loop, and DM 0x2e3204 holds the gain x 2^-15 (the taps' full scale)
      R1 = DM(0x2de6c0);                // the gain, LEV / 100
      R2 = 0x38000000;                  // 2^-15
      F1 = F1 * F2;
      DM(0x2e3204) = R1;

      R13 = DM(5, I1);                  // the sample index's shift: i = phase >> (32 - b)
      R14 = DM(4, I1);                  // sample fraction mask
      R15 = DM(6, I1);                  // half the sample fraction's scale
      R11 = PASS R7;                    // row b
      R8 = PASS R3;                     // ff, for the whole loop (#2)
      R12 = PASS R12;
      IF EQ JUMP 0x171b63;              // -> wr_miph2_done. (count 0: write nothing)
      R0 = PASS R12;                    // the count, for LCNTR
      R12 = PASS R6;                    // row a
      LCNTR = R0, DO wr_miph2_last. UNTIL LCE;   // E2-active (the mix branch is in the body)

.GLOBAL wr_miph2_loop.;
wr_miph2_loop.:
      R0 = LSHIFT R9 BY R13;            // i
      R0 = LSHIFT R0 BY 1;              // tap i-1's byte offset in a guarded row
      R1 = R12 + R0;                    // row a, tap i-1
      R0 = R11 + R0;                    // row b, tap i-1
      I0 = R1;
      I1 = R0;
      R0 = R9 AND R14;                  // between the I0/I1 moves and their first use (step 1a)
      F10 = FLOAT R0 BY R15;            // hfr, half the sample fraction (exact)
      R0 = DM(2, I4);                   // inc (#2: read here, so the add below doesn't wait for it)
      R4 = DM(I0, M6) (SWSE);           // a[i-1]
      R5 = DM(I0, M6) (SWSE);           // a[i]
      R6 = DM(I0, M6) (SWSE);           // a[i+1]
      R7 = DM(I0, M6) (SWSE);           // a[i+2]
      R9 = R9 + R0;                     // phase += inc, mod 2^32: R9's last use is above
      R0 = DM(I1, M6) (SWSE);           // b[i-1]
      R1 = DM(I1, M6) (SWSE);           // b[i]
      R2 = DM(I1, M6) (SWSE);           // b[i+1]
      R3 = DM(I1, M6) (SWSE);           // b[i+2]
      // the taps as integers in float (#2: the 2^-15 full scale is in the gain, which is exact: every
      // operation below is linear, and a power of two scales a float without rounding); F0 last, so the
      // next instruction is a two-operand compute (anomaly 20000072)
      F4 = FLOAT R4;
      F5 = FLOAT R5;
      F6 = FLOAT R6;
      F7 = FLOAT R7;
      F1 = FLOAT R1;
      F2 = FLOAT R2;
      F3 = FLOAT R3;
      F0 = FLOAT R0;

      // the taps between the frames: t = a + ff * (b - a). Step 1a: the four taps' subtracts,
      // then their multiplies, then their adds, so no result feeds the next instruction (each
      // value takes the same operations as before, so the output is the same bit for bit)
      F0 = F0 - F4;
      F1 = F1 - F5;
      F2 = F2 - F6;
      F3 = F3 - F7;
      F0 = F8 * F0;
      F1 = F8 * F1;
      F2 = F8 * F2;
      F3 = F8 * F3;
      F4 = F4 + F0;                     // ym
      F5 = F5 + F1;                     // y0
      F6 = F6 + F2;                     // y1
      F7 = F7 + F3;                     // y2

      // one Catmull-Rom on the blend, render.hermite's order for each value. Step 1a: the
      // independent terms interleaved; F8 is scratch here and takes -15 back before the end
      F0 = F5 - F6;                     // t = y0 - y1
      F2 = F4 - F5;                     // a = ym - y0
      F3 = F6 - F5;                     // b = y1 - y0
      F1 = F0 + F0;                     // 2t (F1 is scratch: F8 holds ff for the whole loop, #2)
      F2 = F2 + F2;                     // 2a
      F3 = F3 + F3;                     // 2b
      F0 = F1 + F0;                     // 3t
      F1 = F7 - F4;                     // y2 - ym
      F7 = F7 - F5;                     // d = y2 - y0
      F3 = F3 + F3;                     // 4b
      F6 = F6 - F4;                     // c1 = y1 - ym
      F0 = F0 + F1;                     // c3
      F2 = F2 + F3;                     // 2a + 4b
      F4 = F10 + F10;                   // fr
      F2 = F2 - F7;                     // c2
.NOCOMPRESS;                            // a hardware loop's last 11 instructions are 48-bit (PRM 4-42)
      F0 = F0 * F4;
      R1 = DM(0x2e3204);                // the gain x 2^-15 (#2; F1 is free after c3)
      F0 = F0 + F2;
      R3 = DM(0x2de6c4);                // osc 2 adds into the buffer osc 1 wrote (DM 0x2de6c4 = 1)
      F0 = F0 * F4;
      R2 = DM(0, I2);                   // what osc 1 wrote: harmless for osc 1, whose R2 is not used
      F0 = F0 + F6;                     // + c1
      F0 = F0 * F10;
      F0 = F0 + F5;                     // y
      F0 = F1 * F0;                     // y * gain
      R3 = PASS R3;
      IF NE F0 = F0 + F2;               // step 1b: a conditional add in place of a branch round it
.GLOBAL wr_miph2_last.;
wr_miph2_last.:
      DM(I2, M6) = F0;
.COMPRESS;
      R0 = R0 - R0;
      DM(4, I4) = R0;                   // 0: the count word as the software loop left it

.GLOBAL wr_miph2_done.;
wr_miph2_done.:
      I12 = DM(M7, I6);
      DM(1, I4) = R9;                   // phase, for the next block
      JUMP (M14, I12) (DB);
      NOP;
      RFRAME;
.wr_miph2..end:
      .type wr_miph2.,STT_FUNC;
