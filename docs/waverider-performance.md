# Waverider: performance on the instrument

All readings are from a Digitone II on OS 1.11 through the USB probe: the SHARC's load is
`1 - idle cycles / total cycles` over one-second intervals, and "longest stretch" is the longest
busy period of a frame as a share of a frame (a frame is 1/1500 s). Overruns count busy stretches
longer than a whole frame. The test plan has every run's steps; the entry names are in the
last column.

## 0.3.8: FSRC and the sub's polyBLEP on the unit (2026-10-29)

The build is fsrc2 (Waverider 0.3.8). Each figure is the median load of ten one-second readings,
with a 16-note chord (notes 72 to 87) on Growlaren, 16 voices on Waverider. The DSP missed no frame.
These figures use a different measure and project from the 0.3.7 table below, so compare them only
with each other.

| Case | FSRC OSC2 | FSRC SUB | FSRC NOIS |
|---|---|---|---|
| FM 64, LEV1 and LEV2 100, SUB 0, NOIS 0 | 60.5 % | 62.5 % (+2.0) | 62.1 % (+1.6) |
| The costliest setup: FOLD 64, WARP 64, FM 127, Formant, SUB 100 SQR, NOIS 100 | 67.8 % | 68.0 % (+0.2) | 68.0 % (+0.2) |

- In the costliest setup, the highest of the short readings over 20 s was 71.8 %.
- When you can hear the sub or the noise, FSRC adds 0.2 points. With SUB or NOIS at 0, the source
  plays only for the FM, and FSRC SUB adds 2.0 points. The estimate was 0.9.
- The owner accepted the 2.0 points for 0.3.8 (2026-10-29). We can shave this load later if needed:
  for example, render the sub for the FM only, without the mix.
- The polyBLEP is not the cause. In the cycle model, FSRC SUB with SUB 0 costs 180 instructions a
  voice and block at note 60 and at note 84. The polyBLEP corrects more blocks at note 84, so a
  polyBLEP cost would grow with the note.
- For 16 voices the cycle model gives about 0.6 to 0.7 points, against the unit's 2.0. The unit runs
  about 1.26 times slower than the emulator assumes. That leaves about 2.4 times without a cause.
  Memory waits are a guess. We did not check them.

## 0.3.7 against 0.3.6 on the unit (2026-10-22)

0.3.7 has the load plan's batch A: the same sound with less DSP code. The builds are fmdepth2 (0.3.6)
and batcha1 (0.3.7). Both had a 16-note chord (notes 36 to 84) on Growlaren, with LFO 1 on AMT.
Each figure is the median, over 60 s, of each second's longest busy stretch
(`dn2sharc_load.py --frame-max`). The DSP missed no frame in any case.

| Case | 0.3.6 | 0.3.7 | Change |
|---|---|---|---|
| Page 5 off | 66.7 % | 61.4 % | -5.3 |
| FOLD 64 | 68.1 % | 62.8 % | -5.3 |
| WARP 64 | 72.8 % | 63.8 % | -9.0 |
| FM 64 | 71.1 % | 64.5 % | -6.6 |
| Formant | 71.1 % | 65.9 % | -5.2 |
| All of page 5 on | 81.1 % | 72.2 % | -8.9 |
| SUB and NOIS 127 | 66.8 % | 61.5 % | -5.3 |
| SUB and NOIS 0 | 62.0 % | 57.5 % | -4.5 |

In a 10-minute soak with all of page 5 on, the median was 72.4 % (0.3.6: 78.2 %), and the DSP missed no frame.
These figures use a different project from the sections below, so compare them only with each other.

## Waverider on its own (2026-10-12)

The same project throughout (16 voices render every frame), one-second readings, osc 2 on, sub
and noise as in the saved test project.

