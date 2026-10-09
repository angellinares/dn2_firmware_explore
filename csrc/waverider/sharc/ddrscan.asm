// ddrscan.asm -- does anything write the DSP's spare DDR while the instrument plays?
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). A diagnostic, never a mod: the build is scripts/build_ddrscan.py.
//
// The build fills the span with PATTERN through boot-stream fill blocks, which the boot
// kernel writes before any stock code runs. This then reads the span back, word by word,
// in the idle task: the idle loop's back edge jumps here, CHUNK words are checked, and it
// goes on to idle_load.asm (wr_idle), which jumps back to the loop's top. So it only ever
// runs when the DSP has nothing else to do, and a word that differs from PATTERN was
// written by someone else.
//
// Each pass over the span publishes, then starts again:
//   PUB[0]  passes completed
//   PUB[1]  words that differ, in the last pass
//   PUB[2]  the first of them, as (address - 0x80000000) / 4
//   PUB[3]  the last of them, the same way
//   PUB[4..19]  which 2 MB granules ever held one: granule g is bit g & 15 of PUB[4 + g >> 4]
//              (sticky; 256 granules, all of DDR)
// Every 1,024 calls the next PUB entry goes to reply word 2 of both reply pages as
// IDX << 27 | (value & 0x7ffffff), halves swapped as reply word 0, so the ColdFire reads a
// big-endian u32 (tools/dn2ddrscan.py). Reply word 2 is block_count.asm's, absent from this
// build; no ColdFire code reads bytes 4..0x15 (docs/for-digikit-waverider-dsp-stop.md).
//
// It uses R0-R5 and I0, saved to its own area and restored before wr_idle (the audio
// task can preempt the idle task at any instruction; the idle loop recomputes what it
// tests, so ASTAT is free).
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16f800 (L1 block 1, byte 0x2df000).
//
// DM (byte addresses, the build's state block at 0x2df800):
//   0x2df800..0x2df818  save: R0, R1, R2, R3, R4, R5, I0
//   0x2df820  CUR (a DDR byte address)   0x2df824  START   0x2df828  END   0x2df82c  PATTERN
//   0x2df830  CNT   0x2df834  FIRST   0x2df838  LAST   0x2df83c  TICK   0x2df840  IDX
//   0x2df880  PUB[0..19]
//   0x2c49d8 / 0x2c59d8  reply word 2

.SECTION/PM seg_pmco;

.GLOBAL wr_scan.;
wr_scan.:
      DM(0x2df800) = R0;
      DM(0x2df804) = R1;
      DM(0x2df808) = R2;
      DM(0x2df80c) = R3;
      DM(0x2df810) = R4;
      DM(0x2df814) = R5;
      DM(0x2df818) = I0;

      R0 = DM(0x2df820);                // CUR
      R1 = DM(0x2df82c);                // PATTERN
      R2 = 32;                          // CHUNK: the words this call checks

.GLOBAL wr_scan_word.;
wr_scan_word.:
      I0 = R0;
      R3 = DM(0, I0);
      R3 = R3 - R1;
      IF NE JUMP 0x16f87c;              // -> wr_scan_hit.

.GLOBAL wr_scan_next.;
wr_scan_next.:
      R4 = 4;
      R0 = R0 + R4;
      R4 = DM(0x2df828);                // END
      COMPU(R0, R4);
      IF GE JUMP 0x16f8b3;              // -> wr_scan_wrap.

.GLOBAL wr_scan_more.;
wr_scan_more.:
      R4 = 1;
      R2 = R2 - R4;
      IF NE JUMP 0x16f81d;              // -> wr_scan_word.
      DM(0x2df820) = R0;                // CUR

      R3 = DM(0x2df83c);                // TICK
      R4 = 1;
      R3 = R3 + R4;
      DM(0x2df83c) = R3;
      R4 = 1023;
      R3 = R3 AND R4;
      IF NE JUMP 0x16f8e9;              // -> wr_scan_out.
      R3 = DM(0x2df840);                // IDX
      R4 = 1;
      R3 = R3 + R4;
      R4 = 20;
      COMPU(R3, R4);
      IF LT JUMP 0x16f856;              // -> wr_scan_keep.
      R3 = R3 - R3;

.GLOBAL wr_scan_keep.;
wr_scan_keep.:
      DM(0x2df840) = R3;
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
      JUMP 0x16f8e9;                    // -> wr_scan_out.

.GLOBAL wr_scan_hit.;
wr_scan_hit.:
      R4 = DM(0x2df830);                // CNT
      R4 = PASS R4;
      IF NE JUMP 0x16f886;              // -> wr_scan_counted.
      DM(0x2df834) = R0;                // FIRST

.GLOBAL wr_scan_counted.;
wr_scan_counted.:
      R5 = 1;
      R4 = R4 + R5;
      DM(0x2df830) = R4;                // CNT
      DM(0x2df838) = R0;                // LAST
      R4 = 0x80000000;
      R4 = R0 - R4;                     // the offset into DDR
      R4 = LSHIFT R4 BY -21;            // its 2 MB granule, 0..255
      R5 = LSHIFT R4 BY -4;             // the granule's PUB word, 0..15
      R5 = LSHIFT R5 BY 2;
      R3 = 0x2df890;                    // PUB[4]
      R5 = R3 + R5;
      I0 = R5;
      R3 = 15;
      R4 = R4 AND R3;
      R3 = 1;
      R3 = LSHIFT R3 BY R4;             // the granule's bit
      R5 = DM(0, I0);
      R5 = R5 OR R3;
      DM(0, I0) = R5;
      JUMP 0x16f825;                    // -> wr_scan_next.

.GLOBAL wr_scan_wrap.;
wr_scan_wrap.:
      R4 = DM(0x2df830);                // CNT, the pass's
      DM(0x2df884) = R4;                // PUB[1]
      R5 = 0x80000000;
      R3 = DM(0x2df834);                // FIRST
      R3 = R3 - R5;
      R3 = LSHIFT R3 BY -2;
      DM(0x2df888) = R3;                // PUB[2]
      R3 = DM(0x2df838);                // LAST
      R3 = R3 - R5;
      R3 = LSHIFT R3 BY -2;
      DM(0x2df88c) = R3;                // PUB[3]
      R3 = DM(0x2df880);
      R4 = 1;
      R3 = R3 + R4;
      DM(0x2df880) = R3;                // PUB[0]: passes
      R3 = R3 - R3;
      DM(0x2df830) = R3;                // CNT
      DM(0x2df834) = R5;                // FIRST, LAST: 0x80000000, offset 0
      DM(0x2df838) = R5;
      R0 = DM(0x2df824);                // START
      JUMP 0x16f830;                    // -> wr_scan_more.

.GLOBAL wr_scan_out.;
wr_scan_out.:
      R0 = DM(0x2df800);
      R1 = DM(0x2df804);
      R2 = DM(0x2df808);
      R3 = DM(0x2df80c);
      R4 = DM(0x2df810);
      R5 = DM(0x2df814);
      I0 = DM(0x2df818);
      JUMP 0x16f500;                    // -> wr_idle.
