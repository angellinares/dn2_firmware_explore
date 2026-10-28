// cohprobe.asm -- do the DM and PM data caches agree on DDR, on the DSP itself?
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). A diagnostic, never a mod: the build is scripts/build_cohprobe.py.
//
// The SHARC+ Programming Reference (chapter 8, "Coherency Between DM and PM Caches") says a
// hardware cross-check keeps the two data caches coherent. fftselftest (2026-10-09) read
// zeros where fft3 wrote on PM and read on DM, but fftselftest3 fixed that by changing two
// things (one bus per array, and no I6, which wraps: L6 = L7 = 194 with CBUFEN on). This
// takes the two apart. In the idle task (the idle loop's back edge jumps here, as for
// ddrscan.asm; this goes on to idle_load.asm's wr_idle), every call checks 16 cache lines
// (64 bytes apart) in each of five cases, each case in its own 16 KB of spare DDR, moving
// 1 KB a call so all 256 lines of a 16 KB cache come round every 16 calls:
//
//   A  DM read (the line is now in the DM cache), PM write V, DM read: expect V
//   B  PM read (the line is now in the PM cache), DM write V, PM read: expect V
//   C  PM write V, DM read, with no read before it (fftselftest's order)
//   D  DM write V, DM read: the same-bus control
//   E  PM write V, DM read on L1 block 1 (no cache): the uncached control
//
// V = CALLS << 8 | case << 4 | line, new each call. A read that is not V counts as bad, and
// as stale too when it equals the line's value before the write (A, B: the first read;
// C, D: the value the case wrote 16 calls before; E: the call before).
//
// No index register walks: every access is DM(0, I0) or PM(0, I8), pre-modify by 0, so no
// L or B register matters (the idle task runs on the secondary DAG set). It uses R0-R7, I0
// and I8, saved to its own area and restored before wr_idle (the audio task can preempt the
// idle task at any instruction; the idle loop recomputes what it tests, so ASTAT is free).
// Each call also reads SHL1C_CFG (0x3e000, as stock's sw 0x1c07fb reads it) and SHL1C_CFG2
// (0x3e002).
//
//   PUB[0]  calls          PUB[1..5]  bad reads, cases A..E
//   PUB[6..10]  of those, the stale ones, cases A..E
//   PUB[11] the first bad read: 0x1000 | case << 8 | line (case 1..5 = A..E; 0 = none yet)
//   PUB[12] its value low 27 bits  [13] >> 27   PUB[14] V low 27 bits  [15] >> 27
//   PUB[16] SHL1C_CFG low 27 bits  [17] >> 27   PUB[18] SHL1C_CFG2 low 27  [19] >> 27
// Every 256 calls the next PUB entry goes to reply word 2 of both reply pages as
// IDX << 27 | (value & 0x7ffffff), halves swapped as reply word 0 (tools/dn2cohprobe.py).
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16f800 (L1 block 1, byte 0x2df000).
//
// DM (byte addresses, the state block at 0x2df800):
//   0x2df800..0x2df824  save: R0-R7, I0, I8
//   0x2df830  CALLS   0x2df834  OFF (0..0x3c00)   0x2df838  TICK   0x2df83c  IDX
//   0x2df880  PUB[0..19]
//   0x2df900  case E's 16 words
//   0x2c49d8 / 0x2c59d8  reply word 2
// DDR: case A 0x80600000, B 0x80604000, C 0x80608000, D 0x8060c000 (Waverider's region,
// absent from this build).

.SECTION/PM seg_pmco;

.GLOBAL wr_coh.;
wr_coh.:
      DM(0x2df800) = R0;
      DM(0x2df804) = R1;
      DM(0x2df808) = R2;
      DM(0x2df80c) = R3;
      DM(0x2df810) = R4;
      DM(0x2df814) = R5;
      DM(0x2df818) = R6;
      DM(0x2df81c) = R7;
      DM(0x2df820) = I0;
      DM(0x2df824) = I8;

      R7 = DM(0x2df830);                // CALLS
      R0 = 1;
      R7 = R7 + R0;
      DM(0x2df830) = R7;
      DM(0x2df880) = R7;                // PUB[0]
      R7 = LSHIFT R7 BY 8;              // V's high part
      R6 = DM(0x2df834);                // OFF
      R4 = R4 - R4;                     // the line, 0..15
      R5 = 16;                          // lines left

