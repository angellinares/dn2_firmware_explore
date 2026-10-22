# loadmap: where the SHARC's frame goes, stage by stage

`loadmap` is a diagnostic build. It measures, on the instrument, how many cycles each stage of the DSP's frame takes: stock's stages and Waverider's. It changes no sample. Build it only when a measurement needs it. It is not a release.

## Why

The load plan (vault, 2026-10-21) estimates Waverider's stages with the runner's cycle model. The model runs one voice with a cold cache. It does not see L1 block conflicts, the branch predictor or IIR0's time, so it cannot say what the silicon does. `loadmap` measures the same split on the unit, in one flash.

## How it works

- **Marks.** The build sends chosen jumps and calls through a 12-byte stub: `CALL wr_lm_mark; JUMP <the original target>`. `wr_lm_mark` reads EMUCLK, adds the cycles since the previous mark to the running segment's record, and makes this mark's segment the running one. Segment k runs from mark k to the next mark.
- **No trace.** A mark saves and restores every register it uses, and ASTAT and MODE1 with `PUSH STS`. It runs in SISD with no ALU saturation.
- **Its own cost.** Every segment's cycles include one mark per pass. Segment `null` is two marks back to back, so it measures that cost. The reader subtracts it.
- **Windows.** A window is 4,096 blocks (2.7 s). At the end of each window the publisher zeroes the 31 records. At the end of every 32nd window (131,072 blocks, 87 s) it first copies them to SNAP in DDR. SNAP then stays the same for 87 s.
- **Publishing.** Every block the publisher writes one half of SNAP into reply word 2 of both reply pages, the next half each block. The ColdFire reads `TAG << 16 | HALF`, with `TAG = 0x8000 | (SEQ & 0x3f) << 8 | i` for half i (0 to 129). Until the first SNAP the word is 0. The word replaces `block_count.asm`'s count, so `dn2sharc_load.py --peak` has no window clock on this build. `--frame-max` reads words 3 and 4 and still works.
- **Why not the reply rows.** Until 2026-10-22 the pages went to entries 11 and 12 of slot rows 1 to 12, at +0x44 and +0x48. On the DN2 the record's 32 rows are the 32 samples of the block, with 28 channels of 24 bits each (`docs/waverider-pages34.md`). Bytes 68 to 75 of a row are channels 22 to 25: the effects buses. The row check on the unit read 0 idle and changing values on all 12 rows while a pattern played. So the build would have written over the effects buses' audio.

## The marks

| # | segment | from |
|---|---|---|
| 0 | `emark` | the handler's call of the per-block routine (our entry-mark JUMP) |
| 1 | `dispatch` | the routine's call of the machine dispatch, `CJUMP 0x1c8ef1` at sw `0x1c3044` |
| 2 | `splice` | our splice JUMP at sw `0x1c9448`: `block_count.asm` |
| 3 | `null` | `block_count.asm`'s way on: one mark's cost |
| 4 | `publish` | the publisher |
| 5-21 | `w_*` | Waverider's voice loop: entry, track header, page 5's setup, an oscillator's parameters, MOVE, the gain and pitch, page 5's phase pass, DCLK, the reader, between the oscillators, page 5's shapers, the Formant, the sub, the noise, the next track, the last voice's IIR0 wait, the exit |
| 22-26 | `t_*` | the dispatch's per-track calls after Waverider: `0x1cdb56`, `0xb80c39`, `0xb81368`, `0xb82342`, `0xb80345`, 16 each |
| 27-29 | `s_*` | the routine's calls after the dispatch: `0x1c1738`, `0x1c1f1e`, `0x1c244d` |
| 30 | `s_tail` | the call `0x1ca84e`: the routine's end, the handler's rest, other tasks and the idle time |

The stock sites come from a trace of one block in digikit's runner (2026-10-21). In instructions, the routine runs about 17,000 before Waverider and about 136,000 after it. `s_tail` holds the idle time, so the segments together fill the frame.

## Build it

1. Make the plan, after any change to Waverider's DSP objects:

   ```
   python scripts/build_loadmap.py --assemble
   ```

   This assembles `csrc/waverider/sharc/loadmap.asm` and writes `src/dnfw/waverider/loadmap_code.json`. The plan records the Waverider stream it was made on. A build refuses any other stream.
2. Build the firmware with the variable set:

   ```
   DNFW_WAVERIDER_LOADMAP=1 dnfw mods apply IMAGE -o OUT.syx --mod ... --mod waverider --mod usbprobe
   ```

## Check it

```
python scripts/sharc_loadmap_check.py
```

This runs four blocks on the plain stream and on the `loadmap` stream, in the Python runner. EMUCLK is fed the count of instructions run, so a segment's cycles are its instructions. On 2026-10-21 (batch A), all seven checks passed. On 2026-10-22, with the publisher on reply word 2, all seven passed again:

- Both runs end, and every track buffer of every block is the same, bit for bit.
- The registers at every stage's target are the plain run's.
- Each segment's instructions, less one mark per pass, equal the plain run's between the same targets. A mark is 34 instructions. `s_tail` crosses the harness's own setup between blocks, so this check leaves it out.
- A SNAP window closes, and SNAP holds the header. In block k, reply word 2 of both reply pages holds half k of SNAP, tagged with SEQ 1.

The Waverider gates also run on the `loadmap` stream: set `DNFW_WAVERIDER_LOADMAP=1` before running them.

## Read it

```
python tools/dn2loadmap.py --save out/loadmap/LABEL.json
```

Quit Transfer first. The tool reads reply word 2 with a 4-byte PEEK until it has every half of one SNAP, each half seen twice with the same value. It then prints, per segment, the passes and cycles per block and the cycles of one pass. It also prints the share of a frame (666,667 cycles), with and without the marks.

The first SNAP comes 87 s after boot. One SNAP needs several hundred reads, so the tool prints the read rate. If a SNAP changes before the tool has every half, the tool starts again on the next one. `--for` sets the time limit (default 240 s).

## Before the first flash

The first version (`loadmap1`) published through the reply rows. The row check on the unit failed on 2026-10-22, so `loadmap1` must not be flashed. Reply word 2 carried the accelerator probe's 182 halves on the unit on 2026-10-17 (`docs/sharc-accelerators.md`), so this route is proven on the DN2. The owner still listens for added noise after the flash.

## Cost

A mark is 34 instructions. With 16 Waverider voices the build runs about 410 marks a block: about 14,000 instructions, likely 2 to 3 points of a frame. The reader subtracts the marks.

The publisher is 55 instructions in a block where no window closes (measured in the runner, 2026-10-22). When a window closes, zeroing the records adds about 310 instructions. A SNAP adds about 450 more. Those two figures are estimates. The publisher's cost is in its own segment.
