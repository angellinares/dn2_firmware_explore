// loadmap.asm -- where the SHARC's frame goes: cycles per stage, stock's and Waverider's.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). A diagnostic: only a build made with DNFW_WAVERIDER_LOADMAP=1 carries it
// (dnfw.waverider.loadmap). It changes no sample.
//
// The build retargets chosen jumps and calls (stock's and ours) to MARK STUBS, 12 bytes
// each from sw 0x16fbc0 (DM 0x2df780):
//
//   stub k:  CALL wr_lm_mark;  JUMP <the original target>
//
// wr_lm_mark reads EMUCLK, adds the cycles since the previous mark to the record of the
// segment that was running, counts a pass for it, and makes k the running segment. It
// finds k from its return address: PCSTK = stub k + 3, so the record's byte offset is
// (PCSTK - 0x16fbc3) x 2 = 12k. A segment is "from mark k to the next mark", whatever
// that is; each segment's cycles include one mark's own cost, which segment 3 (NULL,
// two marks back to back) measures.
//
// Every register, ASTAT and MODE1 are as they were when the stub was entered: PUSH STS
// saves ASTATx, ASTATy and MODE1, and SISD with no ALU saturation is set inside (the
// mark may sit where SIMD or saturation is on). The indexed accesses use pre-modify
// addressing, which is never circular (PRM: circular buffering only post-modifies), so
// L1 does not matter. The PC stack holds the stub's return for the mark's duration.
//
// wr_lm_pub runs once a block, between marks 4 and 5 (in the dispatch's splice, after
// block_count.asm). Every 4,096 blocks it copies the records to SNAP in DDR and zeroes
// them. Every block it writes a 24-word PAGE of SNAP into the reply record of both reply
// pages, two words in each of slot rows 1 to 12, at +0x44 and +0x48 of the row (row r at
// record byte 0x1c + 0x54 r): entries 11 and 12, which no stock DSP code writes. The
// layout is digikit's diagnostic block (core/dsp-link, docs/findings/31 and 45); the
// engine clears the whole record every block before the per-block routine, so the page
// is written every block. Whether the ColdFire leaves those bytes alone on a DN2 unit is
// checked on the instrument before this build is flashed.
//
//   page word 0   0x4c4d0000 | (SEQ & 0xff) << 8 | p     (p = 0, 1, 2)
//   words 1-22    SNAP words 22p .. 22p + 21
//   word 23       the XOR of words 0-22 (a page read across two frames fails it)
//
// The page changes every 8 blocks; the next one is built in DDR (SNAP + 0x200) when it
// changes. tools/dn2loadmap.py reads the 24 words with the USB probe.
//
// SNAP (DDR 0x80780000, inside Waverider's DDR region and above everything it loads):
//   +0  0x4c4d0000 | N (N = 31 marks)   +4  blocks a window (4,096)   +8  SEQ
//   +12 + 8k  segment k's cycles, then its passes;  +0x104  0 (page 2's last word)
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16fe40 (L1 block 1, byte 0x2dfc80).
//
// DM (byte addresses, L1 block 1, zero at boot):
//   0x2dfa40 .. 0x2dfa4c  the mark's saves: R8, R9, R10, I1
//   0x2dfa50  LAST: EMUCLK at the previous mark      0x2dfa54  CUR: the running record, 12k
//   0x2dfa58  BLOCKS     0x2dfa5c  the next page, 0..2     0x2dfa60  SEQ
//   0x2dfa64 .. 0x2dfa7c  the publisher's saves: R8, R9, R10, R11, I1, I0, R12
//   0x2dfa80 + 12k  segment k's record: cycles, passes, a spare word (31 records)
//   0x2c4a84 + 0x54 r and + 4: page word 2r and 2r + 1;  0x2c5a84 + ...: the other reply page

.SECTION/PM seg_pmco;

