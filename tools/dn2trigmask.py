"""Watch the four trigger masks of the live DSP frame, to tell a held gate from a trigger.

    python tools/dn2trigmask.py [--seconds 15] [--out out/probe-frames/trigmask.json]

Polls the 8 bytes at frame offsets 34..41 (`dnfw.waverider.frame.TRIG_MASKS`, the
frame the audio ISR sends the SHARC, at `0x80005e60`) over the read-only USB probe,
as fast as the probe answers, and prints one line a second: how many readings had
each mask non-zero, and the values seen.

A frame lasts 0.67 ms and a probe reading takes several, so a one-frame trigger is
almost never caught, while a mask that stays set while a note is held is non-zero in
every reading for as long as the note is held. That is the question
docs/drive-load-command.md "Open" 1 asks: which frames a load frame may replace.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import dn2probe as dp                                          # noqa: E402

FRAME = 0x80005E60
MASKS = (34, 36, 38, 40)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seconds", type=float, default=15.0)
    p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("out/probe-frames/trigmask.json"))
    p.add_argument("--port", default="Digitone II")
    a = p.parse_args(argv)
    import winmidi
    port = winmidi.Port(a.port, None, None)
    readings = []
    try:
        pr = dp.Probe(port)
        start = time.monotonic()
        second, line = 0, None
        while (now := time.monotonic() - start) < a.seconds:
            r = dp.decode_peek(pr.call(dp.req_peek, FRAME + MASKS[0], 8))
            words = struct.unpack(">4H", r["data"])
            readings.append((round(now, 3), words))
            if int(now) != second or line is None:
                if line is not None:
                    print(summary(second, line))
                second, line = int(now), []
            line.append(words)
        if line:
            print(summary(second, line))
    finally:
        port.close()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"masks": MASKS, "readings": readings}), encoding="utf-8")
    print(f"{len(readings)} readings saved to {a.out}")
    return 0


def summary(second: int, words: list[tuple[int, ...]]) -> str:
    cells = []
    for k, at in enumerate(MASKS):
        set_ = [w[k] for w in words if w[k]]
        values = sorted({f"{v:04x}" for v in set_})
        cells.append(f"+{at}: {len(set_):3d}/{len(words)} {','.join(values) or '-'}")
    return f"t={second:3d}s  " + "   ".join(cells)


if __name__ == "__main__":
    raise SystemExit(main())
