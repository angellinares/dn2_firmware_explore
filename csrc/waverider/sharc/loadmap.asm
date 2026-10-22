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
// block_count.asm). Every 4,096 blocks (a window) it zeroes the records. Every 32nd window
// (131,072 blocks, 87 s) it first copies them to SNAP in DDR, so SNAP holds one window and
// stays the same for 87 s. Every block it writes one half of SNAP to reply word 2 of both
// reply pages, in place of block_count.asm's count, the next half each block:
//
//   the ColdFire reads TAG << 16 | HALF   (halves swapped as reply word 0)
//   TAG = 0x8000 | (SEQ & 0x3f) << 8 | i  (i = 0 .. 129, the half: word i >> 1, high if odd)
//
// Until the first SNAP (SEQ 0) it writes 0. tools/dn2loadmap.py reads the word with the USB
// probe until it holds every half of one SEQ, each seen twice with the same value.
// (Until 2026-10-22 the pages went to entries 11 and 12 of slot rows 1-12. On a DN2 those
// bytes are samples 1-12 of the effects buses, channels 22-25: the unit's row check failed.)
//
// SNAP (DDR 0x80780000, inside Waverider's DDR region and above everything it loads):
//   +0  0x4c4d0000 | N (N = 31 marks)   +4  blocks a window (4,096)   +8  SEQ
//   +12 + 8k  segment k's cycles, then its passes
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16fe40 (L1 block 1, byte 0x2dfc80).
//
// DM (byte addresses, L1 block 1, zero at boot):
//   0x2dfa40 .. 0x2dfa4c  the mark's saves: R8, R9, R10, I1
//   0x2dfa50  LAST: EMUCLK at the previous mark      0x2dfa54  CUR: the running record, 12k
//   0x2dfa58  BLOCKS     0x2dfa5c  PUBI: the next half, 0..129     0x2dfa60  SEQ
//   0x2dfa64 .. 0x2dfa78  the publisher's saves: R8, R9, R10, R11, I1, I0
//   0x2dfa80 + 12k  segment k's record: cycles, passes, a spare word (31 records)
//   0x2c49d8, 0x2c59d8  reply word 2 of the two reply pages

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
      IF NE JUMP 0x16ff14;              // -> wr_lm_send. (the window is still open)

      // a window closes: every 32nd one goes to SNAP first
      R9 = 0x1ffff;
      R9 = R8 AND R9;
      IF NE JUMP 0x16fefd;              // -> wr_lm_zero. (not a SNAP window)
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
      IF NE JUMP 0x16fedd;              // -> wr_lm_copy.
      R9 = R9 - R9;
      DM(0x2dfa5c) = R9;                // PUBI: the new SNAP from its first half

      // every window: the records start again from zero
.GLOBAL wr_lm_zero.;
wr_lm_zero.:
      I1 = 0x2dfa80;
      R8 = 31;
      R9 = R9 - R9;
.GLOBAL wr_lm_zrec.;
wr_lm_zrec.:
      DM(0, I1) = R9;
      DM(1, I1) = R9;
      R10 = I1;
      R11 = 12;
      R10 = R10 + R11;
      I1 = R10;
      R11 = 1;
      R8 = R8 - R11;
      IF NE JUMP 0x16ff03;              // -> wr_lm_zrec.

      // every block: one half of SNAP into reply word 2 (0 until the first SNAP)
.GLOBAL wr_lm_send.;
wr_lm_send.:
      R10 = R10 - R10;
      R9 = DM(0x2dfa60);                // SEQ
      R9 = PASS R9;
      IF EQ JUMP 0x16ff57;              // -> wr_lm_put. (no SNAP yet)
      R8 = DM(0x2dfa5c);                // i
      R10 = LSHIFT R8 BY -1;
      R10 = LSHIFT R10 BY 2;
      R11 = 0x80780000;
      R10 = R10 + R11;
      I0 = R10;
      R10 = DM(0, I0);                  // SNAP word i >> 1
      R11 = 1;
      R11 = R8 AND R11;
      IF EQ JUMP 0x16ff37;              // -> wr_lm_low.
      R10 = LSHIFT R10 BY -16;          // i odd: the high half
.GLOBAL wr_lm_low.;
wr_lm_low.:
      R11 = 0xffff;
      R10 = R10 AND R11;                // HALF
      R11 = 0x3f;
      R9 = R9 AND R11;
      R9 = LSHIFT R9 BY 8;
      R9 = R9 OR R8;
      R11 = 0x8000;
      R9 = R9 OR R11;                   // TAG
      R10 = LSHIFT R10 BY 16;
      R10 = R10 OR R9;                  // halves swapped: the ColdFire reads TAG << 16 | HALF
      R11 = 1;
      R8 = R8 + R11;
      R11 = 130;                        // halves: 2 x (3 + 2N)
      COMP(R8, R11);
      IF LT JUMP 0x16ff54;              // -> wr_lm_keep.
      R8 = R8 - R8;
.GLOBAL wr_lm_keep.;
wr_lm_keep.:
      DM(0x2dfa5c) = R8;                // PUBI
.GLOBAL wr_lm_put.;
wr_lm_put.:
      DM(0x2c49d8) = R10;               // reply word 2, both pages
      DM(0x2c59d8) = R10;

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
