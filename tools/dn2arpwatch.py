"""Watch the arpeggiator a track is playing from, live, on an arpplocks + usbprobe build.

    python tools/dn2arpwatch.py TRACK [--seconds 30] [--port "Digitone II"]

TRACK is 1..16, as the instrument numbers them. Read-only (PEEK), about 10 readings a
second. Each change is printed with the time since start:

- **which sound** the track's notes play from: the per-track table `0x4058e8d8` the
  ISR reads SPEED and N.LEN through, filed by the note set. With `arpplocks` it is
  the track's **shadow** (`0x467c0000 + 1164 t`) when the note had arp locks, else
  the kit's own sound;
- that sound's **arp bytes**: MODE (+351), SPEED (+352), RNG (+353), N.LEN (+354),
  LEN (+355), the step mask (+356..357, which bit is which step as the sound keeps
  it), and the first four step offsets (+358..).

So a lock shows as the sound switching to the shadow with the locked byte, on the
trig that carries it, and back on a trig that does not. Lock nothing and the track
stays on the kit's sound. The layout is `scripts/build_arp_plocks.py`'s (the table
in its docstring); `docs/ideas-backlog.md` §18 has the open questions this answers.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import dn2probe as dp                                          # noqa: E402

TRACK_SOUNDS = 0x4058E8D8          # per-track sound pointer the ISR reads, a long each
SHADOW, SHADOW_STRIDE = 0x467C0000, 1164
ARP_AT, ARP_LEN = 351, 11          # MODE .. offset 3
MODES = ("OFF", "TRUE", "UP", "DOWN", "CYCL", "SHUF", "RAND")


def read(pr, addr: int, length: int) -> bytes:
    r = dp.decode_peek(pr.call(dp.req_peek, addr, length))
    if r["addr"] != addr or len(r["data"]) != length:
        raise ValueError(f"short or misplaced PEEK reply at 0x{addr:08x}")
    return r["data"]


def describe(sound: int, t: int, b: bytes) -> str:
    where = ("shadow" if sound == SHADOW + SHADOW_STRIDE * t
             else "a shadow of another track" if SHADOW <= sound < SHADOW + 16 * SHADOW_STRIDE
             else "the kit's sound")
    mode = MODES[b[0]] if b[0] < len(MODES) else str(b[0])
    mask = struct.unpack(">H", b[5:7])[0]
    offs = [x - 256 if x > 127 else x for x in b[7:11]]
    return (f"{where} 0x{sound:08x}: MODE {mode}, SPEED {b[1]}, RNG {b[2]}, N.LEN {b[3]}, "
            f"LEN {b[4]}, mask {mask:016b}, offsets {offs}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("track", type=int, help="1..16")
    p.add_argument("--seconds", type=float, default=30)
    p.add_argument("--port", default="Digitone II")
    a = p.parse_args(argv)
    if not 1 <= a.track <= 16:
        raise SystemExit("TRACK is 1..16")
    t = a.track - 1
    import winmidi
    port = winmidi.Port(a.port, None, None)
    try:
        pr = dp.Probe(port)
        print("HELLO", dp.decode_hello(pr.call(dp.req_hello))["tag"], flush=True)
        t0, last = time.time(), None
        while time.time() - t0 < a.seconds:
            sound = struct.unpack(">I", read(pr, TRACK_SOUNDS + 4 * t, 4))[0]
            if 0x40000000 <= sound < 0x48000000:
                now = describe(sound, t, read(pr, sound + ARP_AT, ARP_LEN))
            else:
                now = f"no sound pointer (0x{sound:08x})"
            if now != last:
                print(f"{time.time() - t0:6.1f}s  track {a.track}: {now}", flush=True)
                last = now
            time.sleep(0.1)
    finally:
        port.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
