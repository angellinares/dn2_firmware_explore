"""The MODS page in the emulator, from reset: SETTINGS > SYSTEM > MODS opens, scrolls and goes back.

    python scripts/emu_mods_page.py BUILD.syx [--out DIR]

Boots BUILD with digikit's `panel_drive` (set PANEL_DRIVE, as `scripts/emu_seqplay.py` needs),
with the firmware's fault reporter watched. The keys: [SETTINGS], [DOWN] to SYSTEM, [YES], [DOWN]
to the last entry, [YES], [DOWN] once for each row, then [NO].

The checks:

- the build boots and the fault reporter never runs;
- SYSTEM's last entry opens a page, and the page differs from SYSTEM;
- every [DOWN] on the page moves the cursor, as many times as the build's page has rows less one,
  and one more [DOWN] stays on the last row, as in stock's menus;
- [NO] gives SYSTEM back, the same frame as before.

The rows come from the build itself (`dnfw.mods.modspage.existing`), and the script prints them.
The frames are in DIR, white on black as `.png`, for a look at the names and versions.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import emu_seqplay as ES  # noqa: E402

from dnfw.cli.files import read_image  # noqa: E402
from dnfw.firmware.load import load  # noqa: E402
from dnfw.mods import modspage, specs  # noqa: E402

SETTINGS, YES, NO, DOWN = 8, 10, 12, 14
# the stock image each OS boots against (digikit's --base), and its fault reporter
BASES = {"1.11": ("2af43e65e3d8390b41c9f66222620f8cce027d73ed87db00c80b440f628472e0", "0x4011ea6a"),
         "1.12": ("7e5b8a733d4ab1fdf7e5d22757f7d8eddaa3cbf71d0858874a791844c02ceb35", "0x4011ed4a")}
SETTINGS_ENTRIES, SYSTEM_ENTRIES = 7, 4          # [DOWN]s to SYSTEM, and to the entry after MASTER TUNE


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "out/emu-mods-page")
    a = ap.parse_args(argv)
    firmware = load(read_image(a.build))
    os = specs.of_main_os(firmware.container.find(3).unpack())
    rows = modspage.existing(firmware)
    print(f"OS {os}, {len(rows)} rows:")
    for name, value in rows:
        print(f"  {name:<20}{value}")
    if not rows:
        print("FAIL the build has no MODS page")
        return 1
    base, reporter = BASES[os]
    a.out.mkdir(parents=True, exist_ok=True)

    def tap(code, wait="40M"):
        return [f"tap:{code}", f"wait:{wait}"]

    s = ["wait:1100M"] + tap(NO) + tap(NO) + tap(SETTINGS, "80M")
    s += tap(DOWN) * SETTINGS_ENTRIES + tap(YES, "120M") + tap(DOWN) * SYSTEM_ENTRIES + ["frame:system"]
    s += tap(YES, "120M") + ["frame:row0"]
    for k in range(1, len(rows) + 1):
        s += tap(DOWN) + [f"frame:row{k}"]
    s += tap(NO, "120M") + ["frame:back"]
    cmd = [str(ES.panel_drive()), str(a.build), "--base", base, "--out", str(a.out), "--watch", reporter,
           "--steps", ",".join(s)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    lines = r.stdout.strip().splitlines()
    if not lines:
        raise SystemExit(f"panel_drive said nothing (rc {r.returncode}): {r.stderr[-2000:]}")
    report = json.loads(lines[-1])
    frame = {n: (a.out / f"{n}.pbm").read_bytes() for n in ["system", "back"] + [f"row{k}" for k in range(len(rows) + 1)]}

    from PIL import Image, ImageOps
    for n in frame:
        im = ImageOps.invert(Image.open(a.out / f"{n}.pbm").convert("L"))
        im.resize((im.width * 4, im.height * 4), Image.NEAREST).save(a.out / f"{n}.png")

    seen = [frame[f"row{k}"] for k in range(len(rows))]
    checks = {
        "the build boots, and the fault reporter never runs":
            report.get("outcome") == "done" and all(w["hits"] == 0 for w in report.get("watched", [])),
        "SYSTEM's last entry opens a page": frame["row0"] != frame["system"],
        "every DOWN moves the cursor": all(x != y for x, y in zip(seen, seen[1:])),
        "one more DOWN stays on the last row": frame[f"row{len(rows)}"] == frame[f"row{len(rows) - 1}"],
        "NO gives SYSTEM back": frame["back"] == frame["system"],
    }
    for what, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + what)
    print(f"frames: {a.out}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
