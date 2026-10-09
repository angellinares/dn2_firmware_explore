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

## Two evaluators, and 1.12

The MIDI tracks' LFOs run through a second evaluator with the same logic, **B**
(`0x401373dc`, state block `0x4463f498`, phase 0..21,600,000 a cycle; driven with
`--midi`, which writes B's tempo-derived rate words, zero in `ui1200M`). B stops at the
same fixed points (ONE 55, 42, 28, 14 frames at SPH 0, 32, 64, 96) and jumps to the same
stop tables through `%a5@`. **`lfohold` as first published covered A only**: B's stores
are `0x401374e4` (HALF) and `0x4013751e` (ONE).

**1.12** carries both problems: its evaluator A (`0x40137a06`) is 1.11's instruction for
instruction, only the addresses moved (+0x2e0; the state block at `0x44640c18`).

## The fix: `lfolength`

`scripts/build_lfo_length.py` (the design and the register notes), the mod
`src/dnfw/mods/lfolength.py`, four hooks into a 264 B CODE chunk at `0x467f8000`. Measured
(`--fix`): every start phase now runs one cycle (A 47 frames, B 55) in ONE and half a
cycle (24, 28) in HALF, and `--compare` shows each tracing TRIG's waveform until the stop,
**max difference 0** on TRI, SIN and SAW at SPH 0..127, both evaluators.

| SPH | ONE stock | ONE fixed | HALF stock | HALF fixed |
|---|---|---|---|---|
| 0 | 47 | 47 | 24 | 24 |
| 32 | 35 | 47 | 12 | 24 |
| 64 | 24 | 47 | 47 | 24 |
| 96 | 12 | 47 | 35 | 24 |
| 127 | 47 | 47 | 24 | 24 |

The comparison caught one bug of mine on the way: the latch's reconstruction (`extbl`,
`swap`, `lsll #8`) carried a negative byte's sign bits into the low word, a 1/256-cycle
offset at SPH 64 and up (0x80 on TRI). A `clrw` after the `swap` fixed it.

**The regression grid** (`--regress`, factory vs fixed, each case from the same LFO state and the same random-generator state): modes FREE/TRIG/HOLD/ONE/HALF x the seven waveforms x SPH 0/32/64/96 x speed + and - x fade off/on x one trig / a retrig mid-run / a retrig after the stop: **1680/1680 on both evaluators.** Outside ONE/HALF with SPH > 0 (and RND) the fixed machine equals factory exactly; ONE/HALF trace TRIG until each stop and run factory's SPH-0 length after every trig. Two harness artifacts were found and removed on the way, both in the comparison rather than the fix: the LFO state carried from one case to the next, and RND's generator advanced differently on the two machines.

Implications traced (the owner's rule):
- the latch is each record's `+119`, which neither evaluator, their resets, nor B's flag
  setter (`0x401373b8`, which writes `+118`) touches; whole-record copies carry it;
- only ONE and HALF shift; TRIG keeps stock's start; a latch left by a mode change mid-run
  is folded into the phase (`--switch`: ONE/HALF -> FREE, HOLD, TRIG at frame 10 equal stock);
- RND (SPH = SLEW) never reaches the hooks; waveforms past 0..5 (lfowaves' new ones, where
  SPH means steps, width, repeats or a position) don't latch;
- lfowaves repoints B's waveform table inside `lea 0x4020b340,%a1`, so B's waveform hook sits
  on the 6 bytes before it, and lfohold's B sites are asserted with the instruction after
  each store.

## On the instrument: lfofix1, an overflow the emulator could not reach (2026-10-09)

The owner flashed `lfofix1`: ONE, SQR, SPH 85 went low (short), high (long), then **rapidly
low, high, low** and held low; SIN at SPH 74 clicked near the end of the run. Cause: the
waveform hook added the start point to the phase as a signed long; on the instrument the
start point reaches 0.99 of a cycle (SPH 0..127 << 8 in the cell; the fractional `macl`
gives cell / 32768 of a cycle), so phase + point reaches 2.76e9, past a signed long, and
the wrong correction ran: from 0.9 of a run at SPH 85 the waveform was read at 2.56..2.65
cycles. The emulator never got there: its EMAC returns half the fractional product
(`docs/for-digikit-emac-frac.md`), so start points stayed under half a cycle, and the
SPH << 9 scale this note first assumed was that halving.

**The fix (lfofix2):** add (point - cycle) when the point is >= 0, the point itself when
negative, then a cycle back if below 0: every value stays within one cycle. Run as the
bare instruction sequence over phases 0..cycle and points -cycle..cycle for both
evaluators' cycles: 6056/6056 equal (phase + point) mod cycle; the old sequence reads
2.564 cycles at 0.9 of a run from SPH 85.

**Lessons.** A test rig's arithmetic is part of what is tested: check the emulator's
multiply against the chip's definition before trusting a result that depends on it. And
test the real parameter scale: a value range the emulator cannot produce is untested, not
clean.

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
