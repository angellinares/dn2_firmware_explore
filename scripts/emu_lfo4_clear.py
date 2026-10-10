"""Clearing a pattern from the pattern list drops LFO4's values, in the emulator.

    python scripts/emu_lfo4_clear.py BUILD.syx --symbols out/<build>/symbols.json
                                     [--control OLD.syx --control-symbols out/<old>/symbols.json]

The owner, 2026-10-10, on rivvi's mod set: [PTN], the pattern's trig + clear, and track
1 kept its LFO4 settings; after SAVE PROJECT and a reload they were still there. The
clear sets each of the kit's 16 sounds to its defaults through `Sound::init`
(`0x400e7e66`), field by field, then saves the kit (`0x400dde44`, from `0x400308f6`).
LFO4's values live in a table keyed by the sound's address, so nothing removed the entry
and the save wrote it into the cleared pattern.

One panel_drive boot from reset per build. An LFO4 entry is planted for the first sound
of the playing kit (`0x4210c0c0`, the kit the clear resets) and one for a sound the clear
does not touch (`0x42117ba2`); then [PTN], [TRIG 1] + [FUNC] + [PLAY]. Checked after it:

| check | pass |
|---|---|
| the cleared sound's entry | gone from the table |
| the cleared pattern's stored sound | LFO4's eight ids are zero |
| the other sound's entry | still there, its values unchanged |
| `lfo4_sound_inits` | counted the resets (when the build has it) |

`--control` runs a build without the fix beside it: there the entry must survive and
the stored ids must hold the planted values, or the test proves nothing.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PANEL = ROOT.parent / "digikit-rust/out/native/target-host/release/examples/panel_drive.exe"

KNUTH, SLOTS, PARAMS = 2654435761, 256, 8
CLEARED, KEPT = 0x4210C0C0, 0x42117BA2      # the playing kit's sound 0; another kit buffer's
STORED_VALUES = 0x410ADBC4                  # pattern A01's stored sound 0, its value block
IDS = (4, 8, 12, 16, 20, 24, 28, 32)        # LFO4's stored ids (csrc/lfo4/store.c)
PLANT = {CLEARED: (0x7000, 0x0300, 0x4000, 0x1D00, 0x0A00, 0x2000, 0x0300, 0x5000),
         KEPT: (0x7000, 0x0300, 0x4000, 0x2300, 0x0700, 0x0000, 0x0100, 0x5111)}
NO, FUNC, PLAY, PTN, TRIG1 = 12, 17, 20, 23, 25


def home(key: int) -> int:
    return ((key * KNUTH) & 0xFFFFFFFF) >> 24


def steps(sym: dict) -> list[str]:
    assert len({home(k) for k in PLANT}) == len(PLANT), "the planted keys share a slot"
    out = [f"tap:{NO}", "wait:30M"]
    for key, values in PLANT.items():
        out.append(f"poke:0x{sym['ext_key'] + 4 * home(key):08x}:{key:08x}")
        out.append(f"poke:0x{sym['ext_val'] + 16 * home(key):08x}:" + "".join(f"{v:04x}" for v in values))
    out += [f"poke:0x{sym['ext_hi']:08x}:{max(PLANT):08x}", f"poke:0x{sym['ext_lo']:08x}:{min(PLANT):08x}",
            f"poke:0x{sym['ext_live']:08x}:{len(PLANT):08x}"]
    read = [f"peek:0x{sym['ext_key']:08x}:{4 * SLOTS}", f"peek:0x{sym['ext_val']:08x}:{16 * SLOTS}",
            f"peek:0x{STORED_VALUES:08x}:72"]
    if "lfo4_sound_inits" in sym:
        read.append(f"peek:0x{sym['lfo4_sound_inits']:08x}:4")
    return out + read + [f"tap:{PTN}", "wait:40M", f"press:{TRIG1}", "wait:10M", f"press:{FUNC}", "wait:5M",
                         f"tap:{PLAY}", "wait:10M", f"release:{FUNC}", "wait:5M", f"release:{TRIG1}",
                         "wait:80M"] + read


def table(keys: bytes, vals: bytes) -> dict[int, tuple]:
    out = {}
    for s in range(SLOTS):
        key = struct.unpack_from(">I", keys, 4 * s)[0]
        if key:
            out[key] = struct.unpack_from(">8H", vals, 16 * s)
    return out


def run(build: str, symbols: str) -> dict:
    sym = {k: int(v, 16) for k, v in json.loads(pathlib.Path(symbols).read_text()).items()}
    with tempfile.TemporaryDirectory() as tmp:
        script = pathlib.Path(tmp) / "steps"
        script.write_text("\n".join(steps(sym)), newline="\n")
        r = subprocess.run([str(PANEL), build, "--out", tmp, "--steps", f"@{script}"],
                           capture_output=True, text=True, timeout=600)
    d = json.loads(r.stdout)
    if d["outcome"] != "done":
        raise SystemExit(f"{build}: {d['outcome']} {d['fault']}")
    peeks = [bytes.fromhex(x["hex"]) for x in d["results"] if "peek" in x]
    n = len(peeks) // 2
    before, after = peeks[:n], peeks[n:]
    return {"before": table(before[0], before[1]), "after": table(after[0], after[1]),
            "stored": tuple(struct.unpack_from(">H", after[2], 2 * i)[0] for i in IDS),
            "inits": (struct.unpack(">I", after[3])[0] - struct.unpack(">I", before[3])[0]) if n > 3 else None}


def report(name: str, checks: dict[str, bool]) -> bool:
    for what, ok in checks.items():
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {what}")
    return all(checks.values())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("build")
    p.add_argument("--symbols", required=True)
    p.add_argument("--control", help="a build without the fix, run beside it")
    p.add_argument("--control-symbols")
    a = p.parse_args(argv)

    r = run(a.build, a.symbols)
    ok = report("fixed", {
        "the planted entries were in the table before the clear": all(r["before"].get(k) == v for k, v in PLANT.items()),
        "the cleared sound's entry is gone": CLEARED not in r["after"],
        "the cleared pattern's stored sound has no LFO4 values": not any(r["stored"]),
        "the other sound's entry is unchanged": r["after"].get(KEPT) == PLANT[KEPT],
        f"Sound::init was counted ({r['inits']})": bool(r["inits"]),
    })
    if a.control:
        c = run(a.control, a.control_symbols)
        ok &= report("control", {
            "without the fix the entry survives the clear": c["after"].get(CLEARED) == PLANT[CLEARED],
            "and the save writes it into the cleared pattern": c["stored"] == PLANT[CLEARED],
        })
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
