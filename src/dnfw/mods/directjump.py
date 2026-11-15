"""Direct jump: a pattern cued in the PTN view starts at the next step, from where the playing one was.

Stock 1.11 changes to a pattern cued with [PTN] + [TRIG] when the playing pattern ends, or at
its CHANGE length. This mod adds a switch, set in the PTN view: [UP] turns DIRECT JUMP on,
[DOWN] turns it off, and the title bar says "Direct Jump ON" or "Direct Jump OFF". Off, the
default and what a fresh instrument reads, the change is stock's. On, a cue made in the PTN
view while the sequencer plays starts the new pattern on the next step. At 1x, a cue in the last
third of a step starts it on the step after. While the switch is on, [PTN] lights magenta in
the PTN view instead of white. The new pattern goes on from the playing
pattern's position, wrapped by its own length, and in per-track mode each track by its own
length (the Analog Rytm's rule). Program changes, chains and songs keep stock's change, except
one that comes between a jump's cue and the jump, which the jump takes. The switch is saved with
the instrument's settings.

`scripts/build_direct_jump.py` carries the reading of the firmware: the PTN view's keys, LEDs and
message line, the sequencer's cue, arm and switch, and the settings byte. `scripts/emu_directjump.py`
checks the timing and the start step against a prediction from the firmware's own record of
each cue, tick and switch, with stock alongside.

## How it applies

The code is assembled ahead of time (`scripts/gen_directjump_code.py` -> `directjump_code.json`),
so the browser applies exactly these bytes:

1. every guard and every edit's stock bytes are checked -- an image that differs is refused;
2. the seven hooks (`0x400fa1e0`, `0x400da406`, `0x400da45a`, `0x400da6e6`, `0x400d9e10`,
   `0x400da7a6`, `0x400da7c2`), each a `jmp` into the chunk, and the PTN view's key handler and
   LED method in its vtables (`0x402008cc`, `0x4020097c`) are written;
3. the routines are added to the platform's area as a `CODE` chunk at `0x46790000`, which the
   platform's start-up loader copies there.

The switch is one byte of RAM in the settings block (`0x405cd8c1`), which the firmware already
saves to the +Drive and restores; the mod writes it only through the stock settings writer.

On OS 1.12 (issue #382) the same routines apply from `directjump_code_1.12.json`: the sites and
the stock addresses in the code come from `dnfw.osport`, and the switch moves with the settings
block to `0x405ce8c1`. The chunk stays at `0x46790000`.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, platform, specs

ID = "directjump"
NAME = "Direct jump"
SUMMARY = ("A pattern cued in the PTN view starts at the next step, from where the playing one was "
           "([PTN] + [UP] on, [PTN] + [DOWN] off).")
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("directjump_code.json")).read_text())
CODE_VA = SPEC["code"]["va"]
BLOB = bytes.fromhex(SPEC["code"]["blob"])
SPECS = specs.load(__file__, "directjump")         # one per OS version (issue #382); SPEC is 1.11's
FLAG = 0x405CD8C1                  # the switch, in the settings block's unaddressed tail (1.11)
# Bytes in the chunk that only look like RAM above BSS (`dnfw.mods.ramcheck`), in reclaim:
# 0x467903e8 is `move.w #0x2700,%sr` (46 fc 27 00), and 0x467904a0 is `move.w %d7,%sr ;
# movem.l` (46 c7 4c d7). The places shift with the code, so a change to the chunk needs
# this checked again. The 1.12 chunk has the same layout, so the same places.
NOT_RAM = (0x467903E8, 0x467904A0)


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
    if len(original) < SPEC["stock_length"]:      # shorter than the shortest stock
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{SPEC['stock_length']:,}: not Digitone II 1.11")
    os = specs.of_main_os(original)
    spec = specs.pick(SPECS, os, ID)
    content = specs.apply_edits(original, spec, os)
    code_va, blob = spec["code"]["va"], bytes.fromhex(spec["code"]["blob"])
    chunk = platform.area.CodeChunk(code_va, blob).pack()
    content = platform.join(bytes(content), others + [(platform.area.CODE, chunk)])

    return Result(payloads={SECTION: bytes(content)}, extents=extents(os=os),
                  notes=["the PTN view: [UP] turns DIRECT JUMP on, [DOWN] off (off by default)",
                         "on: a pattern cued with [PTN] + [TRIG] starts at the next step, from "
                         "where the playing pattern was",
                         f"{len(spec['edits'])} edits in section 3, and a {len(blob):,} B CODE "
                         f"chunk at 0x{code_va:08x} in the platform's area"])


def ram(os: str = "1.11") -> list[Extent]:
    """The RAM the code uses: its own chunk (with its three state bytes), and the switch's
    byte in the settings block."""
    spec = specs.pick(SPECS, os, ID)
    return [Extent(RAM, spec["code"]["va"], len(spec["code"]["blob"]) // 2,
                   "the mod's code and its state (a platform CODE chunk)"),
            Extent(RAM, spec.get("flag", FLAG), 1, "the DIRECT JUMP switch, in the settings block's tail")]
