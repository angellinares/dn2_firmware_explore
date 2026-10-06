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
3. **It answers** in **reply word 6 (`+0x18`)**, on both pages, halves swapped like
   word 0, so the ColdFire reads it at `0x800053bc`:
   - **the sequence** of the last chunk written whose sum matched;
   - **the sequence with bit 31 flipped** for the last chunk refused, for bounds or
     checksum. A chunk with a bad sum is still written; the ColdFire sends it again.

   Until 2026-10-05 the answers went to words 3 and 4. On the instrument they were
   never seen, because `idle_load.asm`'s timing totals overwrite those words on every
   idle pass. The runner gates missed it: the runner never runs the idle task. See
   "Where the answer goes", below.
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
| a load frame | `load.asm` ran; the chunk is in DDR; word 6 = the sequence; `R12 = 0x25c48c` at the render call |
| a bad checksum | chunk written; word 6 = the sequence, bit 31 flipped (refused) |
| a destination past the area | nothing in DDR; word 6 refused |
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
- **The bit is the voice, not the track.** With only track 1 playing, the bit cycles
  through all 16 positions, one step to the next, and a note's off bit is its on bit:
  the voice allocator handing each note the next voice. The owner reads it the same
  way, and it matches the per-voice engine elsewhere (`docs/modulation-mask.md`: the
  modulated sound parameters are per voice). `dnfw.waverider.frame` called it "bit t =
  track t"; that held only because our gates build single-voice frames, voice 0 on
  track 0. Not yet read on the DSP side: which per-voice cells the bit raises.

**Confirmed with unison (instrument, 2026-10-05).** Track 1 set to unison 3, a
1/16-length note on every step at 120 BPM, 20 s (`out/probe-frames/trigmask_unison3.*`):
every note-on caught (29) and every note-off caught (56) has **exactly three bits
set**, and the group changes from note to note (`8003`, `0b00`, `800c`, `40c0`, ...).
One note, three voices, three bits: the masks are voice masks. The earlier run's
three-bit values (`e000`, `1c00`) were the owner's first pattern, a three-note chord
on step 1. Note-offs were caught about twice as often as note-ons in the same notes,
so a note-off may stay in the mask for two frames; the rule below covers it either
way.

So the rule stands as written: **replace a frame only when it and the frame before it
have all four masks at zero.** At 8 notes a second that leaves almost every frame free.

## The pool: from the store to TBL (2026-10-05, both emulators)

**What plays.** TBL 0 and 1 are the baked tables. TBL 2 and up are the pool's:
TBL slot 2 + j is pool entry j.
- **The DSP** (`csrc/waverider/sharc/pool.asm`, sw `0x16fe00`): the loop jumps there
  for a slot at or past the baked directory's count.
  - It reads the **pool directory** at the load area's last 4 KB, `0x809ff000`:
    magic `WRP1`, count, then entry[j], pool table j's DDR address (0 for none).
  - Any miss plays slot 0, as an out-of-range slot did before: no directory, j past
    the count, or an empty entry.
  - The boot stream writes the directory's first 512 bytes as zeros. So nothing past
    slot 1 plays until the ColdFire has sent a directory.
- **Pool table j** lives at `0x80800000 + j x 16 KiB`. It has the baked tables' layout:
  16 x 512 int16, little-endian, frame-major. 127 tables fit below the directory.

**The ColdFire** (`csrc/waverider/pool.c` over `loader.c`, in the +Drive chunk at
`0x467f0000`, `dnfw.waverider.drive`). From the UI pass, 5 s after boot:
1. it reads the store's current index (`csrc/wrstore/store.c`, shared with the route);
2. it reads the working project's pool list (record 0, `csrc/wrstore/records.c`,
   `docs/for-dnx-waverider-pool.md`). Pool entry j is the list's entry j, when that
   store slot holds a table of that geometry; otherwise entry j is empty and plays
   slot 0. With no list, or an automatic one, the list is every slot of that
   geometry in slot order (the automatic pool, as before the lists). A table of
   another geometry stays stored and listed, but is not played;
3. it sends each table from the store's sectors, five sectors a chunk;
4. it sends the directory **last**.

Once the directory is acknowledged, the page offers TBL up to 1 + count, count being
the last entry in use + 1 (a gap is an unnamed slot):
- the limits getter (`wr_range`) and the value text (`wr_fmt`) read the page's own
  `wr_tbl_range` and `wr_tbl_names`;
- a pool slot is named by the first five characters of its name in the store;
- the wave display draws a pool table from spans that `pool.c` makes as its chunks
  pass (`0x46a00000`, as `dnfw.waverider.wave.pool_spans`).

After a write or a delete through `/waverider` (`wr_store.changes`), the next UI pass
fills the pool again: not 5 s later, but the next pass. The page reads the drive chunk
through its head (`wr_drive_head`, magic `WRDV`), so without that chunk TBL stays at
two tables.

**The exchange.** The frame hook (`0x40025e82`, `wr_frame_hook`) sends a chunk in
place of a frame:
- only when that frame and the one before it carry no note events (masks 34..41);
- one chunk in flight at a time;
- word 6's answer accepts it; a refused answer sends it again, and so does no answer within 24 frames;
- after 8 timeouts in a row the loader stops for good (`wr_load.failed`), and the pool
  reads failed, offering nothing.

**One description of the frames:** `dnfw.waverider.loadframes`. Three gates hold to it:

| gate | what | result |
|---|---|---|
| `scripts/sharc_waverider_pool.py` | load frames through the real handler into DDR, then type-5 render blocks. The cases: no pool (slot 0); the table and its directory (every chunk accepted, DDR holds the table, slot 2 plays it with the reader's pointer at pool entry 0, bit-exact to `dnfw.waverider.live`); slot 1 still baked; slot 3 past a pool of 1 (slot 0); an empty entry (slot 0) | **PASS 9/9** |
| `scripts/emu_waverider_pool.py` (Rust emulator, `panel_drive --card-extent`) | a store on the +Drive (slot 0 the pool test table, slot 3 the baked test table, slot 5 32 waves). The emulator runs no audio ISR (0 hits at `0x400cf7be` and `0x40025e82`), so the script calls `wr_frame_src` from the UI loop and acknowledges in reply word 6 as `load.asm` would. All 15 frames (2 x 7 chunks, then the directory) are the model's, byte for byte; the pool is ready with slots 0 and 3, named "Pulse" and "Saw t"; the spans equal the model's; a run never acknowledged gives up after 8 timeouts; after a write's mark (`wr_store.changes`) the pool fills again with the same frames, sequences going on (30 chunks acked, none resent) | **PASS 10/10** |
| the same frames, captured, into `sharc_waverider_pool.py --load-frames` | the ColdFire's own 15 frames through the DSP's handler: all accepted, both tables and the directory in DDR, slot 2 bit-exact to the reference | **PASS 9/9** |

Byte order is still a hypothesis until an instrument plays a table DNX wrote. Both
halves agree on it, but within one implementation.

### Where the answer goes (instrument, 2026-10-05)

On `waverider-pool1-usbprobe` the probe showed:
- the pool `failed`, after its one chunk (the empty store's directory) was sent 8
  times;
- reply words 3 and 4 climbing like timers, both idle and playing.

Those are `idle_load.asm`'s BEFORE and AFTER totals.

The bytes, as the probe read them on pool1 (HELLO `wrpool1`, 133.5 s after boot):

```
wr_pool  467f1de6  57 52 50 4c | 00 00 00 05 | 00 00 00 00 | 00 00 00 01 | 00 00 00 00 ...
                   'WRPL'       state 5         count 0       fills 1       generation 0 (no store)
wr_load  467f2294  57 52 4c 44 | 00 00 00 01 | 00 00 00 08 | 00 00 00 07 | 00 00 00 00 | 00 00 00 00 | 00 00 00 08 ...
                   'WRLD'       queued 1        sent 8        resent 7      acked 0       refused 0     timeouts 8
                   ... want_bytes 0x204, want_dest 0x1ff000 (the directory), done 0x204, failed 1
                   (done_bytes counts bytes read into the queue, not acknowledged: the
                   516-byte directory was queued; acked counts acknowledged chunks)
reply    800053a4  a first read of 32 bytes (words 0-7), then three of 24 (words 0-5),
                   a second or two apart:
                   00064f6f 0b9b72ab 00035a17 2d317df4 efcf5650 00000000 00000000 00000000
                   00064e59 b01bb42e 0003c95c 330dce89 39825d4a 00000000
                   00064edb b49a3b37 0003ca8d 331e2ce7 3d0c4409 00000000
                   000653aa b9459710 0003cbc9 332edea4 40b485c6 00000000
```

- Words 0 to 4 all climb between reads. Word 3 (`+0x0c`) and word 4 (`+0x10`) are
  `idle_load.asm`'s totals, not anything `load.asm` wrote.
- The directory chunk's answer would have read `4c440001`, or `cc440001` refused.
- Word 6 (`+0x18`) appears in the first read only, as `00000000`.
- The sixth column is word 5 (`+0x14..+0x17`): zero here, idle. It holds the
  compressor's gain reduction at `+0x16`, which moves while playing (the scan's
  played samples saw word 5 change). So that row's "no" means "in use while
  sound plays".

The retry-and-stop path worked as designed on its first contact with hardware: 8
timeouts, then stop, nothing written to the +Drive, and the sound untouched. That
bounded give-up is why this wrong build cost a reflash and not the store.

**Which reply words are free**, from `tools/dn2replyscan.py` (70 samples, idle and
playing) and a static read of every ColdFire site naming the reply. The scan samples
both states on purpose: word 5 is zero at rest and in use while sound plays, so an
idle-only scan would have offered it. Copy the method for the next field:

| reply bytes | what | free? |
|---|---|---|
| `+0x00` | the cycle count (reply word 0) | no |
| `+0x04..+0x13` | words 1-4: our idle total, block count and timing totals | no, ours |
| `+0x14..+0x15` | not read | half a word |
| `+0x16` | the compressor's gain reduction (`0x4002795c`) | no |
| **`+0x18..+0x1b`** | **word 6**: no code names it; 0 in every sample | **yes: the answer** |
| `+0x1c..` | records of 84 bytes, read from base `0x800053c0` (`0x400277ae`, `0x4002540e`), copied to the audio windows `0x4e6df100` | no (zeros there are quiet channels) |
| `+0xa9c..+0xabb` | MOVE's report (M10b-3) | no, ours |

`test_only_load_asm_writes_the_answer_word` checks that no other source of ours stores
to word 6.

**Not yet:**
- a table's own hash is not checked when it is loaded (the route checks it when the
  table is written);
- a refill rewrites tables in place while the old directory still names them;
- the pool list follows SAVE PROJECT AS and LOAD PROJECT, but not the project manager's
  copy, move or delete (`docs/for-dnx-waverider-pool.md`); CREATE NEW starts an empty list;
- one geometry only.

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
