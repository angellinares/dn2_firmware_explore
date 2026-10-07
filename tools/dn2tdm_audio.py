"""The SHARC -> ColdFire SSI0 audio window, slot by slot, from a usbprobe build.

    python tools/dn2tdm_audio.py LABEL [--n 10] [--dir out/tdm-audio]

The ColdFire receives the SHARC's SSI0 stream into a double-buffered window at
`0x4E6DF100` (eDMA channel 48; docs/audio-dma.md): 2 x 2,048 bytes, each half 32 frames
of 64 bytes, 16 longword slots a frame (TDM). The reply records the DSP also sends
(tools/dn2reply_audio.py) carry tracks 7-16; this reads the other link, to see which
slots carry what.

It reads the whole 4 KB window N times (read-only PEEK), saves each to DIR/LABEL.K.bin,
and prints, per slot, how many of the N x 64 frames are non-zero and their RMS, taking
the slot as a 24-bit sample in the longword's low three bytes, sign-extended (the raw
window read on the instrument, 2026-10-08: track 6 at about +-780,000). Until then this
shifted it down by 8 as well, so the levels it printed were 256 times too small.

Read-only: PEEK only. Quit Transfer first (memory probe-after-flash).
"""
from __future__ import annotations

import argparse
import math
import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import dn2probe as dp                                          # noqa: E402
from dn2probe_frame import read                                # noqa: E402

BASE, LENGTH = 0x4E6DF100, 0x1000
FRAME_BYTES, SLOTS = 64, 16


def s24(b: bytes) -> int:
    v = int.from_bytes(b, "big") & 0xFFFFFF
    return v - (1 << 24) if v & 0x800000 else v


def slots(blobs: list[bytes]) -> list[tuple[int, float]]:
    """-> per slot (non-zero frames, RMS) over every frame of every reading."""
    out = []
    for s in range(SLOTS):
        vals = [s24(blob[f + 4 * s: f + 4 * s + 4])
                for blob in blobs for f in range(0, len(blob), FRAME_BYTES)]
        nz = sum(1 for v in vals if v)
        out.append((nz, math.sqrt(sum(v * v for v in vals) / len(vals)) if vals else 0.0))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("label")
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--dir", type=pathlib.Path, default=pathlib.Path("out/tdm-audio"))
    p.add_argument("--port", default="Digitone II")
    a = p.parse_args(argv)
    import winmidi
    a.dir.mkdir(parents=True, exist_ok=True)
    port = winmidi.Port(a.port, None, None)
    blobs = []
    try:
        pr = dp.Probe(port)
        for k in range(a.n):
            blob = read(pr, BASE, LENGTH)
            (a.dir / f"{a.label}.{k:02d}.bin").write_bytes(blob)
            blobs.append(blob)
            time.sleep(0.05)
    finally:
        port.close()
    frames = a.n * LENGTH // FRAME_BYTES
    print(f"{a.label}: {a.n} readings x {LENGTH // FRAME_BYTES} frames")
    for s, (nz, rms) in enumerate(slots(blobs)):
        bar = "#" * min(40, int(rms / 2 ** 23 * 400)) if rms else ""
        print(f"  slot {s:2d}  non-zero {nz:4d}/{frames}  rms {rms:10.0f}  {bar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
