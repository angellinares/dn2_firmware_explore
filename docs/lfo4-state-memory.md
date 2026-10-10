# LFO4's state arrays: where they were, what it cost, where they are now

Found 2026-10-10, fixed 2026-10-11. The investigation is in `docs/song-rows-report.md`
(branch `fix/lfo4-sound-reset`); this is what the code rests on.

## What went wrong

LFO4 gives each track a fourth LFO, so the evaluators' three state arrays grow from 48
records to 64 (2,560 bytes each) and no longer fit where stock keeps them. From
`5f8310c` (2026-09-17) they sat at `0x46700000`, `0x46701000` and `0x46702000`, on the
premise that stock uses no RAM above its data (`0x466b74d0`).

Stock does. It keeps a DMA section at RAM `0x466b8000..0x46701340` and names it only
through an uncached window 0x08000000 higher, `0x4e6b8000..0x4e701340`
(`ACR0 = 0x4007e020`, set at `0x40000564`, caches `0x40000000..0x47ffffff` only). The
section holds the eMMC driver's 64 KiB bounce buffer at `0x4e6f1300`, which is RAM
`0x466f1300..0x46701300`. LFO4's live array was its offset `+0xed00..+0xf700`.

- eMMC write `0x4012c780(sector, bytes, buf)` and read `0x4012c59a` work in pieces of at
  most 65,536 bytes. A buffer that is not 16-byte aligned goes through the bounce:
  `memcpy(0x4e6f1300, buf, n)` at `0x4012c85e` before the DMA on a write,
  `memcpy(buf, 0x4e6f1300, n)` at `0x4012c754` after it on a read.
- The project images are unaligned (`0x405cd96c`, and the slot cache `0x42c71a8c`), so
  every piece of a project passes through the bounce from offset 0.
- On a save the evaluator wrote the live LFO state into the piece before the DMA ended,
  and the card received it. On a load the same landed in RAM. Each piece also overwrote
  the live LFO state.

**The cost:** every project saved or loaded on a unit running LFO4 carries LFO state at
`+0xed00..+0xf700` of every 64 KiB of its 12,890,116-byte image, 196 windows, about half
of the bytes under each window replaced. Measured in rivvi's AM REBECCA and the owner's
SKETCHPAD and project 11; absent from 1.10E exports and fresh 1.11 projects.

**Why no check saw it:** `0x466f1300` appears nowhere in the image, only `0x4e6f1300`
(six literals, `0x4012c644` to `0x4012c85a`). The scans read `0x46......`, and the
emulators do not map the window onto the same RAM, so a watch on `0x466f....` reads
zeros while the data sits at `0x4e6f....`.

## Where the arrays are now

In the first block of stock's own heap, so stock itself records the memory as taken.

- Stock's allocator (`0x4011ffe8`) is one buddy arena: 32 MiB from `0x4464abf0`, 16-byte
  blocks, its descriptor at `0x4029eb9c`. It initialises on its first call.