.GLOBAL wr_lm_mark.;
wr_lm_mark.:
      PUSH STS;
      DM(0x2dfa40) = R8;
      DM(0x2dfa44) = R9;
      DM(0x2dfa48) = R10;
      DM(0x2dfa4c) = I1;
      BIT CLR MODE1 0x202000;           // SISD (PEYEN), no ALU saturation (ALUSAT)
      R8 = EMUCLK;                      // now
      R9 = DM(0x2dfa50);                // LAST
      DM(0x2dfa50) = R8;
      R8 = R8 - R9;                     // d: the running segment's cycles (mod 2^32)
      R9 = PCSTK;                       // stub k + 3
      R10 = 0x16fbc3;
      R9 = R9 - R10;                    // 6k
      R9 = LSHIFT R9 BY 1;              // 12k: the new segment's record
      R10 = DM(0x2dfa54);               // CUR: the running segment's record
      DM(0x2dfa54) = R9;
      R9 = 0x2dfa80;
      R10 = R10 + R9;
      I1 = R10;
      R9 = DM(0, I1);
      R9 = R9 + R8;
      DM(0, I1) = R9;                   // its cycles
      R9 = DM(1, I1);
      R10 = 1;
      R9 = R9 + R10;
      DM(1, I1) = R9;                   // its passes
      I1 = DM(0x2dfa4c);
      R10 = DM(0x2dfa48);
      R9 = DM(0x2dfa44);
      R8 = DM(0x2dfa40);
      POP STS;
      RTS;
.wr_lm_mark..end:
      .type wr_lm_mark.,STT_FUNC;

.GLOBAL wr_lm_pub.;
wr_lm_pub.:
      PUSH STS;
      DM(0x2dfa64) = R8;
      DM(0x2dfa68) = R9;
      DM(0x2dfa6c) = R10;
      DM(0x2dfa70) = R11;
      DM(0x2dfa74) = I1;
      DM(0x2dfa78) = I0;
      BIT CLR MODE1 0x202000;
      R8 = DM(0x2dfa58);
      R9 = 1;
      R8 = R8 + R9;
      DM(0x2dfa58) = R8;                // BLOCKS
      R9 = 0xfff;
      R9 = R8 AND R9;
      IF NE JUMP 0x16fef9;              // -> wr_lm_send. (the window is still open)

      // the window closes: SNAP's header, then each record, zeroed behind
      R9 = DM(0x2dfa60);
      R10 = 1;
      R9 = R9 + R10;
      DM(0x2dfa60) = R9;                // SEQ
      I0 = 0x80780000;
      R10 = 0x4c4d001f;                 // 'LM' | N
      DM(0, I0) = R10;
      R10 = 4096;
      DM(1, I0) = R10;
      DM(2, I0) = R9;
      I0 = 0x8078000c;
      I1 = 0x2dfa80;
      R8 = 31;                          // N
.GLOBAL wr_lm_copy.;
wr_lm_copy.:
      R9 = DM(0, I1);
      DM(0, I0) = R9;
      R9 = DM(1, I1);
      DM(1, I0) = R9;
      R9 = R9 - R9;
      DM(0, I1) = R9;
      DM(1, I1) = R9;
      R10 = I1;
      R11 = 12;
      R10 = R10 + R11;
      I1 = R10;
      R10 = I0;
      R11 = 8;
      R10 = R10 + R11;
      I0 = R10;
      R9 = 1;
      R8 = R8 - R9;
      IF NE JUMP 0x16fed5;              // -> wr_lm_copy.
      R9 = R9 - R9;
      DM(0, I0) = R9;                   // SNAP + 0x104: page 2's last word

