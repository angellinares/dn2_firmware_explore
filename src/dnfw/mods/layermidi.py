"""Track layering onto MIDI tracks: an audio track's layered notes go out over MIDI.

TRACK WILL TRIGGER lets a track trigger others. On stock Digitone II firmware a
MIDI destination stays silent: layering happens in the frame ISR, which copies
the note onto the destination as a synth note, and a MIDI track has no voice to
play it. This mod sends those notes out on the MIDI track's channel. **Passed on
the instrument on 2026-10-02** as `layer-midi6`: sequenced notes, chords,
retrigs and probability; INF holds until the sequencer stops; live keys with no
hanging notes; two audio sources into one MIDI track, and one source into
several MIDI tracks. `docs/layer-midi.md` carries the reading and the bench
history, and `scripts/build_layer_midi.py` the assembly and evidence.

**Moved onto the mod platform 2026-10-03** (`layer-midi7`): the same code, now a
platform `CODE` chunk at `0x467d8000` instead of a cave in the image, so it
combines with usbprobe. **Passed on the instrument on 2026-10-03** with bootscreen
and usbprobe in the same image.

## How it works

Two hooks in the frame ISR, one platform `CODE` chunk at `0x467d8000`:

1. at the head of the per-note body (`0x40026980`), every note the ISR voices
   passes once: a layered copy's note (record `+56` bit 17) on a MIDI track
   becomes a MIDI note-on on the batch the ISR already hands the MIDI task;
2. at the head of the per-note release body (`0x40026d32`), a layered copy's
   release on a MIDI track becomes a MIDI note-off, which the MIDI task matches
   to the note on whichever channel it is active and sends.

The note, velocity and length are the ISR's own note entry's. A record is taken
from the MIDI pool only while two are free: the stock allocator does not check
for an empty pool, and an empty pop corrupts low memory for good.

## How it applies

The code is assembled ahead of time (`scripts/gen_layermidi_code.py` ->
`layermidi_code.json`), so the browser applies exactly these bytes:

1. every guard (whole instructions and the code the hooks rely on) and every
   edit's stock bytes are checked -- an image that differs is refused;
2. the edits are written: the two hooks, pointing at the chunk;
3. the routines are added to the platform's area (`dnfw.mods.platform`) as a
   324 B `CODE` chunk at `0x467d8000`, which the platform's start-up loader
   copies there.

It writes only inside section 3 and changes no stock length; the appended area
is the platform's, shared with the other mods on it. It is kept apart from
midiarp by the compatibility notes, not by bytes: both turn layered copies on
MIDI tracks into MIDI (`dnfw.mods.matrix`).
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, platform
from ..osport import versions

ID = "layermidi"
NAME = "Layering onto MIDI tracks"
SUMMARY = "TRACK WILL TRIGGER onto a MIDI track sends the layered notes out over MIDI."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("layermidi_code.json")).read_text())
# One spec per OS version (issue #382): the user's stock image picks it. SPEC, CODE_VA and BLOB stay
# OS 1.11's names.
SPECS = {"1.11": SPEC}
for _os in versions.VERSIONS:
    _path = pathlib.Path(__file__).with_name(f"layermidi_code_{_os}.json")
    if _os != "1.11" and _path.exists():
        SPECS[_os] = json.loads(_path.read_text())
CODE_VA = SPEC["code"]["va"]
BLOB = bytes.fromhex(SPEC["code"]["blob"])


def _spec(os: str) -> dict:
    if os not in SPECS:
        raise ModError(f"layermidi is not yet ported to Digitone II {os}")
    return SPECS[os]


def extents(firmware=None, os: str | None = None) -> list[Extent]:
    os = os or (versions.of_firmware(firmware).name if firmware is not None else "1.11")
    spec = _spec(os)
    blob = bytes.fromhex(spec["code"]["blob"])
    return ([Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in spec["edits"]]
            + platform.extents(16 + len(blob), os))


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original, others = platform.split(section.unpack())
    try:
        os = versions.of_main_os(original).name
    except versions.UnknownImage as exc:
        raise ModError(str(exc)) from None
    spec = _spec(os)
    code_va, blob = spec["code"]["va"], bytes.fromhex(spec["code"]["blob"])
    # Longer is fine: data appended after the stock end (lfowaves, bootscreen)
    # moves no address this mod writes or reads. The guards identify the build.
    if len(original) < spec["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{spec['stock_length']:,}: not Digitone II {os}")
    for g in spec["guards"]:
        want = bytes.fromhex(g["bytes"])
        if original[g["va"] - BASE:g["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} is not stock; this mod is for unmodified "
                           f"Digitone II {os}")
    for e in spec["edits"]:
        want = bytes.fromhex(e["stock"])
        if original[e["va"] - BASE:e["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{e['va']:08x} is not stock; this mod is for unmodified "
                           f"Digitone II {os}, or another mod already wrote there")

    content = bytearray(original)
    for e in spec["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new
    chunk = platform.area.CodeChunk(code_va, blob).pack()
    content = platform.join(bytes(content), others + [(platform.area.CODE, chunk)])

    return Result(payloads={SECTION: bytes(content)}, extents=extents(os=os),
                  notes=["TRACK WILL TRIGGER onto a MIDI track plays it over MIDI",
                         "note-on as the layered note plays, note-off as it is released",
                         f"{len(spec['edits'])} hooks in section 3, and a {len(blob):,} B CODE "
                         f"chunk at 0x{code_va:08x} in the platform's area"])


def ram() -> list[Extent]:
    """The RAM above BSS the code uses: only its own code, copied there by the loader."""
    return [Extent(RAM, CODE_VA, len(BLOB), "the mod's code (a platform CODE chunk)")]
