// pool.asm -- a table slot past the baked directory, looked up in build3's directory.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in).
//
// The ColdFire loads the pool's tables as they are stored into the load area (load.asm,
// command 4) and then their request directory; build3.asm builds each one's levels in
// the DSP's idle time and only then names it in its directory in L1:
//
//   0x2e4100  BUILT[j], j = 0 .. 127: pool entry j's table (dnfw.waverider.table3's
//             layout, bit 0 set: the reader's flag), or 0 for none (not built, being
//             rebuilt, or nothing there)
//
// The boot stream writes BUILT as zeros, so until a table is built no pool slot plays.
//
// The loop (machine9_live.asm) jumps here when SLOT is at or past the baked
// directory's count. Slot j = SLOT - count is the pool's entry j. A built entry jumps
// back to wr_t5v_pooled with its address in R2; anything else (j past 127, an entry 0)
// jumps back to wr_t5v_slot_ok with R1 = 0, which plays baked slot 0, as an out-of-range
// slot did before the pool.
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
      R2 = 128;
      COMPU(R12, R2);
      IF GE JUMP 0x16fe1c;              // -> wr_pool_none.
      R12 = LSHIFT R12 BY 2;
      R1 = 0x2e4100;
      R1 = R12 + R1;
      I1 = R1;
      R2 = DM(0, I1);                   // BUILT[j]
      R2 = PASS R2;
      IF EQ JUMP 0x16fe1c;              // -> wr_pool_none.
      JUMP 0x16ee17;                    // -> wr_t5v_pooled.

.GLOBAL wr_pool_none.;
wr_pool_none.:
      R1 = R1 - R1;                     // slot 0
      JUMP 0x16ee0b;                    // -> wr_t5v_slot_ok.
.wr_pool..end:
