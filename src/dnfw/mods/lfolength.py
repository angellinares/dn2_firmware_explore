"""The LFO ONE/HALF fix: trig modes ONE and HALF run one cycle / half a cycle from the
start phase, and hold the value they reached. It supersedes `lfohold` (2026-10-08), which
fixed the hold on audio tracks only; this does both, on audio and MIDI tracks.

## The stock behaviour this changes

The manual: ONE runs the LFO for one cycle and stops, HALF for half a cycle. Stock 1.11
(and 1.12, the same code) stops them at **fixed points of the cycle** instead: HALF on
crossing the cycle's middle, ONE on crossing its end, wherever the trig's start phase
(SPH) put the LFO. So a later start phase runs shorter: ONE from SPH 96 plays a quarter of
a cycle, and HALF from SPH 64 plays a whole one (it starts on its own stop point). Negative
speed mirrors it. Both of the firmware's LFO evaluators do this: A (audio tracks,
`0x40137726`) and B (`0x401373dc`, the MIDI tracks' LFOs). A community report (rivvi,
2026-10-09), reproduced in the emulator on stock; `docs/lfo-trig-modes.md` has the tables.

## What it changes

For ONE and HALF only, the phase's origin moves to the start: on a trig the phase starts
at 0 and the start point is latched (the SPH cell's high byte, in each LFO record's free
byte `+119`); the waveform is read at phase + that point. Every stock test then counts
from the start. TRIG, FREE and HOLD keep stock's phase exactly (TRIG still starts at the
SPH point); a latch left by changing the mode mid-run is folded into the phase once, so
the waveform doesn't jump. RND, whose SPH is SLEW, never reaches the hooks.

**The hold** (`lfohold`'s fix, folded in): at the stop, stock overwrites the output with a
fixed value per waveform, the centre for nearly all of them, so a square in ONE "turns
off" and in HALF "jumps back to the middle". The four stores that do it (two per
evaluator) are NOP'd, and the LFO keeps the last value it computed.

Four hooks (a `jmp` each into a platform `CODE` chunk at `0x467f8000`, 260 B) and four
NOP'd stores, generated
by `scripts/gen_lfolength_code.py` from `scripts/build_lfo_length.py` into
`lfolength_code.json`, so the browser applies exactly these bytes. Every hook's stock
bytes and the instructions around it are checked first: an image that differs is refused.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, platform

ID = "lfolength"
NAME = "LFO ONE/HALF fix"
SUMMARY = ("LFO trig modes ONE and HALF run one cycle / half a cycle from the start phase and "
           "hold the value they reached, on audio and MIDI tracks (supersedes lfohold).")
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("lfolength_code.json")).read_text())
CODE_VA = SPEC["code"]["va"]
BLOB = bytes.fromhex(SPEC["code"]["blob"])
STATE_BLOCKS = ((0x4463FC18, "evaluator A's LFO states (audio tracks)"),
                (0x4463F498, "evaluator B's LFO states (MIDI tracks)"))
STATE_BYTES, RECORD, LATCH = 0x780, 40, 39   # 16 tracks x 3 LFOs; the latch is each record's +119 (+39)


def extents(firmware=None) -> list[Extent]:
    return ([Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in SPEC["edits"]]
            + platform.extents(16 + len(BLOB)))


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original, others = platform.split(section.unpack())
    if len(original) < SPEC["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{SPEC['stock_length']:,}: not Digitone II 1.11")
    for g in SPEC["guards"]:
        want = bytes.fromhex(g["bytes"])
        if original[g["va"] - BASE:g["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} is not stock; this mod is for unmodified "
                           "Digitone II 1.11. Start from the original 1.11 file")
    for e in SPEC["edits"]:
        want = bytes.fromhex(e["stock"])
        if original[e["va"] - BASE:e["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{e['va']:08x} is not stock; this mod is for unmodified "
                           "Digitone II 1.11, or another mod already wrote there. "
                           "Start from the original 1.11 file")

    content = bytearray(original)
    for e in SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new
    chunk = platform.area.CodeChunk(CODE_VA, BLOB).pack()
    content = platform.join(bytes(content), others + [(platform.area.CODE, chunk)])

    return Result(payloads={SECTION: bytes(content)}, extents=extents(),
                  notes=["LFO TRIG MODE ONE runs one cycle and HALF half a cycle from SPH, "
                         "and both hold the value they reached, on audio and MIDI tracks",
                         f"{len(SPEC['edits'])} edits in section 3 (4 hooks, 4 stores NOP'd), and a "
                         f"{len(BLOB):,} B CODE chunk at 0x{CODE_VA:08x} in the platform's area"])


def ram() -> list[Extent]:
    """The RAM the mod uses: its code, and one byte in each LFO record of both state blocks."""
    out = [Extent(RAM, CODE_VA, len(BLOB), "the mod's code (a platform CODE chunk)")]
    for base, what in STATE_BLOCKS:
        for r in range(STATE_BYTES // RECORD):
            out.append(Extent(RAM, base + r * RECORD + LATCH, 1, f"the start-phase latch in {what}"))
    return out
