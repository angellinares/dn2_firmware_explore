"""Build the +Drive read probe: Waverider (as shipped) + the usbprobe + three sector reads.

    python scripts/build_driveread_probe.py -o 00_Resources/02_Builds/waverider-driveread-usbprobe_DN2_1.11.syx

The first step of loading wavetables from the +Drive: does the stock block driver
`0x4012c59a(sector, bytes, buf)`, called from our code in the UI task, read our own
region? The page renderer is compiled with `WR_DRIVEREAD` (csrc/waverider/page.c): once,
5 s after boot, it reads sector 0 (the +Drive header, the control), project slot 0 and
our region's base (sector 0x600000), and keeps each one's return and first 32 bytes in
`wr_drive`, which the probe reads with PEEK. Reads only: nothing is written to the
+Drive.

The shipped mod (`src/dnfw/mods/waverider_code.json`) is untouched: this composes its
own spec in memory, as `build_modview_probe.py` does, and writes `<out>.driveread.json`
beside the build with `wr_drive`'s address.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                   # noqa: E402
from dnfw.cli.main import main as dnfw_main             # noqa: E402
from dnfw.firmware.load import load                     # noqa: E402
from dnfw.mods import waverider as waverider_mod        # noqa: E402
from dnfw.patch.assemble import assemble                # noqa: E402
from dnfw.waverider import coldfire as CF               # noqa: E402
from dnfw.waverider import cpage                        # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


def spec_with_driveread() -> tuple[dict, int]:
    stock = load(read_image(STOCK)).container.find(3).unpack()
    seen: dict[str, int] = {}

    def compile_c(header: str, *, base: int):
        image, symbols, bss = cpage.compile_page("#define WR_DRIVEREAD 1\n" + header, base=base)
        seen.update(symbols)
        return image, symbols, bss

    built = CF.compose(stock, assemble, compile_c)
    spec = dict(waverider_mod.SPEC)
    spec["edits"] = sorted((e.to_json() for e in built["edits"]), key=lambda e: e["va"])
    spec["layout"] = {k: v for k, v in sorted(built["layout"].items())}
    spec["chunk"] = {"load": built["chunk"]["load"], "code": built["chunk"]["code"].hex()}
    return spec, seen["wr_drive"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-o", "--out", type=pathlib.Path, required=True)
    p.add_argument("--tag", default="wrdrv", help="the probe's HELLO tag")
    a = p.parse_args()
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; builds are never overwritten")
    spec, block = spec_with_driveread()
    waverider_mod.SPEC = spec
    code = dnfw_main(["mods", "apply", str(STOCK), "--mod", "waverider", "--mod", "usbprobe",
                      "--probe-tag", a.tag, "-o", str(a.out)])
    if code:
        return code
    side = a.out.with_name(a.out.name + ".driveread.json")
    side.write_text(json.dumps({"tag": a.tag, "wr_drive": block,
                                "layout": "magic u32, state u32 (1 started, 2 done), when u32 (ticks), "
                                          "rc[3] u32, head[3][32] (sector 0, 0x58000, 0x600000)"},
                               indent=1) + "\n")
    print(f"wr_drive at {block:#010x}; wrote {side}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
