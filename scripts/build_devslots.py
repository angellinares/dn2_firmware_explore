"""Build the /devslots read build: a Discord user's mod set + Waverider with the /devslots route.

    python scripts/build_devslots.py -o 00_Resources/02_Builds/devslots-wr-layermidi-arpmodes-lfowaves-lfo4-bootscreen_DN2_1.11.syx

The route (csrc/wrstore/slotroute.c, docs/for-dnx-devslots.md) lets DNX read the two
raw slots the start-up reader takes the device settings from (sectors 0x40000 and
0x48000) and the running copy in RAM, 272 bytes each. Reads only.

The shipped mod (`src/dnfw/mods/waverider_code.json`) is untouched: the +Drive chunk is
linked again here with `WR_SLOTROUTE` and slotroute.c, in memory, as
`build_driveread_probe.py` does for the page.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                   # noqa: E402
from dnfw.cli.main import main as dnfw_main             # noqa: E402
from dnfw.firmware.load import load                     # noqa: E402
from dnfw.mods import waverider as waverider_mod        # noqa: E402
from dnfw.patch import cbuild                           # noqa: E402
from dnfw.patch.assemble import assemble                # noqa: E402
from dnfw.waverider import coldfire as CF               # noqa: E402
from dnfw.waverider import cpage                        # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
ROUTE = ROOT / "csrc/wrstore/slotroute.c"
MODS = ["waverider", "layermidi", "arpmodes", "lfowaves", "lfo4", "bootscreen"]
BOOT = ROOT / "00_Resources/08_MyBuilds/waverider_glyph_boot.pgm"


def build_with_route(sources, *, defines=None, **kw):
    return cbuild.build([*sources, ROUTE], defines={**(defines or {}), "WR_SLOTROUTE": 1}, **kw)


def spec_with_route() -> dict:
    stock = load(read_image(STOCK)).container.find(3).unpack()
    built = CF.compose(stock, assemble, cpage.compile_page, build_with_route)
    spec = dict(waverider_mod.SPEC)
    spec["edits"] = sorted((e.to_json() for e in built["edits"]), key=lambda e: e["va"])
    spec["layout"] = {k: v for k, v in sorted(built["layout"].items())}
    spec["chunk"] = {"load": built["chunk"]["load"], "code": built["chunk"]["code"].hex()}
    spec["drive"] = {**spec["drive"], "load": built["drive"]["load"], "code": built["drive"]["code"].hex()}
    return spec


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-o", "--out", type=pathlib.Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; builds are never overwritten")
    waverider_mod.SPEC = spec_with_route()
    args = ["mods", "apply", str(STOCK)]
    for m in MODS:
        args += ["--mod", m]
    return dnfw_main(args + ["--boot-image", str(BOOT), "-o", str(a.out)])


if __name__ == "__main__":
    raise SystemExit(main())