| State | Load (median) | Range | Longest stretch | Overruns |
|---|---|---|---|---|
| Nothing playing | 63.4 % | 63.3 to 63.5 | | |
| 16-note chord, both oscillators on Prim. | 64.8 % | 64.7 to 64.9 | | |
| 16-note chord, both oscillators on a 64x2048 pool table, 60 readings | 65.0 % | 64.9 to 65.1 | | |
| The same, 10 minutes (600 readings) | 65.0 % | 64.9 to 65.2 | median 68.3 %, max 69.6 % | 0 in 600 s |
| Default Waverider on track 1 and default WaveTone on track 2, alternating at 120 BPM (the alpha build) | 56.4 % | 56.3 to 56.5 | median 59.4 %, max 59.6 % | 0 in 60 s |

Playing adds about 1.4 points over an idle project, and a pool table costs 0.2 points over Prim.
The 10-minute run is flat from the first two minutes to the last two.

## The factory machines, for comparison

The 16-note chord on 16 voices, measured 2026-10-09 in an earlier project.

| Machine | Load (median) | Longest stretch | Overruns |
|---|---|---|---|
| WaveTone | 58.0 % | 61.2 % | 0 |
| FM Tone | 62.9 % | 66.2 % | 0 |
| FM Tone, heavy patch | 63.1 % | 69.2 % (worst) | 0 |

## Page 5, estimated against the factory machines (2026-10-16)

These numbers are estimates, not readings. Each row starts from the 16-note chord on a pool table above
(65.0 %, longest stretch up to 69.6 %). It adds 16 times the runner's cost of the control (the next table)
against a frame of 666,667 cycles. Runner instructions are not silicon cycles, so the instrument's reading decides.

| 16-note chord, 16 voices | Load (median) | Longest stretch |
|---|---|---|
| Waverider, page 5 at 0 (0.3.0) | about 65.2 % | about 69.8 % |
| WARP on | about 66.9 % | about 71.5 % |
| FM on | about 66.4 % | about 71.0 % |
| WARP and FM on | about 67.9 % | about 72.5 % |
| FOLD, AM, WARP and FM on | about 69.8 % | about 74.4 % |
| WaveTone (measured) | 58.0 % | 61.2 % |
| FM Tone (measured) | 62.9 % | 66.2 % |
| FM Tone, heavy patch (measured) | 63.1 % | 69.2 % |

With all of page 5 on every voice, the median stays under 70 %. The longest stretch is about 5 points
above FM Tone's worst. WARP or FM alone stays within about 3 points of it.

## What costs what

Per voice and block, measured in the SHARC runner (`scripts/sharc_waverider_p3_cost.py`):

| Part | Cycles per voice per block |
|---|---|
| Sub-oscillator | +742 |
| Noise, WHT | +905 |
| Noise, PNK with a decay | +2,022 |
| Sub and noise together | +2,764 (about 6.6 % of a frame on 16 voices) |
| Page 5: FOLD | +369 |
| Page 5: Ring | +363 |
| Page 5: AM | +431 |
| Page 5: WARP (both oscillators) | +710 |
| Page 5: FM | +482 |
| Page 5: WARP and FM | +1,138 |
| Page 5: AM, FOLD, WARP and FM together | +1,898 (about 4.6 % of a frame on 16 voices) |
| Page 5 at 0, against the build before WARP and FM | +87 (WARP's word read once a voice, and a test before each reader call) |
| One oscillator (osc 2's whole pass) | +2,822 |
| NPOS (branch `wip/waverider-npos`, not shipped), NPOS 64, both oscillators at POS 64: DCLK's crossfades of its jumps | +5,614 |
| FM Tone's whole voice, for comparison | +11,113 |

A table in the pool costs nothing per frame unless a voice plays it; what it costs is
its memory and one build when the pool loads.

## Building a table

The DSP builds a pool table's mip levels in its spare time after the pool loads: a 64x2048
table takes about 0.16 s, and a pool of 128 is ready a few seconds after the load. While a table
builds, its slot plays Prim.; on a reload the old table plays on and the new one fades in.

## What has not been measured yet

- 4096-point tables on the instrument.
- A soak with Waverider on every voice and an FM Tone track beside it.
- The cost of the larger tables (4096 points) against Prim.
- The reload click on the instrument (the runner shows a step of 0.002 of the sine's amplitude,
  from 0.5 before the spare region).
