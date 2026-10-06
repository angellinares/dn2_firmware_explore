// load.asm -- command 4: a chunk of a table, from the ColdFire's frame into DDR.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in).
//
// The per-frame handler (sw 0x1c9d6b) reads the command at the received frame's first
// short word and jumps through its table. The build moves that table to 0x2dfa00 with
// eight entries and lets commands 0..7 through (stock: 0..3, anything else case 0's
// code); entry 4 is this. A load frame carries no parameters:
//
//   word 0   4 | count << 16      count = payload words, 1..668
//   word 1   destination          a byte offset into the load area, 4-aligned
//   word 2   sequence             echoed when the chunk is accepted
//   word 3   checksum             the payload words' sum, mod 2^32
//   word 4.. payload
//
// The chunk goes to DDR at LOAD_AREA + destination when it lies inside the area. Then
// the frame renders as if it were the frame before it: the per-block routine's own
// copy of the last frame (0x25c48c, which sw 0x1c2712 refreshes from its argument
// before it unpacks) becomes the argument, and this jumps to case 3 (sw 0x1c9f0f), the
// stock render. So the audio of a load frame is the audio of a repeated frame.
//
// The answer goes to reply word 6 (+0x18), both pages, halves swapped like reply
// word 0, so the ColdFire reads it at 0x800053bc as the sequence it sent:
//   the sequence            the last chunk written with a matching checksum;
//   the sequence ^ 1 << 31  the last chunk refused (bounds or checksum).
// Word 6 is the one reply word nothing else uses: words 1-4 are idle_load.asm's
// timing totals (which overwrote the answers here until 2026-10-05, on the
// instrument), +0x16 is the compressor's gain reduction, and from +0x1c the reply is
// the ColdFire's audio and per-voice records (0x400277ae, 0x4002540e). It read 0 in
// 70 samples on the instrument, idle and playing (tools/dn2replyscan.py). A chunk
// whose checksum fails was still written: the ColdFire sends it again.
//
// In, from the dispatch: I3 = the received frame (a byte address), R1 = R15 << 8,
// R15 = the bank word, R14 = the handler's start cycle. Uses R0, R2, R8, R10, R11,
// R12, R13 and I0, and leaves R0 = 8, R11 = 8, R12 = 2, R13 = 4 as the dispatch set
// them for case 3 (sw 0x1c9da2..0x1c9dbd). Keeps R1, R3-R7, R9, R14, R15. Only forms
// the firmware itself uses; every add has R8-R15 first; no DO loop.
//
// PLACEMENT IS FIXED at PM sw 0x16fb00 (DM 0x2df600): the absolute jumps are written
// for it by scripts/sharc_resolve_jumps.py.
//
// DM (byte addresses):
//   0x2dfa20  the sequence, while the chunk is copied
//   0x2dfa24  the checksum it should have
//   0x2c49e8, 0x2c59e8  reply word 6, both pages

.SECTION/PM seg_pmco;

.GLOBAL wr_load.;
wr_load.:
      R13 = 4;
      R8 = I3;                          // the frame
      I0 = R8;
      R2 = DM(0, I0);                   // word 0
      R11 = LSHIFT R2 BY -16;           // count
      R8 = R8 + R13;
      I0 = R8;
      R12 = DM(0, I0);                  // word 1: the destination
      R8 = R8 + R13;
      I0 = R8;
      R10 = DM(0, I0);                  // word 2: the sequence
      DM(0x2dfa20) = R10;
      R8 = R8 + R13;
      I0 = R8;
      R10 = DM(0, I0);                  // word 3: the checksum
      DM(0x2dfa24) = R10;
      R8 = R8 + R13;                    // the payload

      // 1 <= count <= 668
      R0 = 1;
      COMPU(R11, R0);
      IF LT JUMP 0x16fb78;              // -> wr_load_refuse.
      R0 = 668;
      COMPU(R11, R0);
      IF GT JUMP 0x16fb78;              // -> wr_load_refuse.
      // the destination 4-aligned and inside the area (2 MiB + 4 KiB), and its end too;
      // the start is tested on its own, so a destination near 2^32 can't wrap the end
      R0 = 3;
      R2 = R12 AND R0;
      IF NE JUMP 0x16fb78;              // -> wr_load_refuse.
      R0 = 0x201000;
      COMPU(R12, R0);
      IF GE JUMP 0x16fb78;              // -> wr_load_refuse.
      R2 = LSHIFT R11 BY 2;
      R2 = R12 + R2;                    // the end
      COMPU(R2, R0);
      IF GT JUMP 0x16fb78;              // -> wr_load_refuse.

      R0 = 0x807ff000;                  // the load area: the pool directory, then the tables
      R12 = R12 + R0;
      R10 = R10 - R10;                  // the sum
      R0 = 1;
.GLOBAL wr_load_word.;
wr_load_word.:
      I0 = R8;
      R2 = DM(0, I0);
      I0 = R12;
      DM(0, I0) = R2;
      R10 = R10 + R2;
      R8 = R8 + R13;
      R12 = R12 + R13;
      R11 = R11 - R0;
      IF NE JUMP 0x16fb4f;              // -> wr_load_word.

      R2 = DM(0x2dfa24);
      COMP(R10, R2);
      IF NE JUMP 0x16fb78;              // -> wr_load_refuse.
      R2 = DM(0x2dfa20);
      R10 = LSHIFT R2 BY 16;
      R2 = LSHIFT R2 BY -16;
      R10 = R10 OR R2;                  // halves swapped, as reply word 0
      DM(0x2c49e8) = R10;               // reply word 6, both pages: accepted
      DM(0x2c59e8) = R10;
      JUMP 0x16fb8c;                    // -> wr_load_render.

.GLOBAL wr_load_refuse.;
wr_load_refuse.:
      R2 = DM(0x2dfa20);
      R10 = LSHIFT R2 BY 16;
      R2 = LSHIFT R2 BY -16;
      R10 = R10 OR R2;
      R2 = 0x8000;                      // the ColdFire's bit 31, in the swapped halves
      R10 = R10 XOR R2;
      DM(0x2c49e8) = R10;               // reply word 6, both pages: refused
      DM(0x2c59e8) = R10;

.GLOBAL wr_load_render.;
wr_load_render.:
      // case 3 with the frame before this one: what the dispatch leaves it, and the
      // per-block routine's copy of the last frame as the frame
      R0 = 8;
      R11 = 8;
      R12 = 2;
      R13 = 4;
      I3 = 0x25c48c;
      JUMP 0x1c9f0f;                    // the stock render (case 3)
.wr_load..end:
