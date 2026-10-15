"""Boot every combinable pair of mods from reset with the Rust boot gate.

    python scripts/boot_gate_pairs.py out/bus/matrix.json --out out/mod-pairs --with fxmod,lfo4,waverider

Reads `dnfw mods matrix --json`, and for each pair that combines (only pairs with a
mod in `--with`, if given) builds the pair as the matrix does: in the CLI's order (a mod
marked APPLY_LAST last), with each mod's default inputs (`dnfw.cli.mods._apply_default`:
a frame as the boot image, the factory samples for transients), then runs digikit's `boot_gate.exe` on it twice: watching the firmware's fault
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
import tempfile

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


def build_pair(a: str, b: str, syx: pathlib.Path) -> None:
    """The pair's image, as `dnfw mods matrix` builds it for its boots."""
    sys.path.insert(0, str(ROOT / "src"))
    from dnfw.cli import mods as cli
    from dnfw.cli.files import read_image
    from dnfw.firmware.build import build, replacement
    from dnfw.firmware.load import load
    from dnfw.firmware.verify import verify
    firmware = load(read_image(STOCK))
    chosen = sorted((cli.REGISTRY[a], cli.REGISTRY[b]), key=lambda m: getattr(m, "APPLY_LAST", False))
    payloads: dict[int, bytes] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for mod in chosen:
            payloads.update(cli._apply_default(mod, cli._staged(firmware, payloads), pathlib.Path(tmp)).payloads)
    out = build(firmware, {sid: replacement(firmware, sid, pay) for sid, pay in payloads.items()})
    bad = [c.name for c in verify(load(out)).checks if not c.ok]
    if bad:
        raise RuntimeError(f"the rebuilt image fails {bad}")
    syx.write_bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("matrix", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--with", dest="only", default="", help="comma-separated mod ids")
    ap.add_argument("--pairs", default="", help="only these, comma-separated a+b names")
    args = ap.parse_args()
    only = {m for m in args.only.split(",") if m}
    pairs = [p for p in json.loads(args.matrix.read_text())["pairs"]
             if p["combines"] and (not only or {p["a"], p["b"]} & only)
             and (not args.pairs or f"{p['a']}+{p['b']}" in args.pairs.split(","))]
    failed = 0
    for k, p in enumerate(pairs, 1):
        name = f"{p['a']}+{p['b']}"
        folder = args.out / name
        folder.mkdir(parents=True, exist_ok=True)
        syx = folder / f"{name}_DN2_1.11.syx"
        try:
            build_pair(p["a"], p["b"], syx)
        except Exception as exc:                  # noqa: BLE001 -- the verdict names it
            line = f"FAULT: the pair did not build ({exc})"
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
