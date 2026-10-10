"""How far stock's live blocks reach into its heap, read from the allocator's own bitmap.

    python scripts/emu_heap_reach.py [FIXED.syx] [--upload FRAMES]

Stock's allocator (`0x4011ffe8`) sets one bit of its bitmap (`0x445a1e40`, a bit per
16-byte unit of the 32 MiB arena at `0x4464abf0`) at the last unit of every live block,
and counts its live blocks at `0x4029ebb4`. So the bitmap, read at a quiet moment, gives
the number of live blocks and where the highest one ends: how much of the arena stock
holds at rest. A block that is taken and released inside one operation (a project-sized
buffer during a save) is not seen; `scripts/emu_heap_requests.py` covers those.

Read at four points of one panel_drive run: after start-up, after SAVE PROJECT AS, after a
compressed project uploaded as DNX sends it, after a walk through the panel's pages. On
plain stock, and on FIXED when given.

Control: the bits counted must equal the allocator's own count at every point.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import emu_high_ram_touch as touch                          # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
BITMAP, BITMAP_BYTES, ARENA, LIVE_COUNT, UNIT = 0x445A1E40, 0x40000, 0x4464ABF0, 0x4029EBB4, 16
POINTS = ("after start-up", "after SAVE PROJECT AS", "after the DNX upload", "after the panel walk")
MIB = 1 << 20


def run(build: pathlib.Path, out: pathlib.Path, upload: list[str]) -> list[tuple[int, int, int]]:
    """(live blocks by the bitmap, the allocator's count, bytes from the arena's base to the
    end of the highest live block) at each of POINTS."""
    out.mkdir(parents=True, exist_ok=True)
    read = [f"peek:0x{BITMAP:08x}:{BITMAP_BYTES}", f"peek:0x{LIVE_COUNT:08x}:4"]
    steps = read + touch.SAVE_AS + read + [f"send:{h}" for h in upload] + ["wait:300M"] + read + touch.WALK + read
    script = out / "steps"
    script.write_text(chr(10).join(steps) + chr(10), newline=chr(10))
    r = subprocess.run([str(touch.PANEL), str(build), "--card-image", str(touch.CARD), "--out", str(out), *touch.SYSEX,
                        "--steps", f"@{script}"], capture_output=True, text=True, timeout=7000, stdin=subprocess.DEVNULL)
    if not r.stdout.strip():
        raise SystemExit(f"{build.name}: no output: {r.stderr[-800:]}")
    d = json.loads(r.stdout.strip().splitlines()[-1])
    if d["outcome"] != "done":
        raise SystemExit(f"{build.name}: {d['outcome']} {d.get('fault')}")
    peeks = [bytes.fromhex(x["hex"]) for x in d["results"] if "hex" in x]
    rows = []
    for bitmap, count in zip(peeks[0::2], peeks[1::2]):
        ends = [8 * i + bit for i, byte in enumerate(bitmap) if byte for bit in range(8) if byte >> bit & 1]
        rows.append((len(ends), int.from_bytes(count, "big"), UNIT * (max(ends) + 1)))
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("build", nargs="?", help="a build to read beside stock")
    p.add_argument("--upload", default=str(ROOT / "out/high-ram-touch/upload_frames.txt"),
                   help="a file of SysEx messages (hex, one a line): a compressed project sent to /projects/3")
    p.add_argument("--out", default=str(ROOT / "out/heap-reach"))
    a = p.parse_args(argv)
    upload = pathlib.Path(a.upload).read_text().split()
    ok = True
    for name, build in [("stock", STOCK)] + ([("fixed", pathlib.Path(a.build))] if a.build else []):
        print(f"  {name}:")
        for point, (bits, count, reach) in zip(POINTS, run(build, pathlib.Path(a.out) / name, upload)):
            ok &= bits == count
            print(f"    {point:<22} {bits:,} live blocks (the allocator's count: {count:,}); "
                  f"the highest ends {reach / MIB:.2f} MiB into the 32 MiB arena, at {ARENA + reach:#010x}")
    print("PASS" if ok else "FAIL: the bitmap and the allocator's count disagree")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
