"""Estimate a build's SHARC cycles in digikit's runner, and tune the estimate from the
instrument.

    python scripts/sharc_cycles.py estimate BUILD.syx [BUILD.syx ...] [--blocks 4]
    python scripts/sharc_cycles.py compare LABEL [LABEL ...] [--against CASE]
    python scripts/sharc_cycles.py fit MEASUREMENTS.json [--free KEY ...] [--write]

`estimate` runs each build's section 7 (the DSP image, read from the .syx) through
the cases below, the way scripts/sharc_waverider_p3_cost.py does (track 0 Waverider,
a note at block 1, tracks 1-15 MIDI), with the cycle model recording every step
(scripts/sharc_cycles_recorder.py, dnfw.sharccycles). It prints, per case,
instructions and estimated cycles over the run, and each case's difference from
the control per block; and writes out/sharc_cycles/<build>.json with the event
counts, so `fit` can use them without running again.

`compare` reads those files back and prints, per case, each build's instructions
and estimated cycles per block over the AGAINST case (default silent), then the
events behind the difference between the first build and each other one.

`fit` reads data/sharc_cycles/measurements.json (the instrument's readings, each
pair naming the two estimate cases it compares), fits the FREE keys
(dnfw.sharccycles.fit) and prints old and new costs and each pair's residual;
--write saves the result to data/sharc_cycles/costs.json, which `estimate` reads.

The run covers sw 0x1c2712 (frame unpack and machine dispatch) only, not the whole
frame: compare differences between cases, never one case's total with the
instrument's frame.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.sharccycles import costs as C              # noqa: E402
from dnfw.sharccycles import fit as F                # noqa: E402
from dnfw import sharcemu  # noqa: E402

OUT = ROOT / "out" / "sharc_cycles"
DATA = ROOT / "data" / "sharc_cycles"
COSTS = DATA / "costs.json"


def _cases(live):
    sub, _oct, _wave, _src = live.SUB_SLOTS
    nois, typ, colr, dec = live.NOISE_SLOTS
    on2 = {"LEV2": 0x6400}
    # (name, track 0's overrides, a note at block 1); "silent" is the instrument's
    # nothing-playing state, the rest one voice
    return [
        ("silent", {"LEV2": 0}, False),
        ("control", {"LEV2": 0}, True),
        ("osc2", on2, True),
        ("osc2+sub", {**on2, sub: 0x6400}, True),
        ("osc2+noise", {**on2, nois: 0x6400, typ: 0x0100, colr: 0x4000, dec: 0x2800}, True),
        ("osc2+sub+noise", {**on2, sub: 0x6400, nois: 0x6400, typ: 0x0100, colr: 0x4000, dec: 0x2800},
         True),
    ]


def section7_of(syx: pathlib.Path) -> bytes:
    from dnfw.cli.files import read_image             # noqa: PLC0415
    from dnfw.firmware.load import load               # noqa: PLC0415
    section = load(read_image(syx)).container.find(7)
    if section is None:
        raise SystemExit(f"{syx} has no section 7")
    return section.unpack() or section.raw_payload


def estimate(a) -> int:
    import sharc_waverider_m5 as g                    # noqa: PLC0415
    from dnfw.waverider import live                   # noqa: PLC0415
    from sharc_cycles_recorder import Recorder        # noqa: PLC0415
    dk = g.m1.Digikit(a.digikit)
    g.fx.bind(str(a.digikit / "tools"))
    g.m4.IMAGE = a.image
    stock = g.m1.dn2_section7(a.image)
    sound, machines = g.m4.init_sound(a.image)
    table = C.load(COSTS)
    OUT.mkdir(parents=True, exist_ok=True)
    cases = _cases(live)
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        for syx in a.builds:
            label = syx.name.split("_DN2_")[0]
            img = g.Image(dk, section7_of(syx))
            init = g.init_on(snap, m2mach, img)
            report = {"build": syx.name, "section7_sha256": img.sha, "blocks": a.blocks, "cases": {}}
            for name, words, note in cases:
                over = {g.WAV1: 0x4000, **{(g.LEV2 if k == "LEV2" else k): v for k, v in words.items()}}

                def fb(b, over=over, note=note):
                    return g.base_frame(sound, machines, trigger=(note and b == 1),
                                        overrides=over).to_bytes()

                with Recorder(g.fx) as rec:
                    run = g.run_blocks(init, fb, a.blocks)
                counts = dict(rec.model.counts)
                cycles, parts, unpriced = C.estimate(counts, table)
                report["cases"][name] = {"ok": run["ok"], "runner_instructions": run["instructions"],
                                         "skipped": rec.skips, "counts": counts, "cycles": cycles,
                                         "parts": parts, "unpriced": unpriced}
                print(f"{label:28s} {name:16s} instr {counts.get('instructions', 0):>9,}  "
                      f"est {cycles:>12,.0f}  ({cycles / max(1, counts.get('instructions', 1)):.2f}/instr)"
                      + ("" if run["ok"] else "  RUN FAILED"), flush=True)
            base = report["cases"]["control"]
            for name, case in report["cases"].items():
                case["delta_per_block"] = {
                    "instructions": (case["counts"].get("instructions", 0)
                                     - base["counts"].get("instructions", 0)) / a.blocks,
                    "cycles": (case["cycles"] - base["cycles"]) / a.blocks}
            (OUT / f"{label}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
            print(f"  -> {OUT / (label + '.json')}")
    return 0


def _counts(ref: str) -> dict[str, float]:
    """'LABEL:CASE' -> that case's counts per block, from out/sharc_cycles/LABEL.json."""
    label, case = ref.split(":")
    rep = json.loads((OUT / f"{label}.json").read_text(encoding="utf-8"))
    return {k: v / rep["blocks"] for k, v in rep["cases"][case]["counts"].items()}


def compare(a) -> int:
    reps = {lab: json.loads((OUT / f"{lab}.json").read_text(encoding="utf-8")) for lab in a.labels}
    table = C.load(COSTS)
    first = a.labels[0]
    cases = list(reps[first]["cases"])
    print(f"per block, over '{a.against}':  instructions / estimated cycles")
    print(f"{'case':16s}" + "".join(f"{lab[:24]:>28s}" for lab in a.labels))
    for case in cases:
        row = f"{case:16s}"
        for lab in a.labels:
            r = reps[lab]
            c, b = r["cases"][case], r["cases"][a.against]
            di = (c["counts"].get("instructions", 0) - b["counts"].get("instructions", 0)) / r["blocks"]
            dc = (c["cycles"] - b["cycles"]) / r["blocks"]
            row += f"{di:>13,.0f} /{dc:>12,.0f}"
        print(row)
    for lab in a.labels[1:]:
        for case in cases:
            if case == a.against:
                continue
            x, y = reps[first], reps[lab]

            def per_block(rep, key, case=case):
                cs, bs = rep["cases"][case]["counts"], rep["cases"][a.against]["counts"]
                return (cs.get(key, 0) - bs.get(key, 0)) / rep["blocks"]
            keys = set(x["cases"][case]["counts"]) | set(y["cases"][case]["counts"])
            diffs = sorted(((per_block(y, k) - per_block(x, k)) * table[k].value, k)
                           for k in keys if k in table)
            moved = [(v, k) for v, k in diffs if abs(v) >= 1]
            print()
            print(f"{lab} - {first}, {case}: " + ", ".join(f"{k} {v:+,.0f}" for v, k in moved))
    return 0


def fit_cmd(a) -> int:
    m = json.loads(a.measurements.read_text(encoding="utf-8"))
    table = C.load(COSTS)
    pairs = []
    for p in m["pairs"]:
        ca, cb = _counts(p["a"]), _counts(p["b"])
        # a block is a frame (32 samples, 1,500 a second); SCALE stretches the runner's
        # one voice to the instrument's (a held chord of four: 4)
        scale = p.get("scale", 1)
        diff = {k: (ca.get(k, 0) - cb.get(k, 0)) * scale for k in set(ca) | set(cb)}
        pairs.append(F.Pair(p["name"], diff, p["cycles_a"] - p["cycles_b"], p.get("sigma", 1000.0)))
    free = a.free or m.get("free", [])
    new, before, after = F.fit(pairs, table, free, lam=a.lam)
    print(f"{'key':22s} {'was':>8s} {'now':>8s}  source")
    for k in free:
        print(f"{k:22s} {table[k].value:8.2f} {new[k]:8.2f}  {table[k].source}")
    for p, r0, r1 in zip(pairs, before, after):
        print(f"  {p.name:40s} measured {p.cycles:>10,.0f}  residual {r0:>10,.0f} -> {r1:>10,.0f}")
    if a.write:
        DATA.mkdir(parents=True, exist_ok=True)
        old = json.loads(COSTS.read_text(encoding="utf-8"))["costs"] if COSTS.exists() else {}
        for k in free:
            old[k] = {"value": round(float(new[k]), 3), "unit": table[k].unit, "source": "fit",
                      "note": f"fit {a.measurements.name}: " + ", ".join(p.name for p in pairs)}
        COSTS.write_bytes((json.dumps({"costs": old}, indent=1) + "\n").encode("utf-8"))
        print(f"  -> {COSTS}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    e.add_argument("builds", nargs="+", type=pathlib.Path)
    e.add_argument("--blocks", type=int, default=4)
    e.add_argument("--digikit", type=pathlib.Path,
                   default=sharcemu.path())
    e.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    c = sub.add_parser("compare")
    c.add_argument("labels", nargs="+")
    c.add_argument("--against", default="silent")
    f = sub.add_parser("fit")
    f.add_argument("measurements", type=pathlib.Path)
    f.add_argument("--free", nargs="*")
    f.add_argument("--lam", type=float, default=1.0)
    f.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    return {"estimate": estimate, "compare": compare, "fit": fit_cmd}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
