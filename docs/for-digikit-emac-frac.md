# For digikit: EMAC fractional products come out halved

**Found 2026-10-09** while checking a ColdFire LFO fix against the instrument.

## What

With `MACSR = 0x20` (fractional mode, as the DN2 1.11 firmware sets it, e.g. `0x401373f0`
`movel #32,%macsr`), digikit's patched Unicorn returns **half** the product a ColdFire EMAC
gives:

| code | digikit | the ColdFire EMAC (fractional: the Q31 product) |
|---|---|---|
| `macl %d0,%d1,%acc0 ; movclrl %acc0,%d0`, d0 = d1 = 0x40000000 (0.5) | `0x10000000` | `0x20000000` (0.25) |
| d0 = 0x55000000, d1 = 1382400000 | 459,000,000 | 918,000,000 |

`scripts/emu_lfo_trigmodes.py`'s neighbourhood reproduces it in a few lines (a scratch
script: `movel #32,%macsr`, two `movel #imm`, `macl`, `movclrl`, `rts`, run with
`Machine.call`).

## Why it matters

- The DN2's LFO evaluators (`0x40137726`, `0x401373dc`) set the start phase with a
  fractional `macl` of the SPH cell and the cycle length. Under digikit the start point
  comes out at half its real value, so SPH appears to cover half a cycle; on the
  instrument it covers the whole cycle (the manual: SPH 64 = the centre).
- The SIN waveform's polynomial (`0x40137274`) uses fractional `macl` too: under digikit a
  free-running SIN falls from the top to zero over a whole cycle instead of tracing a sine.
- An LFO fix verified only in digikit missed an overflow that only real-scale start points
  reach (`docs/lfo-trig-modes.md`).

## Where

The EMAC is in digikit's patched Unicorn core (`emu/unicorn_compat.py` checks its semantics
but does not implement them). In fractional mode the product should be shifted left one
place before it is accumulated (the ColdFire's Q31 alignment).

No change proposed here yet: the fix belongs in the Unicorn patch, and `unicorn_compat.py`
would gain a fractional-product case (0.5 x 0.5 = 0x20000000) to hold it.