.GLOBAL wr_coh_line.;
wr_coh_line.:
      // -- A: DM read, PM write, DM read
      R0 = 0x80600000;
      R0 = R0 + R6;
      I0 = R0;
      I8 = R0;
      R1 = DM(0, I0);                   // the line's value before (now in the DM cache)
      R3 = 0x10;
      R3 = R3 OR R7;
      R3 = R3 OR R4;                    // V
      PM(0, I8) = R3;
      R2 = DM(0, I0);
      R0 = 0x2df884;                    // PUB[1]
      COMP(R2, R3);
      IF NE CALL 0x16f94c;                   // -> wr_coh_bad.

      // -- B: PM read, DM write, PM read
      R0 = 0x80604000;
      R0 = R0 + R6;
      I0 = R0;
      I8 = R0;
      R1 = PM(0, I8);                   // the line's value before (now in the PM cache)
      R3 = 0x20;
      R3 = R3 OR R7;
      R3 = R3 OR R4;
      DM(0, I0) = R3;
      R2 = PM(0, I8);
      R0 = 0x2df888;                    // PUB[2]
      COMP(R2, R3);
      IF NE CALL 0x16f94c;                   // -> wr_coh_bad.

      // -- C: PM write, DM read
      R0 = 0x80608000;
      R0 = R0 + R6;
      I0 = R0;
      I8 = R0;
      R3 = 0x30;
      R3 = R3 OR R7;
      R3 = R3 OR R4;
      R1 = 0x1000;
      R1 = R3 - R1;                     // the value written 16 calls before
      PM(0, I8) = R3;
      R2 = DM(0, I0);
      R0 = 0x2df88c;                    // PUB[3]
      COMP(R2, R3);
      IF NE CALL 0x16f94c;                   // -> wr_coh_bad.

      // -- D: DM write, DM read (the same-bus control)
      R0 = 0x8060c000;
      R0 = R0 + R6;
      I0 = R0;
      R3 = 0x40;
      R3 = R3 OR R7;
      R3 = R3 OR R4;
      R1 = 0x1000;
      R1 = R3 - R1;
      DM(0, I0) = R3;
      R2 = DM(0, I0);
      R0 = 0x2df890;                    // PUB[4]
      COMP(R2, R3);
      IF NE CALL 0x16f94c;                   // -> wr_coh_bad.

      // -- E: PM write, DM read on L1 (the uncached control)
      R0 = LSHIFT R4 BY 2;
      R1 = 0x2df900;
      R0 = R0 + R1;
      I0 = R0;
      I8 = R0;
      R3 = 0x50;
      R3 = R3 OR R7;
      R3 = R3 OR R4;
      R1 = 0x100;
      R1 = R3 - R1;                     // E's words are written every call
      PM(0, I8) = R3;
      R2 = DM(0, I0);
      R0 = 0x2df894;                    // PUB[5]
      COMP(R2, R3);
      IF NE CALL 0x16f94c;                   // -> wr_coh_bad.

      R0 = 64;
      R6 = R6 + R0;                     // the next line
      R0 = 1;
      R4 = R4 + R0;
      R5 = R5 - R0;
      IF NE JUMP 0x16f833;                   // -> wr_coh_line.

      R0 = 0x3c00;
      R6 = R6 AND R0;                   // OFF + 1 KB, within the 16 KB
      DM(0x2df834) = R6;

      // -- the cache configuration, every call
      R1 = 0x7ffffff;
      R0 = DM(0x3e000);                 // SHL1C_CFG
      R2 = R0 AND R1;
      DM(0x2df8c0) = R2;                // PUB[16]
      R2 = LSHIFT R0 BY -27;
      DM(0x2df8c4) = R2;                // PUB[17]
      R0 = DM(0x3e002);                 // SHL1C_CFG2
      R2 = R0 AND R1;
      DM(0x2df8c8) = R2;                // PUB[18]
      R2 = LSHIFT R0 BY -27;
      DM(0x2df8cc) = R2;                // PUB[19]

      // -- publish one entry every 256 calls
      R3 = DM(0x2df838);                // TICK
      R4 = 1;
      R3 = R3 + R4;
      DM(0x2df838) = R3;
      R4 = 255;
      R3 = R3 AND R4;
      IF NE JUMP 0x16f92b;                   // -> wr_coh_out.
      R3 = DM(0x2df83c);                // IDX
      R4 = 1;
      R3 = R3 + R4;
      R4 = 20;
      COMPU(R3, R4);
      IF LT JUMP 0x16f908;                   // -> wr_coh_keep.
      R3 = R3 - R3;

.GLOBAL wr_coh_keep.;
wr_coh_keep.:
      DM(0x2df83c) = R3;
      R4 = LSHIFT R3 BY 2;
      R5 = 0x2df880;                    // PUB
      R4 = R4 + R5;
      I0 = R4;
      R4 = DM(0, I0);                   // PUB[IDX]
      R5 = 0x7ffffff;
      R4 = R4 AND R5;
      R5 = LSHIFT R3 BY 27;
      R4 = R4 OR R5;                    // IDX << 27 | value
      R5 = LSHIFT R4 BY 16;
      R4 = LSHIFT R4 BY -16;
      R4 = R4 OR R5;                    // halves swapped, as reply word 0
      DM(0x2c49d8) = R4;                // reply word 2, both pages
      DM(0x2c59d8) = R4;

.GLOBAL wr_coh_out.;
wr_coh_out.:
      R0 = DM(0x2df800);
      R1 = DM(0x2df804);
      R2 = DM(0x2df808);
      R3 = DM(0x2df80c);
      R4 = DM(0x2df810);
      R5 = DM(0x2df814);
      R6 = DM(0x2df818);
      R7 = DM(0x2df81c);
      I0 = DM(0x2df820);
      I8 = DM(0x2df824);
      JUMP 0x16f500;                    // -> wr_idle.

// A bad read. R0: the case's bad counter (PUB[1..5]), R1: the line's value before the
// write, R2: what the read gave, R3: V, R4: the line. Changes R0, R1 and I0 only.
.GLOBAL wr_coh_bad.;
wr_coh_bad.:
      I0 = R0;
      R0 = DM(0, I0);
      R0 = R0 + 1;
      DM(0, I0) = R0;                   // bad
      COMP(R2, R1);
      IF NE JUMP 0x16f96a;                   // -> wr_coh_first.
      R0 = I0;
      R1 = 20;
      R0 = R0 + R1;
      I0 = R0;                          // the same case's PUB[6..10]: no DAG offset, whose unit
      R0 = DM(0, I0);                   // (bytes or words) the emulator and the PRM may not share
      R0 = R0 + 1;
      DM(0, I0) = R0;                   // stale
      R0 = I0;
      R1 = 20;
      R0 = R0 - R1;
      I0 = R0;                          // back to the bad counter, for the case below

.GLOBAL wr_coh_first.;
wr_coh_first.:
      R0 = DM(0x2df8ac);                // PUB[11]
      R0 = PASS R0;
      IF NE RTS;
      R0 = I0;
      R1 = 0x2df880;
      R0 = R0 - R1;                     // 4 x case
      R0 = LSHIFT R0 BY 6;              // case << 8
      R0 = R0 OR R4;
      R1 = 0x1000;
      R0 = R0 OR R1;
      DM(0x2df8ac) = R0;                // PUB[11]
      R1 = 0x7ffffff;
      R0 = R2 AND R1;
      DM(0x2df8b0) = R0;                // PUB[12]
      R0 = LSHIFT R2 BY -27;
      DM(0x2df8b4) = R0;                // PUB[13]
      R0 = R3 AND R1;
      DM(0x2df8b8) = R0;                // PUB[14]
      R0 = LSHIFT R3 BY -27;
      DM(0x2df8bc) = R0;                // PUB[15]
      RTS;
