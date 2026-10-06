"""Build the read-only /waverider route on stock Digitone II 1.11 (step 1 of the store).

    python scripts/build_waverider_route.py -o out/wrroute/wrroute_DN2_1.11.syx [--probe]

`csrc/wrstore/route.c` compiled to run at CODE_VA, as a platform CODE chunk, and one
hook: 0x4002bb70 in the Data API's start-up builder (0x4002b8c8), right after it adds
the kits handler (`docs/data-api-routes.md`). The hook calls `wr_add`, which adds
our handler and then sets the builder's flag, the 8 bytes it replaces. Reads only:
nothing writes to the +Drive. `--probe` also applies usbprobe, so `wr_route` can be
PEEKed on the instrument.

A test build for the emulator bridge first (DNX lists / and /waverider through
digikit's sysex_bridge), not a flash. Builds are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                     # noqa: E402
from dnfw.container.section import compress               # noqa: E402
from dnfw.firmware import build as fwbuild                # noqa: E402
from dnfw.firmware.load import load                       # noqa: E402
from dnfw.mods import platform                            # noqa: E402
from dnfw.patch import cbuild                             # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
SOURCES = [ROOT / "csrc/wrstore/store.c", ROOT / "csrc/wrstore/routekit.c", ROOT / "csrc/wrstore/route.c",
           ROOT / "csrc/wrstore/records.c", ROOT / "csrc/wrstore/poolroute.c"]   # the route alone; the
# Waverider mod links them into its +Drive chunk (dnfw.waverider.drive)
BASE = 0x40000400
MAIN_OS = 3
CODE_VA = 0x467E8000                 # after reloadconfirm's chunk (0x467e0000, 1,208 B)
HOOK = 0x4002BB70
HOOK_STOCK = bytes.fromhex("700113c04059cd20")   # moveq #1,%d0; move.b %d0,0x4059cd20
ENTRIES = ["wr_add", "wr_root_entry", "wr_list_invoker", "wr_register", "wr_nop", "wr_route", "wr_store"]
# the code the route relies on, asserted (docs/data-api-routes.md)
CONTEXT = [
    (0x4002BB4C, "48794059cd24", "the builder passes the registry to the add, for the kits"),
    (0x4002BB78, "4cd73cfc203c4059cd24", "after the hook: restore, return the registry"),
    (0x400EAD92, "2f0b2f0a266f0010246f000c", "the registry's add(registry, &unique_ptr)"),
    (0x400EB084, "4e56fffc2f0a486effff48794021ddf7", "ProjectHandler's root entry, the shape copied"),
    (0x400EB0B6, "", "ProjectHandler's std::function manager, reused"),
    (0x4012C59A, "", "the block driver's read"),
    (0x4014BE0E, "4fefffd848d73cfc", "XXH32"),
]


def compose(stock: bytes) -> tuple[bytes, bytes, dict[str, int]]:
    content = bytearray(stock)
    for va, want, why in CONTEXT:
        if want and content[va - BASE:va - BASE + len(want) // 2].hex() != want:
            raise SystemExit(f"{va:#010x} is not as expected ({why}): not stock 1.11")
    if bytes(content[HOOK - BASE:HOOK - BASE + 8]) != HOOK_STOCK:
        raise SystemExit(f"{HOOK:#010x} is not stock")
    linked = cbuild.build(SOURCES, base=CODE_VA, entries=ENTRIES)
    if linked.bss:
        raise SystemExit(f"{linked.bss} bytes of BSS: nothing zeroes it")
    blob = linked.image + bytes(-len(linked.image) % 4)
    new = bytes.fromhex("4eb9") + struct.pack(">I", linked.symbols["wr_add"]) + bytes.fromhex("4e71")
    content[HOOK - BASE:HOOK - BASE + 8] = new
    return bytes(content), blob, {k: linked.symbols[k] for k in ENTRIES}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-o", "--out", type=pathlib.Path, required=True)
    p.add_argument("--probe", action="store_true", help="also apply usbprobe")
    a = p.parse_args()
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; builds are never overwritten")
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    original, others = platform.split(section.unpack())
    content, blob, syms = compose(original)
    if a.probe:
        from dnfw.mods import usbprobe
        for e in usbprobe.SPEC["edits"]:
            new = bytes.fromhex(e["new"])
            content = content[:e["va"] - BASE] + new + content[e["va"] - BASE + len(new):]
    chunk = platform.area.CodeChunk(CODE_VA, blob).pack()
    joined = platform.join(content, others + [(platform.area.CODE, chunk)])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, joined)}))
    a.out.with_name(a.out.name + ".json").write_text(json.dumps(
        {"code_va": CODE_VA, "code_bytes": len(blob), "symbols": syms, "hook": HOOK}, indent=1) + "\n")
    (a.out.parent / "section_3_MAIN_OS.bin").write_bytes(joined)
    print(f"wrote {a.out}: {len(blob):,} B of code at {CODE_VA:#010x}; "
          + ", ".join(f"{k} {v:#010x}" for k, v in syms.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
