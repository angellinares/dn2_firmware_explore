# Waverider: performance on the instrument

All readings are from a Digitone II on OS 1.11 through the USB probe: the SHARC's load is
`1 - idle cycles / total cycles` over one-second intervals, and "longest stretch" is the longest
busy period of a frame as a share of a frame (a frame is 1/1500 s). Overruns count busy stretches
longer than a whole frame. The test plan has every run's steps; the entry names are in the
last column.

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
