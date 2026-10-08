# LFO trig modes ONE and HALF: where they stop

Stock 1.11's LFO evaluator A (`0x40137726`, LFO1-3 of every track, once a frame) and
what a fix for the start-phase report has to respect. Measured in the emulator with
`scripts/emu_lfo_trigmodes.py` (the WSL venv; `ui1200M`, LFO3 on track 1, one trig at
frame 0, MULT 8, SPD cell 0x7000; the free-running period is 46.7 frames).

## The reports

1. **The value at the stop** (community, 2026-10-08): ONE and HALF jump to a fixed value
   instead of holding. Fixed by the `lfohold` mod (two stores NOP'd).
2. **The start phase** (rivvi, 2026-10-09): *"if you move the wave start position to the
   next cycle it seems to end prematurely ... It seems to not read the second one."*

## How the evaluator decides to stop

The phase (state `+80`) runs 0 .. 1,382,400,000 for one cycle; each frame adds the
increment (`d6`) into `d2` before wrapping.

| mode | test | where |
|---|---|---|
| HALF (4) | `(d2 - 691,200,000) ^ (old - 691,200,000) < 0`: crossing the cycle's **middle** | `0x401378b4`..`0x401378f0` |
| ONE (3) | `d2 > 1,382,399,999` unsigned: crossing the cycle's **end** (the same test that wraps the phase) | `0x401378f4`..`0x40137924` |

On a trig the phase is set from SPH (`0x40137966`, `macl` of the SPH cell, read signed
by `mvsw`, against 1,382,400,000; RND, waveform 6, takes 0 since its SPH is SLEW) and
stored with the advanced phase's store at `0x401379ba`. The waveform is evaluated from
that phase at `0x401379ec` (scaled, then the table `0x4020b340` by waveform), and the
phase is copied to `+112` each frame unless stopped (`0x40137adc`).

So both stops are **fixed points of the cycle**, not a length from the start phase.

## Measured

The SPH cell's scale: with SPH << 9 (the panel's, presumably: 64 is then the cycle's
centre, as the manual says, and 0..127 covers the cycle) the run lengths in frames are:

| SPH | ONE, SPD + | HALF, SPD + | ONE, SPD - | HALF, SPD - |
|---|---|---|---|---|
| 0 | 47 | 24 | 47 | 24 |
| 32 | 35 | 12 | 12 | 35 |
| 64 | 24 | 47 | 24 | 47 |
| 96 | 12 | 35 | 35 | 12 |
| 127 | 47 | 24 | 46 | 23 |

The same on TRI, SIN and SAW. A later start phase gives a shorter run, and HALF started
on its own stop point runs a whole cycle: rivvi's report, in stock. The `lfohold`
NOPs change none of these lengths (`--hold`: the same stops, the last value held).

## A fix that respects stock

**Shift the phase's origin:** on a trig, start the phase at 0 and latch the SPH point;
evaluate the waveform (and the `+112` copy) at phase + the latched point. Every stock
test, the wrap included, is then relative to the start, in both directions. Latching
(rather than reading SPH live) keeps stock's rule that SPH takes effect at the next
trig. RND keeps its own path (SPH is SLEW there).

**Before a build (the owner's rule: trace every implication, regress nothing):**
- every reader and writer of `+80` and `+112` while the instrument runs (UI included:
  the LFO page's position), from an emulator write/read watch on the state block
  (`0x4463fc18`, 0x780 bytes: 16 tracks x 3 LFOs x 40 bytes);
- a free field for the latch (16 bits is enough: the SPH cell);
- stock vs patched over the whole grid: TRIG, FREE, HOLD, ONE, HALF x every waveform x
  SPH 0..127 x SPD + and - x MULT x FADE, with **retrigs from the TRIG menu** (the
  per-trig LFO trigger) while running and after a stop. Only ONE and HALF with SPH not 0
  may change, and only in where they stop.
