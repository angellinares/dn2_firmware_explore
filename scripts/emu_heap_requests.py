"""Does a request to stock's heap fail once its first block is taken? Stock and a fixed build.

    python scripts/emu_heap_requests.py FIXED.syx [--upload FRAMES]

LFO4's state arrays live in the first block of stock's heap (docs/lfo4-state-memory.md).
The heap is a buddy arena of 32 MiB, and a project image (12.9 MB) takes one of its two
16 MiB halves, so the question is whether taking the first block costs stock anything.

One scenario on plain stock and on FIXED: boot, SAVE PROJECT AS, a compressed project
uploaded as DNX sends it, a walk through the panel's pages. Counted on each: the
allocator's calls, its "no block" exit (`0x401200ec`), the eMMC writes and LZ4 decompress
calls (so the upload is seen to have run), and which of the large request sites ran.

Pass: no failed request on either build, and the same work done on both.

Not covered: a project made on an older OS version, whose load converts it through a
project-sized block of the heap (`0x400e2742..0x400e29f4`, one block at a time); the
sound manager's 2.7 MB requests (`0x40189...`); anything the emulator does not run.
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
ALLOCATE, NO_BLOCK = 0x4011FFE8, 0x401200EC
EMMC_WRITE, DECOMPRESS = 0x4012C780, 0x400EF7E4
# call sites that push a constant size of 1 MiB or more (digikit-up/tools/refscan.py on the allocator's entries)
LARGE = {0x401B02F8: "12,890,132", 0x400F6B1A: "12,890,120", 0x4012F058: "12,890,116", 0x401B01A8: "12,889,620",
         0x40189CE4: "2,782,228", 0x4012DB64: "2,782,212", 0x400CD880: "2,097,152", 0x400CF552: "1,048,576"}


def run(build: pathlib.Path, out: pathlib.Path, upload: list[str]) -> dict[int, int]:
    out.mkdir(parents=True, exist_ok=True)
    steps = touch.SAVE_AS + [f"send:{h}" for h in upload] + ["wait:300M"] + touch.WALK
    script = out / "steps"
    script.write_text(chr(10).join(steps) + chr(10), newline=chr(10))
    pcs = [ALLOCATE, NO_BLOCK, EMMC_WRITE, DECOMPRESS, *LARGE]
    r = subprocess.run([str(touch.PANEL), str(build), "--card-image", str(touch.CARD), "--out", str(out), *touch.SYSEX,
                        "--count", ",".join(f"0x{p:08x}" for p in pcs), "--steps", f"@{script}"],
                       capture_output=True, text=True, timeout=7000, stdin=subprocess.DEVNULL)
    if not r.stdout.strip():
        raise SystemExit(f"{build.name}: no output: {r.stderr[-800:]}")
    d = json.loads(r.stdout.strip().splitlines()[-1])
    if d["outcome"] != "done":
        raise SystemExit(f"{build.name}: {d['outcome']} {d.get('fault')}")
    return {int(w["pc"], 16): w["hits"] for w in d["watched"]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("build")
    p.add_argument("--upload", default=str(ROOT / "out/high-ram-touch/upload_frames.txt"),
                   help="a file of SysEx messages (hex, one a line): a compressed project sent to /projects/3")
    p.add_argument("--out", default=str(ROOT / "out/heap-requests"))
    a = p.parse_args(argv)
    upload = pathlib.Path(a.upload).read_text().split()
    seen = {}
    for name, build in (("stock", STOCK), ("fixed", pathlib.Path(a.build))):
        hits = seen[name] = run(build, pathlib.Path(a.out) / name, upload)
        print(f"  {name}: {hits[ALLOCATE]:,} requests, {hits[NO_BLOCK]} failed; {hits[EMMC_WRITE]} eMMC writes, "
              f"{hits[DECOMPRESS]} LZ4 decompress calls; large sites reached: "
              + (", ".join(f"{LARGE[pc]} x{hits[pc]}" for pc in LARGE if hits[pc]) or "none"))
    ok = (not seen["stock"][NO_BLOCK] and not seen["fixed"][NO_BLOCK]
          and seen["stock"][DECOMPRESS] > 0
          and all(seen["stock"][pc] == seen["fixed"][pc] for pc in (EMMC_WRITE, DECOMPRESS)))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
