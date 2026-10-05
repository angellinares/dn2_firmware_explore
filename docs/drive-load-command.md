# Loading tables at run time: the DSP's load command

**Goal.** Tables, and later samples, come from the +Drive at run time
(`docs/waverider-tables.md`), not from section 7. Section 7 is capped by the
ColdFire's DSP loader at 1 MiB (`0x400cf5ac`, `0x400cf5e4`); past it the DSP never
boots. The only path from the ColdFire to the DSP while it runs is the per-frame SPI
exchange: 2,688 bytes out and 2,748 back, 1,500 times a second. This is the DSP half
of using that path for data. **[E]**, runner only: nothing here has run on silicon.

## What the per-frame handler does (DN2 1.11, read 2026-10-04)

`sw 0x1c9d6b`, the engine task's loop body:

- **The two pages.** It calls `0x1ca020` for the receive page
  `p1 = 0x2c29d0 + (DM(0x2c0450) << 12)` and the reply page `p2`.
- **The command.** It reads the command, the first short word of `p1`:
  `r2 = dm(m5,i3)(sw)`. The instrument's frame starts `0x0003`, read by the probe
  (`out/probe-frames`).
- **The bound.** `r1 = lshift r2 by -2` (sw `0x1c9daa`). Any command of 4 or more
  branches to case 0's code (`if not sz`, sw `0x1c9daf`).
- **The jump.** Otherwise it jumps through the table `i4 = 0x268a68` (sw `0x1c9d9f`).
  The table has four entries; the string "Audio Task" follows it.

| command | stock target | what it does |
|---|---|---|
| 0 | `0x1c9dc2` | silence: clears the output |
| 1 | `0x1c9e76` | a variant of 0 |
| 2 | `0x1c9eda` | loopback: copies input to output |
| 3 | `0x1c9f0f` | **render** |

**Case 3, the render.** In order:
1. It converts the block's audio input, banked by `DM(0x268a38)`, through `0x1c9d00`.
2. It calls the per-block routine `0x1c2712` from sw `0x1c9fbc` with `R12 = I3`, the
   received frame. That routine first copies the frame to **`0x25c48c`**, then
   unpacks it.
3. It converts the output back (`0x1c9d3f`).
4. It jumps to the common tail (sw `0x1c9e44`). The tail writes the cycle count to
   reply word 0, flips the bank word `0x268a38` and returns.

So **`0x25c48c` always holds the previous frame**. That is what makes a load frame
cheap.

## The load command

A frame whose command is 4 carries data, not parameters. Its words, as the DSP reads
them (little-endian 32-bit; DSP word k is the ColdFire's 16-bit words 2k and 2k+1,
low half first):

| word | content |
|---|---|
| 0 | `4 \| count << 16`, count = payload words, 1..668 |
| 1 | destination: a byte offset into the load area, 4-aligned |
| 2 | sequence, echoed on acceptance |
| 3 | checksum: the payload words' sum, mod 2^32 |
| 4.. | payload, up to 668 words (2,672 bytes) |

**`load.asm`** (sw `0x16fb00`, DM `0x2df600`):
1. **It checks the bounds:** a count of 1..668, and a destination 4-aligned, below
   2 MB, with its end inside the area.
2. **It copies the payload** to **DDR `0x80800000 + destination`** and sums it.
   The load area is `0x80800000..0x80a00000`, the top 2 MB of Waverider's DDR
   region; the baked tables keep `0x80600000..`.
3. **It acknowledges** in reply bytes the ColdFire never reads (`docs/sharc-load.md`),
   on both pages, halves swapped like word 0:
   - **reply word 3 (`+0x0c`):** the sequence of the last chunk written whose sum
     matched;
   - **reply word 4 (`+0x10`):** the sequence of the last chunk refused, for bounds or
     checksum. A chunk with a bad sum is still written; the ColdFire sends it again.
4. **It renders** by setting `I3 = 0x25c48c` and jumping to case 3. The block renders
   from the previous frame, so the audio of a load frame is the audio of a repeated
   frame.

