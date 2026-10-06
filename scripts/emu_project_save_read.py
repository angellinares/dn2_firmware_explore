"""Save a fresh project on a firmware image in the emulator, then read it back over the Data API.

    python scripts/emu_project_save_read.py SYX OUT.bin [--card out/dk-dn2-card.img]

For DNX (2026-10-06): does stock 1.11 itself write the 12-byte `X | ffffffff | X |
3fffffff` runs DNX found in a damaged project? A project saved here was never used,
so whatever it carries, 1.11's save put there.

One panel_drive run (digikit-rust), on the card image (its writes stay in memory):
1. boot (or resume a cached boot state), dismiss the MMC notice;
2. SETTINGS > PROJECT > SAVE PROJECT AS > 002 > YES: the stock save to slot 2
   (`0x400f6960` with slot 1, then 128 for the working copy, measured);
3. the Data API, through the SysEx router as Transfer sends it: open `/projects/2`
   with a 16 KiB chunk size, every sequence until the file ends, close.
OUT.bin is the file as read, the 31-byte container header included, as DNX's reads are.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from emu_waverider_rename import Frames, dec          # noqa: E402

PANEL = ROOT.parent / "digikit-rust/out/native/target-host/release/examples/panel_drive.exe"
ROUTER = ["--call-at", "0x4002e464", "--call-fn", "0x4012166e", "--call-args", "2",
          "--capture", "0x401233f2:0:1"]
CHUNK = 0x4000                       # what the device grants (the open's reply)
SEQUENCES = 820                      # 12.9 MB / 16 KiB = 787, and some to spare
SAVE = ("tap:12,wait:30M,tap:8,wait:30M,tap:10,wait:30M,tap:14,wait:20M,tap:10,wait:60M,"
        "tap:14,wait:20M,tap:10,wait:60M,tap:10,wait:900M,frame:saved")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("syx")
    ap.add_argument("out")
    ap.add_argument("--card", default=str(ROOT / "out/dk-dn2-card.img"))
    a = ap.parse_args()

    f = Frames()
    f.frame("open", 0x54, b"/projects/2\0" + struct.pack(">I", CHUNK))
    for k in range(SEQUENCES):
        f.frame(f"seq{k}", 0x55, struct.pack(">II", 1, k))
    f.frame("close", 0x56, struct.pack(">I", 1))
    steps = SAVE + "," + ",".join(f"send:{h}" for _, h in f.lines)
    out_dir = pathlib.Path(a.out).parent
    steps_file = out_dir / (pathlib.Path(a.out).stem + ".steps")
    steps_file.write_text(steps.replace(",", "\n") + "\n")       # too long for a command line
    r = subprocess.run([str(PANEL), a.syx, "--card-image", a.card, "--out", str(out_dir), *ROUTER,
                        "--steps", f"@{steps_file}"], capture_output=True, text=True, timeout=3600)
    report = json.loads(r.stdout.strip().splitlines()[-1])
    if report["outcome"] != "done":
        print("FAIL", report["outcome"], report.get("fault"))
        return 1
    # the sender's pieces, joined into messages at each F7 (7-bit data never holds one)
    stream = b"".join(bytes.fromhex(c["hex"]) for c in report["captures"])
    replies = [m + b"\xf7" for m in stream.split(b"\xf7") if m.startswith(b"\xf0")]
    data = bytearray()
    for m in replies:
        d = dec(m.hex())[5:]
        if len(d) < 22 or d[0] != 1:
            continue
        seq = struct.unpack_from(">I", d, 5)[0]
        length = struct.unpack_from(">I", d, 18)[0]
        if seq == 0 or length == 0:
            continue
        data += d[22:22 + length]
    pathlib.Path(a.out).write_bytes(bytes(data))
    print(f"{len(replies)} replies, {len(data):,} bytes to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
