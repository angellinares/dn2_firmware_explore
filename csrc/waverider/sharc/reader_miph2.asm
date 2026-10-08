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
// Registers in the loop: R8 = -15 (ff while the taps blend, -15 again for the next
// sample), R9 phase, R10 hfr, R11 row b, R12 row a, R13 the sample index's shift
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
      R8 = R8 - R1;                     // the table's address without the flag
      R2 = 1;
      R1 = 0x95eb41;                    // T[0] = ceil(28 kHz / 255)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph2_level.
      R13 = R13 + R2;
      R1 = 0x12d04b5;                   // T[1] = ceil(28 kHz / 127)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph2_level.
      R13 = R13 + R2;
      R1 = 0x25ed098;                   // T[2] = ceil(28 kHz / 63)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph2_level.
      R13 = R13 + R2;
      R1 = 0x4d1344e;                   // T[3] = ceil(28 kHz / 31)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph2_level.
      R13 = R13 + R2;
      R1 = 0x9f49f4a;                   // T[4] = ceil(28 kHz / 15)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph2_level.
      R13 = R13 + R2;
      R1 = 0x15555556;                  // T[5] = ceil(28 kHz / 7)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph2_level.
      R13 = R13 + R2;
      R1 = 0x31c71c72;                  // T[6] = ceil(28 kHz / 3)
      COMPU(R10, R1);
      IF LT JUMP 0x171a5a;              // -> wr_miph2_level.
      R13 = R13 + R2;                   // level 7, the last

.GLOBAL wr_miph2_level.;
wr_miph2_level.:
      R3 = LSHIFT R13 BY 5;             // k * 32 bytes: its record
      R4 = 0x2e3100;
      R3 = R4 + R3;
      I1 = R3;
      R4 = DM(0, I1);                   // the level's byte offset in the table
      R8 = R8 + R4;
      R5 = DM(1, I1);                   // b + 1: a row is 2^(b+1) + 6 bytes

      // Rows: f0 = pos >> 16, f1 = min(f0 + 1, 15); row f = table + f * 2^(b+1) + f * 6
      R0 = LSHIFT R11 BY -16;
      R2 = 1;
      R1 = R0 + R2;
      R2 = 15;
      R1 = MIN(R1, R2);
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
      IF EQ JUMP 0x171b84;              // -> wr_miph2_done. (count 0: write nothing)
      R0 = PASS R12;                    // the count, for LCNTR
      R12 = PASS R6;                    // row a
      LCNTR = R0, DO wr_miph2_last. UNTIL LCE;   // E2-active (the mix branch is in the body)

.GLOBAL wr_miph2_loop.;
wr_miph2_loop.:
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
      F0 = F0 * F10;
.NOCOMPRESS;                            // a hardware loop's last 11 instructions are 48-bit (PRM 4-42)
      F0 = F0 + F5;                     // y
      R1 = DM(0x2de6c0);                // the gain, LEV / 100
      F0 = F1 * F0;                     // y * gain
      // osc 2 adds into the buffer osc 1 wrote (DM 0x2de6c4 = 1)
      R1 = DM(0x2de6c4);
      R1 = PASS R1;
      IF EQ JUMP 0x171b78;              // -> wr_miph2_store.
      R2 = DM(0, I2);                   // what osc 1 wrote
      F0 = F0 + F2;
.GLOBAL wr_miph2_store.;
wr_miph2_store.:
      DM(I2, M6) = F0;
      R0 = DM(2, I4);                   // inc
.GLOBAL wr_miph2_last.;
wr_miph2_last.:
      R9 = R9 + R0;                     // phase += inc, mod 2^32 (the loop's last instruction)
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
