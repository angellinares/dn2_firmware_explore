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

Four hooks (a `jmp` each into a platform `CODE` chunk at `0x467b0000`, 260 B) and four
NOP'd stores, generated
by `scripts/gen_lfolength_code.py` from `scripts/build_lfo_length.py` into
`lfolength_code.json`, so the browser applies exactly these bytes. Every hook's stock
bytes and the instructions around it are checked first: an image that differs is refused.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, platform, specs

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
SPECS = specs.load(__file__, "lfolength")          # one per OS version (issue #382); SPEC is 1.11's
STATE_BLOCKS = ((0x4463FC18, "evaluator A's LFO states (audio tracks)"),
                (0x4463F498, "evaluator B's LFO states (MIDI tracks)"))
STATE_BYTES, RECORD, LATCH = 0x780, 40, 39   # 16 tracks x 3 LFOs; the latch is each record's +119 (+39)


def extents(firmware=None, os: str | None = None) -> list[Extent]:
    os = os or specs.of_firmware(firmware)
    spec = specs.pick(SPECS, os, ID)
    return ([Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in spec["edits"]]
            + platform.extents(16 + len(spec["code"]["blob"]) // 2, os))


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original, others = platform.split(section.unpack())
    os = specs.of_main_os(original)
    spec = specs.pick(SPECS, os, ID)
    content = specs.apply_edits(original, spec, os, f". Start from the original {os} file")
    code_va, blob = spec["code"]["va"], bytes.fromhex(spec["code"]["blob"])
    chunk = platform.area.CodeChunk(code_va, blob).pack()
    content = platform.join(bytes(content), others + [(platform.area.CODE, chunk)])

    return Result(payloads={SECTION: bytes(content)}, extents=extents(os=os),
                  notes=["LFO TRIG MODE ONE runs one cycle and HALF half a cycle from SPH, "
                         "and both hold the value they reached, on audio and MIDI tracks",
                         f"{len(spec['edits'])} edits in section 3 (4 hooks, 4 stores NOP'd), and a "
                         f"{len(blob):,} B CODE chunk at 0x{code_va:08x} in the platform's area"])


def ram(os: str = "1.11") -> list[Extent]:
    """The RAM the mod uses: its code, and one byte in each LFO record of both state blocks."""
    spec = specs.pick(SPECS, os, ID)
    out = [Extent(RAM, spec["code"]["va"], len(spec["code"]["blob"]) // 2, "the mod's code (a platform CODE chunk)")]
    bases = spec.get("state_blocks", [b for b, _ in STATE_BLOCKS])
    for base, (_, what) in zip(bases, STATE_BLOCKS):
        for r in range(STATE_BYTES // RECORD):
            out.append(Extent(RAM, base + r * RECORD + LATCH, 1, f"the start-phase latch in {what}"))
    return out
