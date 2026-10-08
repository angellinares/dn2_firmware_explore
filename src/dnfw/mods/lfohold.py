"""LFO trig modes ONE and HALF hold the value they stopped at, instead of jumping.

## The stock behaviour this changes

The manual says ONE runs the LFO to the end of its waveform and stops, and HALF
runs it to the middle and stops. Stock 1.11's LFO evaluator (`0x40137726`, the
one LFO1-3 run through every frame) does stop there, but it does not hold the
value it reached: it overwrites the LFO's output with a constant from a table
indexed by waveform, and keeps that constant until the next trig.

| mode | where | the store | the table (TRI, SIN, SQR, SAW, EXP, RMP, RND) |
|---|---|---|---|
| HALF (4) | crossing the cycle's middle, `0x401378c8`..`0x401378f0` | `0x401378ec` `movel %a0@,%a2@(84)` | `0x4020b2ec`: 0, 0, 0, 0, 0, max, 0 |
| ONE (3) | wrapping at the cycle's end, `0x401378f4`..`0x40137924` | `0x40137920` `movel %a0,%a2@(84)` | `0x4020b308`: all 0 (`0x4020b324` at negative speed: 0, 0, 0, 0, max, 0, 0) |

State `+84` is the LFO's output. Once stopped (the stop flag), the evaluator no
longer runs the waveform or the fade, and the output stays what was stored. So a
stopped LFO sits at the centre (no modulation) for most waveforms. That's
invisible on a triangle or a sine at their zero crossings, and a jump everywhere
else: a square's ONE "turns off" after one cycle and its HALF "jumps back to the
middle" (a community report, reproduced on official 1.10), a triangle's HALF
drops from its peak, a ramp's HALF leaps to the maximum.

## What it changes

The two stores become NOPs (`4e71 4e71`, 4 bytes each). The output then keeps
what the previous frame computed, the last value before the stop: ONE holds the
waveform's end, HALF its middle. Nothing else moves; the stop flag, the phase,
the trig restart and the random waveform's own path are untouched.

Measured in the emulator (`scripts/emu_lfo_trigmodes.py`, `ui1200M`, LFO3 on track
1, one trig, MULT 8): stock, every waveform but RND ends at exactly the
destination's centre after a ONE (47 frames) or a HALF (24 frames) while TRIG runs
on; with the NOPs, each holds the value it reached (TRI HALF its peak, RMP ONE
its top, SAW, SIN, EXP likewise); RND is the same either way. The harness's
square never toggles, so the square case is the instrument's to show.
"""

from . import Extent, ModError, Result

ID = "lfohold"
NAME = "LFO hold"
SUMMARY = "LFO trig modes ONE and HALF hold the value they stopped at, instead of jumping to a fixed one."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400

# Stock 1.11, as `out/main111.dis` reads it, with the instruction before each
# store asserted too, so a moved or different evaluator is refused.
SITES = (
    (0x401378E8, bytes.fromhex("41f03c00" "25500054"), bytes.fromhex("41f03c00" "4e714e71"),
     "HALF: lea %a0@(0,%d3:l:4),%a0 ; movel %a0@,%a2@(84) -> the store NOP'd"),
    (0x4013791C, bytes.fromhex("20713c00" "25480054"), bytes.fromhex("20713c00" "4e714e71"),
     "ONE: moveal %a1@(0,%d3:l:4),%a0 ; movel %a0,%a2@(84) -> the store NOP'd"),
)


def extents(firmware=None) -> list[Extent]:
    return [Extent(SECTION, at + 4 - BASE, 4, what) for at, _stock, _new, what in SITES]


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    content = bytearray(section.unpack())
    for at, stock, new, _what in SITES:
        off = at - BASE
        if content[off:off + len(stock)] != stock:
            raise ModError(f"0x{at:08x} is not stock; this mod is for Digitone II 1.11, "
                           "or another mod already wrote there")
        content[off:off + len(new)] = new
    return Result(payloads={SECTION: bytes(content)}, extents=extents(),
                  notes=["LFO trig modes ONE and HALF hold the value they stopped at",
                         "2 in-place edits of 4 B in section 3, nothing appended"])
