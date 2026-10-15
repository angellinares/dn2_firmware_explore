"""Boot every combinable pair of mods from reset with the Rust boot gate.

    python scripts/boot_gate_pairs.py out/bus/matrix.json --out out/mod-pairs --with fxmod,lfo4,waverider

Reads `dnfw mods matrix --json`, and for each pair that combines (only pairs with a
mod in `--with`, if given) builds the pair with `dnfw mods apply`, as a user would,
then runs digikit's `boot_gate.exe` on it twice: watching the firmware's fault
reporter `0x4011ea6a` and the second fault path `0x400cf678`. Each pair gets
`<out>/<a>+<b>/boot.txt`, whose last line is the verdict that
`dnfw mods matrix --boots` writes into the boots list:

    booted, 0 hits on both watches (boot_gate from reset, 2026-10-15)

A pair that faults, or never reaches the UI, says so on that line with the gate's
own outcome and PC. The pair's `.syx` is deleted afterwards; only the verdict stays.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
GATE = pathlib.Path("D:/01_Code/Z_Personal/digikit-rust/out/native/target-host/release/examples/boot_gate.exe")
WATCHES = ("0x4011ea6a", "0x400cf678")


def gate(syx: pathlib.Path, watch: str) -> dict:
    done = subprocess.run([str(GATE), str(syx), "--watch", watch], capture_output=True, text=True,
                          timeout=300)
    line = next((ln for ln in reversed(done.stdout.splitlines()) if ln.startswith("{")), "{}")
    return json.loads(line)


def verdict(results: list[dict]) -> str:
    day = datetime.date.today().isoformat()
    if all(r.get("outcome") == "booted" and all(w["hits"] == 0 for w in r.get("watched", []))
           for r in results):
        return f"booted, 0 hits on both watches (boot_gate from reset, {day})"
    bad = next(r for r in results if r.get("outcome") != "booted"
               or any(w["hits"] for w in r.get("watched", [])))
    hits = ", ".join(f"{w['pc']} {w['hits']} hits" for w in bad.get("watched", []))
    return (f"FAULT: boot_gate {bad.get('outcome')} at {bad.get('pc')} in {bad.get('phase')} "
            f"({hits}; {day})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("matrix", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--with", dest="only", default="", help="comma-separated mod ids")
    args = ap.parse_args()
    only = {m for m in args.only.split(",") if m}
    pairs = [p for p in json.loads(args.matrix.read_text())["pairs"]
             if p["combines"] and (not only or {p["a"], p["b"]} & only)]
    failed = 0
    for k, p in enumerate(pairs, 1):
        name = f"{p['a']}+{p['b']}"
        folder = args.out / name
        folder.mkdir(parents=True, exist_ok=True)
        syx = folder / f"{name}_DN2_1.11.syx"
        built = subprocess.run(["dnfw", "mods", "apply", "--mod", p["a"], "--mod", p["b"], "-o", str(syx),
                                str(STOCK)], capture_output=True, text=True, cwd=ROOT, timeout=900)
        if built.returncode or not syx.exists():
            line = f"FAULT: the pair did not build ({built.stdout.strip().splitlines()[-1:]})"
            results = []
        else:
            results = [gate(syx, w) for w in WATCHES]
            line = verdict(results)
            syx.unlink()
        (folder / "boot.txt").write_text("\n".join(json.dumps(r) for r in results) + "\n" + line + "\n",
                                         encoding="utf-8", newline="\n")
        failed += not line.startswith("booted")
        print(f"[{k}/{len(pairs)}] {name}: {line}", flush=True)
    print(f"{len(pairs) - failed} of {len(pairs)} pairs booted")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
