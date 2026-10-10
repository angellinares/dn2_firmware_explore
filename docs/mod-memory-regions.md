# Where mod memory can live: the two regions, searched

2026-10-11. The search that found LFO4's bug (`docs/lfo4-state-memory.md`), repeated for
the region every other mod uses and for the alternative, stock's own heap. Each claim
names the run or the bytes behind it; what was not checked is listed at the end of each
part.

## The addresses of the RAM

The ColdFire has 128 MB of SDRAM at `0x40000000`. Its decode repeats the RAM every
0x08000000, so a byte answers at nine addresses up to `0x8c000000` (digikit's board maps
`0x40000000..0x8c000000` as RAM). `ACR0 = 0x4007e020` caches the first only. Stock reaches
its DMA section through the second (`0x4e......`). Every scan below covers all nine.

| RAM | what |
|---|---|
| `0x40000400..0x4030b980` | the image: code, constants, initial data |
| `..0x466b74d0` | stock's data. In it, `0x4464abf0..0x4664abf0`: the heap, 32 MiB |
| `0x466b8000..0x46701340` | stock's DMA section, named as `0x4e6b8000..0x4e701340` |
| `0x46701340..0x48000000` | **region A**, 25.0 MB: where the mods live |

## What the mods use

From each mod's own declaration (`ram()`), 2026-10-11:

| mod | bytes | where |
|---|---|---|
| waverider | 435,692 | `0x4670c000`, `0x467f0000`, `0x46a00000` |
| lfo4 | 30,664 | `0x46800000`, `0x46900000` (its state arrays, 7,680 bytes, are now in the heap) |
| arpplocks | 20,612 | `0x467c0000`, `0x467c8000` |
| lfowaves | 11,660 | `0x46740000`, `0x46750000`, `0x46780000` |
| arpmodes | 2,320 | `0x467a0000` |
| usbprobe | 2,304 | `0x46f00000` |
| reloadconfirm, midiarp, lfolength, layermidi, bootscreen | 2,801 | `0x46708000`, `0x467d0000..0x467f8000` |
| the platform's data window | 196,608 | `0x46710000` |
| **all** | **702,661** | 0.67 MiB of the 25.0 MB |

## Region A: `0x46701340..0x48000000`

**Does stock reference it, directly or through another address? Nothing found.**