**The dispatch** takes commands 0..7 through a table moved to DM `0x2dfa00`:
- two one-field patches:
  - `i4 = 0x268a68` becomes `i4 = 0x2dfa00` (`140f2600688a` to `140f2d0000fa`);
  - `lshift by -2` becomes `-3` (`3e02007812fe` to `…12fd`, stock's sign bits kept);
- the moved table's entries: 0..3 stock, 4 `load.asm`, 5..7 case 0's code, which is
  what stock does for any command of 4 or more.

Selmap reads both patched instructions as `i4=0x2dfa00` and `r1=lshift r2 by -0x3`,
and every instruction of `load.asm` as its source line.

## The gate: `scripts/sharc_load_command.py`, PASS 6/6 (2026-10-04)

From the Milestone 2 post-init snapshot, on Waverider's section 7.

**Part 1: the real handler, to the render call.**

| frame | result |
|---|---|
| a load frame | `load.asm` ran; the chunk is in DDR; word 3 = the sequence; `R12 = 0x25c48c` at the render call |
| a bad checksum | chunk written; word 4 = the sequence; word 3 untouched |
| a destination past the area | nothing in DDR; word 4 |
| a render frame | stock: `R12` = the receive page |
| command 5 | case 0's code |

**Part 2: the render from the copy.** Two direct calls of `0x1c2712` on an
instrument frame with track 0 triggered. The control repeats the frame. The test's
second call takes `R12 = 0x25c48c`. Of the 4,760 bytes the second call writes, all
match except four stack words: pointers into the frame, at the same offset from the
two frames' bases.

**A runner gap, not ours.** Entered through case 3 (the real handler), the render ends
with `I6 = 0` and halts at its return ("return target 0x1"). The stock image behaves
the same. The other gates call the render directly. So part 1 stops at the call, and
part 2 calls it directly. A candidate finding for digikit, not yet traced.

## The trigger masks are one-frame events (instrument, 2026-10-05)

`tools/dn2trigmask.py` polled frame bytes 34..41 of the live frame (`0x80005e60`)
over the USB probe, about 345 readings a second, for 60 s
(`out/probe-frames/trigmask_run2.*`):

| phase (owner) | what the masks showed |
|---|---|
| track 1 playing, a trig on all 16 steps, 120 BPM (0-27 s) | 1-6 caught a second, a single bit each, the bit moving through all 16 positions |
| STOP, then the trig key (28-43 s) | one capture at a key press (+34 = `0001`, 34.5 s), then zero |
| taps, the last one held for at least 10 s (44-60 s) | on and off caught apart for the taps (`0020` on at 44.69 s, off at 44.78 s, and so on); the held note's onset at 50.33 s (`0004`), then zero until the end |
| the whole idle run before (45 s) | zero in all 15,533 readings |

- **No mask is a held gate.** A held note shows only its onset. Loading does not need
  to pause while a note is held.
- **+34 is the note-on mask and +36 the note-off mask.** +38 always equals +34 and +40
  always equals +36, in all 20,674 readings. Each event is caught at about the rate a
  one-frame event would be (a 0.67 ms frame against a reading every ~2.9 ms).
- **The bit is not the track.** With only track 1 playing, the bit cycles through all
  16 positions, one step to the next, and a note's off bit is its on bit. It looks
  like a voice index. `dnfw.waverider.frame` says "bit t = track t". That holds for
  the single-voice frames our gates build. **[unverified]**: what the DSP indexes by
  this bit.

So the rule stands as written: **replace a frame only when it and the frame before it
have all four masks at zero.** At 8 notes a second that leaves almost every frame free.

## Open, before the ColdFire half

1. ~~Which frames a load frame may replace.~~ Measured above.
2. **The ColdFire half.**
   - The +Drive reader (`WR_DRIVEREAD` proved the sector reads) fills a chunk queue
     from the UI task.
   - The frame ISR (`0x40025e36`; the send at `0x40025e9e`) swaps an allowed frame
     for the next chunk.
   - It watches reply words 3 and 4 and resends what is not acknowledged. The
     ColdFire may slip frames: digikit's two-frame DMA slip.
3. **Where Waverider finds a loaded table.** The directory (`0x2de600`) names table
   addresses. A loaded table needs either an entry there (a load into L1, outside this
   area), or a directory in DDR. A design choice for the +Drive manager step.
4. **Throughput.** 2,672 bytes a frame is 4 MB/s at every frame, far beyond need. A
   16 KB table is 7 frames; a Tonverk-size 256 KB table is 99 frames, a fifteenth of a
   second.
