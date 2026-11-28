"""Parameter slides: a trig's parameter locks glide over a length, or to the next trig, where stock jumps.

Each trig has SLD on TRIG PAGE 2, in the place under RTRG: OFF, 1/2, 1, 2, 4, 8, 16 or NEXT. In
GRID RECORDING, hold one or more trigs and turn knob E. A trig with a length glides to its own
values over that many steps of the track's speed, from the values the track had just before
it. A NEXT trig glides from its own values to the next trig's, and arrives as that trig plays.
The parameters that glide are the continuous ones that stock offers as LFO destinations. With
SLD OFF on every trig, the instrument behaves as stock.

`scripts/build_pslide.py` carries the reading of the firmware: the note path, the lock lists,
the clock, TRIG PAGE 2 and the step flags. Its code is `scripts/pslide_engine.py` (the slides'
updates), `scripts/pslide_prepare.py` (a trig's slide, prepared at step evaluation),
`scripts/pslide_notes.py` (the starts, at notes and lock trigs) and `scripts/pslide_ui.py` (SLD,
and the edits that carry it with its trig).

## How it applies

The code is assembled ahead of time (`scripts/gen_pslide_code.py` -> `pslide_code.json`), so the
browser applies exactly these bytes:

1. every guard and every edit's stock bytes are checked: an image that differs is refused;
2. the twelve hooks, each a `jmp` or `jsr` into the chunk, and the operand of the mask that
   clears a trig's own settings (`0x4004fd36`: `0x7fff` -> `0x7f97`) are written;
3. the routines are added to the platform's area as a `CODE` chunk at `0x46c00000`, with the
   slides' state after them, which the platform's start-up loader clears. The frame routine
   subscribes to the hook bus's `ev_frame`.

SLD is three bits of the step's flag word, `0x0008`, `0x0020` and `0x0040`: bit 0 of the value
in `0x0008`, bit 1 in `0x0020`, bit 2 in `0x0040`.
"""

from __future__ import annotations

from . import RAM, Extent, ModError, Result, bus, platform, specs

ID = "pslide"
NAME = "Parameter slides"
SUMMARY = ("A trig's parameter locks glide over a length or to the next trig "
           "(SLD on TRIG PAGE 2: hold trigs in GRID RECORDING, turn knob E).")
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPECS = specs.load(__file__, "pslide")         # one per OS version (issue #382)
SPEC = SPECS["1.11"]
# Bytes in the chunk that only look like RAM above BSS (`dnfw.mods.ramcheck`), each disassembled
# with objdump -m m68k:cfv4e on 2026-11-27. The places move with the code, so a change to the chunk
# needs them read again.
NOT_RAM = (
    0x46C001DC, 0x46C00606, 0x46C0070E, 0x46C0074E, 0x46C0076A,
                             # move.w #0x2700,%sr (46 fc 27 00)
    0x46C00646, 0x46C00748, 0x46C00760, 0x46C0077E,
                             # move.w %d5,%sr (46 c5) and the next instruction
    0x46C00288,
                             # not.l %d1 ; and.l %d1,%d0 (46 81 c0 81)
    0x46C003E0, 0x46C00704, 0x46C00BC6, 0x46C00BCE, 0x46C00BD6, 0x46C00BDE, 0x46C00C52,
                             # not.l %d0 ; and.l %d0,%d4 (46 80 c8 80)
    0x46C013E6, 0x46C014CE,
                             # jsr 0x40054690 ; lea ...: the operand's low word and the next opcode
)


def _padded(n: int) -> int:
    return n + -n % 4


def area(os: str = "1.11") -> int:
    """The platform's area with this mod alone: the area's header, a directory entry for each of
    three chunks, this mod's CODE chunk, its subscription, and the bus's dispatchers up to the end
    of ev_frame's (`dnfw.mods.bus.attach`)"""
    spec = specs.pick(SPECS, os, ID)
    dispatchers = platform.SPECS[os]["bus"]["symbols"]["frame_end"] - bus.BUS_VA
    return (12 + 3 * 12 + 16 + _padded(len(spec["code"]["blob"]) // 2) + 12
            + 16 + _padded(dispatchers))


def extents(firmware=None, os: str | None = None) -> list[Extent]:
    os = os or specs.of_firmware(firmware)
    spec = specs.pick(SPECS, os, ID)
    return ([Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in spec["edits"]]
            + platform.extents(area(os), os))


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original = section.unpack()
    if original is None:
        raise ModError("MAIN OS did not depack")
    original, others = platform.split(original)
    os = specs.of_main_os(original)
    spec = specs.pick(SPECS, os, ID)
    content = specs.apply_edits(original, spec, os)
    code = spec["code"]
    blob = bytes.fromhex(code["blob"])
    chunk = platform.area.CodeChunk(code["va"], blob, code["bss"]).pack()
    content = platform.join(bytes(content), others + [(platform.area.CODE, chunk),
                                                      bus.subscribe(b"FRAM", spec["labels"]["slide_frame"])])
    return Result(payloads={SECTION: bytes(content)}, extents=extents(os=os),
                  notes=["TRIG PAGE 2: SLD under RTRG. Hold trigs in GRID RECORDING and turn knob E",
                         "a trig with a length glides to its locks over it, a NEXT trig glides to the "
                         "next trig's",
                         f"{len(spec['edits'])} edits in section 3, a {len(blob):,} B CODE chunk at "
                         f"0x{code['va']:08x} with {code['bss']:,} B of state, and an ev_frame handler"])


def ram(os: str = "1.11") -> list[Extent]:
    """The RAM the code uses: its own chunk and the slides' state after it."""
    code = specs.pick(SPECS, os, ID)["code"]
    return [Extent(RAM, code["va"], len(code["blob"]) // 2 + code["bss"],
                   "the mod's code and its slides' state (a platform CODE chunk and its BSS)")]