- `reserve` (`scripts/build_lfo4_tick.py`, in LFO4's cave) is hooked at the end of that
  initialisation (`0x4012006a`). It runs once a boot, inside the allocator's mutex, which
  is recursive (`0x40001608`), so nothing can allocate before it. It requests 0x3000
  bytes, which the allocator makes a 16 KiB block, and clears them.
- The first block of a fresh arena is its base for any size (run in the emulator from a
  cleared arena: 16 bytes, 7,680, 8,192, 65,536 and 1 MiB all return `0x4464abf0`, and no
  later request overlaps it). So the arrays have fixed addresses: live `0x4464abf0`,
  second `0x4464bbf0`, backup `0x4464cbf0`.
- If the block is anywhere else, `reserve` stops on an illegal instruction, which the
  firmware reports on the screen. The unit never runs with the arrays in the wrong place.

The 32 MiB arena is the part of the ColdFire's 128 MB that stock hands out on request;
most of stock's memory is fixed areas. LFO4 takes 16 KiB of it, 0.05 %.

## What checks it

| check | what it shows |
|---|---|
| `dnfw.mods.ramcheck.in_stock_dma`, `test/test_mods_ramcheck.py` | no mod declares or names anything in `0x466b8000..0x46701340` or its window; the old LFO4 placement is refused (control). The USB probe names two of stock's audio buffers there to read them (`READS_STOCK_DMA`) |
| `boot_gate.exe BUILD --watch` | the build boots; `reserve` runs once (`0x402dfb58`, at instruction 26,286,686, the allocator's first call), reaches its jump back, and the illegal instruction is not reached |
| `scripts/emu_lfo4_state_memory.py BUILD --stock STOCK` | the first block is the arena's base and goes to `reserve`; none of the 4,095 later blocks recorded lies in the arrays' 16 KiB; a marker written to the arrays is intact after SAVE PROJECT AS (591 eMMC writes) and absent from the bounce buffer. On stock the same first block goes to stock's own caller |
| `scripts/emu_boot_engine.py --build out/lfo4-heap1` | boot from reset, then evaluator A and a sound through LOAD and SAVE |

## Not verified

- On the instrument: that `0x4e6f1300` and `0x466f1300` are one RAM. Stock's own use of
  the window and the exact offset of the damage in the files say so.
- On the instrument: the fixed build itself. The test is a project round trip through
  DNX with LFO4 running (send, SAVE PROJECT, read back, compare; then the 196 windows).
- The emulators still do not fold the window. Until they do, an emulator null on
  "does stock write here" is weak for any address in `0x466b8000..0x46701340`.
- Stock's peak use of the arena. It does not matter for 16 KiB; it would for megabytes.

## The RAM above the section, where the other mods live (2026-10-11)

The question: does stock reference `0x46701340..0x48000000`, directly or through another
address? The SDRAM is 128 MB and its decode repeats it every 0x08000000, so the same RAM
answers at nine addresses up to `0x8c000000`; each check below covers all nine.

| check | result |
|---|---|
| `scripts/emu_high_ram_touch.py` on plain stock: boot, SAVE PROJECT AS three times, a walk through every page key, the preset menu, pattern, song, play, record and stop; then the emulator's own list of every 1 MiB page the guest touched | 88 pages. In the first window the highest is `0x46600000`; in the second only `0x4e600000` and `0x4e700000`, first written at `0x4e700000` by memcpy (`0x401344ac`, the bounce buffer's tail), its non-zero bytes all below `+0x1340`. No page of the range in any other window. Controls: `0x46600000` and `0x4e600000` are in the list |
| `digikit-up/tools/refscan.py`, stock code `0x40000400..0x401d0000`, 99.94 % of bytes decoded, one scan per window | control: the bounce buffer's six sites are found. Hits in the nine ranges: `0x47efffff` twice (the high word of a double, with `0xe0000000` beside it), `0x4ead99ff` (a timeout compared with a timer count), `0x4f000000` twice and `0x7ff00000`, `0x7fffffff` (float constants and limits), `0x474e5543` ("GNUC"), `0x47f94003` and `0x6ea42090` (not addresses: an instruction pair read as one, and an added constant). No reference |
| stock data from `0x401d0400`: every value in the nine ranges beside a valid pointer | 3,862: 2,643 text, 23 the halves of two neighbouring pointers, 1,196 inside tables of numbers and packed data. No pointer table holds one. The 1,196 were not read one by one |

**What this does not show.** An address computed at run time, on a path the emulator did
not run (the sequencer, the full audio path, USB audio, a transfer). The page list is per
megabyte. Nothing here was measured on the instrument.

## Other mods

No other mod's memory overlaps the section (`in_stock_dma` on every registered mod), and
no stock reference above `0x4e701340` was found under either address. Their RAM above
`0x46701340` is still chosen by hand and declared (`ram()`); moving it into the arena is
a separate change.