| search | result |
|---|---|
| **What stock touches when it runs.** `scripts/emu_high_ram_touch.py` on plain stock: boot; SAVE PROJECT AS three times; a compressed project uploaded as DNX sends it (394 LZ4 decompress calls, 396 more eMMC writes); the saved project read as DNX reads it, compressed and raw (654 more eMMC reads); every page key, the preset menu, pattern, song, play, record, stop. Then the emulator's list of every 1 MiB page the guest touched (`panel_drive`'s `touched` step) | 88 pages. In the first window the highest is `0x46600000`. In the second, `0x4e600000` and `0x4e700000` only; the latter first written at `0x4e700000` by memcpy (`0x401344ac`, the bounce buffer's tail) and not zero only below `+0x1340`. No page of the region in any other window. Controls: `0x46600000` and `0x4e600000` are in the list |
| **What stock's code names.** `digikit-up/tools/refscan.py` over `0x40000400..0x401d0400`, 99.94 % of bytes decoded, once per window | control: the bounce buffer's six sites found. Hits in the nine ranges, each read: `0x47efffff` twice (a double's high word, `0xe0000000` beside it), `0x4f000000`, `0x7f800000`, `0x7ff00000`, `0x7fffffff` and their like (float constants and limits), `0x4ead99ff` (1,319,999,999, compared with a timer count at `0x400db9ce`), `0x474e5543` ("GNUC"), `0x6ea42090` (an added constant), `0x47f94003` (two instructions read as one). No address |
| **What stock's data holds.** Every value in the nine ranges in the data from `0x401d0400`: 25,450. A real pointer sits among pointers, so each was tested for a quarter or more of the 16 longwords around it pointing into the image | 115 pass, each read: nearly all are C++ type names beside their typeinfo pointers; the rest are glyph bitmaps, a table of limits (`0x7fffffff`), the first entry of the CRC-32 table (`0x77073096`) and fill bytes (`0x7f7f7f7f`). None is an address. Control: 11 real code pointers in `0x40100000..0x40101000` pass the same test. The 25,335 that fail it are text (2,643 of the first sample), halves of neighbouring pointers, and numbers in tables and packed data, about what random bytes give (1,763 beside one valid pointer expected, 1,196 seen) |

**Not shown.**
- An address computed at run time on a path the emulator did not run: the sequencer playing, the full audio path, USB audio, a project made on an older OS version.
- A touch finer than a megabyte in a page that stock also uses. Only `0x4e700000` is such a page, and its bytes were read.
- Anything on the instrument. One instrument result exists, on a Waverider build: project slot 25 read back identical (0 of 12,890,116 bytes) across a flash and a wavetable write while playing.

## Region B, the alternative: stock's heap, `0x4464abf0..0x4664abf0`

**How it works.** One buddy arena of 32 MiB in 16-byte blocks (`0x4011ffe8`, descriptor `0x4029eb9c`, a bitmap at `0x445a1e40`), behind a recursive mutex (`0x40001608`). It initialises on its first call. A request is rounded up to a power of two: a project image (12.9 MB) takes a 16 MiB block, half the arena.

**Who references it.** refscan on the arena's nine ranges: the control finds the allocator's nine uses of its descriptor; the hits in the arena's ranges are numbers (`0x46480000` a float, `0x454c4533` "ELE3", `0x45672351` and `0x85ebca77`/`0x85ebca87` hash constants, `0x55555555`, `0x7e000000` and float limits). Stock reaches the arena only through the allocator.

**What stock requests.** 2,234 calls name the allocator or its entries; 1,960 push a constant size. The large ones:

| size | sites | what |
|---|---|---|
| 12,889,620 to 12,890,132 | 5 factories, called at `0x400e2742`, `0x400e27f6`, `0x400e2896`, `0x400e2936`, `0x400e29d6` | the load of a project from an older OS version: each conversion step allocates one project-sized block, converts into it, copies it back (12,889,604 bytes) and releases it before the next. One at a time |
| 12,890,120 | `0x400f6b14`, `0x400f6c44`, `0x400f6d54` | the project save |
| 2.66 to 2.78 MB | 14 sites at `0x40189...` and `0x4012db64` | not read (the sound manager's area) |
| 2,097,152 x2, 1,048,576 x2 | `0x400cd880`, `0x400cf552` | the DSP uploader's two buffers at start-up among them |

**What taking the first block costs.** The first block of a fresh arena is its base for any size (run from a cleared arena: 16 bytes to 1 MiB all return `0x4464abf0`). On stock that first block goes to stock's own first request (return address `0x4018bc3a`), so the lower 16 MiB half is split from the first moment on stock too, and a project-sized request has only the upper half either way. Taking the block first moves stock's small blocks up by its size and nothing else.

| run | result |
|---|---|
| `scripts/emu_heap_requests.py`: boot, SAVE PROJECT AS, the DNX upload, the panel walk, on stock and on the fixed LFO4 build | stock 46,521 requests, 0 failed; fixed 46,394 requests, 0 failed; 987 eMMC writes and 394 LZ4 decompress calls on both. The only large site reached: the uploader's 1 MiB |
| `scripts/emu_lfo4_state_memory.py` | a marker in the arrays survives a save; the first block goes to `reserve`; none of the 4,095 later blocks recorded lies in it |

**Not shown.**
- Stock's peak use of the arena. The arena is cleared with stock's data at start-up and the allocator keeps its free lists inside it, so neither the touched pages nor the highest non-zero byte measure it (both read 32 MiB).
- The load of an older project, and the 2.7 MB requests: not reached in the emulator runs. If three or more 4 MiB blocks and a project-sized block were ever live at once, 16 KiB less in the lower half could be the difference. For 16 KiB that is unlikely; for 0.67 MiB it has to be measured first.
- The same on the instrument.

## The two regions side by side

| | region A, above the DMA section | region B, the heap's first block |
|---|---|---|
| Stock knows the memory is taken | no: it rests on stock never naming it | yes: the allocator records it |
| Evidence stock does not use it | no touch in the emulator scenario, no reference in code or data, under nine addresses | by construction, plus the runs above |
| What could break it | a computed address on a path not run | stock running short of heap |
| Cost to stock | none | the block's size out of 32 MiB |
| Addresses fixed at build time | yes | yes, the arena's base |
| In use by | every mod but LFO4's state | LFO4's state (16 KiB) |
