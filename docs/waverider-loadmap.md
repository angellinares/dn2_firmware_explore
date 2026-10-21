# loadmap: where the SHARC's frame goes, stage by stage

`loadmap` is a diagnostic build. It measures, on the instrument, how many cycles each stage of the DSP's frame takes: stock's stages and Waverider's. It changes no sample. Build it only when a measurement needs it. It is not a release.

## Why

The load plan (vault, 2026-10-21) estimates Waverider's stages with the runner's cycle model. The model runs one voice with a cold cache. It does not see L1 block conflicts, the branch predictor or IIR0's time, so it cannot say what the silicon does. `loadmap` measures the same split on the unit, in one flash.

## How it works

- **Marks.** The build sends chosen jumps and calls through a 12-byte stub: `CALL wr_lm_mark; JUMP <the original target>`. `wr_lm_mark` reads EMUCLK, adds the cycles since the previous mark to the running segment's record, and makes this mark's segment the running one. Segment k runs from mark k to the next mark.
- **No trace.** A mark saves and restores every register it uses, and ASTAT and MODE1 with `PUSH STS`. It runs in SISD with no ALU saturation.
- **Its own cost.** Every segment's cycles include one mark per pass. Segment `null` is two marks back to back, so it measures that cost. The reader subtracts it.
- **Publishing.** Every 4,096 blocks (2.7 s) the publisher copies the 31 records to DDR and zeroes them. Every block it writes one 24-word page of that copy into the reply record. Each of slot rows 1 to 12 holds two words, at +0x44 and +0x48 of the row. Three pages hold one window. The page changes every 8 blocks.
- **The rows.** The rows are digikit's diagnostic block (`core/dsp-link`, findings 31 and 45). No stock DSP code writes those entries. The engine clears the whole record every block, so the publisher writes every block, after the clear.

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

This runs four blocks on the plain stream and on the `loadmap` stream, in the Python runner. EMUCLK is fed the count of instructions run, so a segment's cycles are its instructions. On 2026-10-21 (batch A), all seven checks passed:

- Both runs end, and every track buffer of every block is the same, bit for bit.
- The registers at every stage's target are the plain run's.
- Each segment's instructions, less one mark per pass, equal the plain run's between the same targets. A mark is 34 instructions. `s_tail` crosses the harness's own setup between blocks, so this check leaves it out.
- A window closes, SNAP holds the header, and both reply pages hold page 0 with a valid check word.

The Waverider gates also run on the `loadmap` stream: set `DNFW_WAVERIDER_LOADMAP=1` before running them.

## Read it

```
python tools/dn2loadmap.py --windows 3 --save out/loadmap/LABEL.json
```

Quit Transfer first. The tool reads the rows with one PEEK of 932 bytes and rebuilds each window. Per segment, it prints the passes and cycles per block and the cycles of one pass. It also prints the share of a frame (666,667 cycles), with and without the marks. Skip the first window after a boot: it starts from an arbitrary EMUCLK.

## Before the first flash

The rows' safety on a DN2 unit is not proven. digikit read, on the Digitakt II, that the ColdFire reads those entries only for "parameters 36 to 39". Whether the DN2 ever asks for them, or sends them anywhere, is open.

A static read of DN2 1.11 found only two users of the rows' address `0x800053c0` in the frame ISR. One is a call with a length of `0x54`, likely cache maintenance. The other is a test routine at `0x40138460`. So the owner runs this check on the unit before flashing `loadmap`:

1. On the current Waverider build, PEEK the rows while a pattern plays. They must read 0.
2. On the `loadmap` build, listen to the main outputs, and look at the USB audio and Overbridge meters. There must be no added noise.

## Cost

A mark is 34 instructions. The publisher is about 407 instructions a block. With 16 Waverider voices the build runs about 410 marks a block: about 14,000 instructions, likely 2 to 3 points of a frame. The reader subtracts the marks. The publisher's cost is in its own segment.