.GLOBAL wr_lm_send.;
wr_lm_send.:
      R9 = DM(0x2dfa60);                // SEQ
      R9 = PASS R9;
      IF EQ JUMP 0x16ff90;              // -> wr_lm_out. (no window closed yet)
      R8 = DM(0x2dfa58);
      R10 = 7;
      R10 = R8 AND R10;
      IF NE JUMP 0x16ff59;              // -> wr_lm_rows. (the page stays)

      // a new page p: word 0, SNAP words 22p .. 22p + 21, the check
      R8 = DM(0x2dfa5c);                // p
      R10 = 0xff;
      R9 = R9 AND R10;
      R9 = LSHIFT R9 BY 8;
      R9 = R9 OR R8;
      R10 = 0x4c4d0000;
      R9 = R9 OR R10;                   // word 0, and the check's start
      I0 = 0x80780200;
      DM(0, I0) = R9;
      R10 = LSHIFT R8 BY 6;
      R11 = LSHIFT R8 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R8 BY 3;
      R10 = R10 + R11;                  // 88p: 22 words a page
      R11 = 0x80780000;
      R10 = R10 + R11;
      I1 = R10;
      R8 = 22;
.GLOBAL wr_lm_fill.;
wr_lm_fill.:
      R10 = DM(0, I1);
      R9 = R9 XOR R10;
      DM(1, I0) = R10;
      R10 = I1;
      R11 = 4;
      R10 = R10 + R11;
      I1 = R10;
      R10 = I0;
      R10 = R10 + R11;
      I0 = R10;
      R11 = 1;
      R8 = R8 - R11;
      IF NE JUMP 0x16ff30;              // -> wr_lm_fill.
      DM(1, I0) = R9;                   // word 23: the check
      R8 = DM(0x2dfa5c);
      R11 = 1;
      R8 = R8 + R11;
      R11 = 3;
      COMP(R8, R11);
      IF LT JUMP 0x16ff56;              // -> wr_lm_keep.
      R8 = R8 - R8;
.GLOBAL wr_lm_keep.;
wr_lm_keep.:
      DM(0x2dfa5c) = R8;

      // every block: the page into rows 1-12 of both reply records, one pass each
.GLOBAL wr_lm_rows.;
wr_lm_rows.:
      DM(0x2dfa7c) = R12;
      R12 = 0x2c4a84;                   // reply page 0x2c49d0 + 0x1c + 0x54 + 0x44
.GLOBAL wr_lm_page.;
wr_lm_page.:
      I0 = 0x80780200;
      I1 = R12;
      R8 = 12;
.GLOBAL wr_lm_row.;
wr_lm_row.:
      R9 = DM(0, I0);
      DM(0, I1) = R9;                   // +0x44
      R9 = DM(1, I0);
      DM(1, I1) = R9;                   // +0x48
      R10 = I0;
      R11 = 8;
      R10 = R10 + R11;
      I0 = R10;
      R10 = I1;
      R11 = 0x54;
      R10 = R10 + R11;
      I1 = R10;
      R11 = 1;
      R8 = R8 - R11;
      IF NE JUMP 0x16ff66;              // -> wr_lm_row.
      R11 = 0x2c5a84;                   // the other reply page (0x2c59d0)
      COMP(R12, R11);
      IF EQ JUMP 0x16ff8d;              // -> wr_lm_rows_done. (both pages written)
      R12 = PASS R11;                   // a compute: it sets the flags, so it comes after the test
      JUMP 0x16ff5f;                    // -> wr_lm_page.
.GLOBAL wr_lm_rows_done.;
wr_lm_rows_done.:
      R12 = DM(0x2dfa7c);

.GLOBAL wr_lm_out.;
wr_lm_out.:
      I0 = DM(0x2dfa78);
      I1 = DM(0x2dfa74);
      R11 = DM(0x2dfa70);
      R10 = DM(0x2dfa6c);
      R9 = DM(0x2dfa68);
      R8 = DM(0x2dfa64);
      POP STS;
      JUMP 0x16fbde;                    // mark 5's stub (W_ENTRY): sw 0x16fbc0 + 6 x 5
.wr_lm_pub..end:
      .type wr_lm_pub.,STT_FUNC;
