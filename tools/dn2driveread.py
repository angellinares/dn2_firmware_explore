"""Read the +Drive read probe's results (waverider-driveread builds) over the USB probe.

    python tools/dn2driveread.py [--addr 0x4670f360]

`csrc/waverider/page.c` (`WR_DRIVEREAD`) reads three sectors once, 5 s after boot, with
the stock block driver, and keeps them in `wr_drive`: magic 'WRDR', state (1 started,
2 done), the tick it ran at, each read's return, and each sector's first 32 bytes.
The address comes from `<build>.driveread.json` beside the build (matched by the HELLO
tag), or `--addr`. Only reads; read-only PEEK. Quit Transfer first.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
BUILDS = HERE.parent / "00_Resources" / "02_Builds"
SECTORS = (("sector 0, the +Drive header (control: BE EF BA CE)", 0),
           ("project slot 0", 0x58000), ("our region's base", 0x600000))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--addr", type=lambda s: int(s, 0), default=None)
    p.add_argument("--port", default="Digitone II")
    a = p.parse_args(argv)
    import dn2probe as dp
    import winmidi
    port = winmidi.Port(a.port, None, None)
    try:
        pr = dp.Probe(port)
        tag = dp.decode_hello(pr.call(dp.req_hello))["tag"]
        addr = a.addr
        if addr is None:
            for f in BUILDS.glob("*.driveread.json"):
                meta = json.loads(f.read_text())
                if meta.get("tag") == tag:
                    addr = meta["wr_drive"]
            if addr is None:
                print(f"HELLO tag {tag!r}: no .driveread.json with that tag; pass --addr")
                return 1
        r = dp.decode_peek(pr.call(dp.req_peek, addr, 24 + 96))
        if r["addr"] != addr or len(r["data"]) != 24 + 96:
            print(f"short PEEK at {addr:#010x}")
            return 1
        raw = r["data"]
    finally:
        port.close()
    magic, state, when, *rc = struct.unpack(">6I", raw[:24])
    print(f"{tag}: wr_drive at {addr:#010x}, magic {magic:#010x} ({'ok' if magic == 0x57524452 else 'WRONG'}), "
          f"state {state} ({ {0: 'not run yet', 1: 'started, never finished (a hang)', 2: 'done'}.get(state, '?') }), "
          f"at tick {when} ({when / 120:.1f} s)")
    for k, (what, sector) in enumerate(SECTORS):
        head = raw[24 + 32 * k:24 + 32 * (k + 1)]
        print(f"  {what:<52} sector {sector:#09x}  rc {rc[k] if rc[k] < 0x80000000 else rc[k] - (1 << 32)}  "
              f"{head.hex(' ')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
