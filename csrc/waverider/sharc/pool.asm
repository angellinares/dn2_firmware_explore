// pool.asm -- a table slot past the baked directory, looked up in the load area's pool.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in).
//
// The ColdFire loads tables from the +Drive into the load area (load.asm, command 4),
// then writes the pool directory there last, in the area's first 4 KB (the area starts at
// 0x807ff000, so the 128 tables keep 0x80800000 + 16 KiB x j):
//
//   0x807ff000  magic 'WRP1' (0x57525031)
//   0x807ff004  count, the entries that follow (128)
//   0x807ff008  entry[j]: the DDR address of pool table j, or 0 for none
//
// A pool table has the baked tables' layout (16 frames x 512 int16, frame-major,
// little-endian as the reader reads them). The boot stream writes the directory's
// first bytes as zeros, so until the ColdFire has written one no pool slot plays.
//
// The loop (machine9_live.asm) jumps here when SLOT is at or past the baked
// directory's count. Slot j = SLOT - count is the pool's entry j. A pool entry that
// is there jumps back to wr_t5v_pooled with its address in R2; anything else (no
// directory, j past its count, an empty entry) jumps back to wr_t5v_slot_ok with
// R1 = 0, which plays baked slot 0, as an out-of-range slot did before the pool.
//
// In: R1 = SLOT, R2 = the baked count (R1 >= R2). Uses R1, R2, R12, I1, as the loop
// does around the call. Only forms the firmware itself uses; every add has R8-R15
// first.
//
// PLACEMENT IS FIXED at PM sw 0x16fe00 (DM 0x2dfc00): the absolute jumps are written
// for it by scripts/sharc_resolve_jumps.py.

.SECTION/PM seg_pmco;

.GLOBAL wr_pool.;
wr_pool.:
      R12 = R1 - R2;                    // j (three registers: no 16-bit form)
      R2 = DM(0x807ff000);              // the pool directory's magic
      R1 = 0x57525031;                  // 'WRP1'
      COMP(R2, R1);
      IF NE JUMP 0x16fe27;              // -> wr_pool_none.
      R2 = DM(0x807ff004);              // its count
      COMPU(R12, R2);
      IF GE JUMP 0x16fe27;              // -> wr_pool_none.
      R12 = LSHIFT R12 BY 2;
      R1 = 0x807ff008;
      R1 = R12 + R1;
      I1 = R1;
      R2 = DM(0, I1);                   // entry[j]
      R2 = PASS R2;
      IF EQ JUMP 0x16fe27;              // -> wr_pool_none.
      JUMP 0x16ee17;                    // -> wr_t5v_pooled.

.GLOBAL wr_pool_none.;
wr_pool_none.:
      R1 = R1 - R1;                     // slot 0
      JUMP 0x16ee0b;                    // -> wr_t5v_slot_ok.
.wr_pool..end:
