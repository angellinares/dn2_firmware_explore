"""A read-only USB SysEx probe: live ColdFire state on a PC, without a reflash per question.

derived from irpina/digihealth (sysinfo.s), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

The instrument answers SysEx on its own channel, `F0 00 20 3C 7D 00 ... F7`
(Elektron's manufacturer header and a device byte no Elektron machine uses, so
a stock OS drops it), over USB only, with three commands, all of which only
read: HELLO, STATS (the audio-frame ISR's cost, idle time, and DSP liveness)
and PEEK (DDR, the on-chip SRAM and the SSI0 audio windows; never a peripheral
register). `tools/dn2probe.py` is the other end; `docs/usbprobe.md` has the
sites, the evidence and the hardware test.

The protocol and the router hook are irpina's (irpina/digihealth, and irpina's
probing handoff (local)), for the Digitakt mk1 1.53; the DN2 1.11 sites were
found again by the signature of each mk1 site.

## How it applies

`scripts/gen_usbprobe_code.py` assembles `csrc/usbprobe/` into the 896-byte
cave at `0x402cf52c` and records it with four 6-byte `jsr` hooks in
`usbprobe_code.json`. Here:

1. every guard and every edit's stock bytes are checked -- an image that
   differs is refused;
2. the edits are written, and the HELLO tag is filled in.

Section 3 only, no length change, nothing appended. lfowaves (2026-09-30), arpplocks
(2026-10-02) and midiarp (2026-10-03) left these caves for the mod platform and
combine with it.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, specs

ID = "usbprobe"
NAME = "USB SysEx probe (diagnostic)"
SUMMARY = "Read-only live state over USB SysEx (device 0x7D): HELLO, STATS, PEEK."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("usbprobe_code.json")).read_text())
SPECS = specs.load(__file__, "usbprobe")           # one per OS version (issue #382); SPEC is 1.11's
DEFAULT_TAG = "usbprobe 1"


def extents(firmware=None, os: str | None = None) -> list[Extent]:
    spec = specs.pick(SPECS, os or specs.of_firmware(firmware), ID)
    return [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in spec["edits"]]


def tag_bytes(tag: str) -> bytes:
    """-> the HELLO tag as stored: ASCII, NUL-terminated, in the tag field."""
    raw = tag.encode("ascii")
    if not raw or len(raw) >= SPEC["tag"]["length"] or any(b < 0x20 or b > 0x7E for b in raw):
        raise ModError(f"tag {tag!r}: 1..{SPEC['tag']['length'] - 1} printable ASCII characters")
    return raw + bytes(SPEC["tag"]["length"] - len(raw))


def apply(firmware, tag: str = DEFAULT_TAG) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original = section.unpack()
    os = specs.of_main_os(original)
    spec = specs.pick(SPECS, os, ID)
    content = specs.apply_edits(original, spec, os)
    at = spec["tag"]["va"] - BASE
    content[at:at + spec["tag"]["length"]] = tag_bytes(tag)

    return Result(payloads={SECTION: bytes(content)}, extents=extents(os=os),
                  notes=[f"USB SysEx probe on device byte 0x7D, tag {tag!r}: "
                         "python tools/dn2probe.py hello",
                         f"{len(spec['edits']) - 2} hooks and {spec['cave']['used'] + spec['cave2']['used']} B "
                         "in two caves "
                         "in section 3, nothing appended"])


def ram(os: str = "1.11") -> list[Extent]:
    """The scratch buffers and timing words above BSS (`csrc/usbprobe/layout.inc`)."""
    r = specs.pick(SPECS, os, ID)["ram"]
    return [Extent(RAM, r["va"], r["length"], "the probe's buffers and timing state")]


# Bytes that only look like RAM above BSS (`dnfw.mods.ramcheck`):
# 0x402cf6b4: `move.w %sr,%d0 ; move.w #0x2700,%sr` (40 c0 46 fc 27 00);
# 0x402cf6dc: `move.w %d7,%sr ; movem.l ...` (46 c7 48 d1).
NOT_RAM = (0x402CF6B4, 0x402CF6DC)
# Stock's audio DMA buffers (`csrc/usbprobe/dn2_111.inc`: AUD_RX 0x4e6df100, 0x4e6e0100),
# which STATS hashes and PEEK may read. The probe writes nothing there.
READS_STOCK_DMA = (0x402CF854, 0x402CF858, 0x402CF86C, 0x402CF874)
