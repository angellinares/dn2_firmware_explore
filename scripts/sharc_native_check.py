"""digikit's native SHARC engine against its Python runner over the Waverider block call, bit for bit.

    python scripts/sharc_native_check.py [--blocks 12] [--digikit DIR] [--library DLL]

The Python runner with `sharc_dn2_fixups.py` is the reference the Waverider tests were
built on. The native engine (`scripts/sharc_native.py`) runs the same call about 20
times faster and carries the fix-ups it needs from the host. This runs both over the same
frames and compares everything `run_blocks` records: every track's buffer after the
machine loop and at the end of the call (as bits), the amp's input and output, each
voice's unpacked inputs, the reader blocks, the reply tail, the modulator's phases and
random state. The instruction counts are printed beside it.

| case | frames |
|---|---|
| one oscillator | osc 1 alone, POS mid-table |
| two oscillators moving | both oscillators, POS a step each block, TBL alternating between the two baked tables, DCLK at its default |
| control: no host fix-ups | the first case with the native engine's fix-ups off: it must differ, or the check cannot see them |

Writes out/waverider/native_check_report.json. Exit 0 when the two cases match and the control differs.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as g                 # noqa: E402
from dnfw import sharcemu                      # noqa: E402
from dnfw.waverider import dsp, live           # noqa: E402

# "instructions" is reported, not compared: in the block where the amp's JUMP (LA) first runs,
# the Python runner's SIMD two-pass counts one step more than the core does on its own. Stepped
# side by side with the two-pass off, the two engines have equal registers at every instruction.
SKIP = {"state", "wall_s", "instructions"}


def differences(a: dict, b: dict) -> dict[str, int]:
    """Per recorded field, how many of its blocks (or, for the two flat sample lists,
    samples) differ."""
    out = {}
    for key in sorted(set(a) | set(b)):
        if key in SKIP:
            continue
        x, y = a.get(key), b.get(key)
        if x == y:
            continue
        if isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            out[key] = sum(1 for p, q in zip(x, y) if p != q)
        else:
            out[key] = 1
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    ap.add_argument("--library", type=pathlib.Path, default=sharcemu.native_library())
    ap.add_argument("--image", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--blocks", type=int, default=12)
    a = ap.parse_args(argv)

    dk = g.m1.Digikit(a.digikit)
    g.fx.bind(str(a.digikit / "tools"))
    g.m4.IMAGE = a.image
    stock = g.m1.dn2_section7(a.image)
    sound, machines = g.m4.init_sound(a.image)
    wr = g.Image(dk, dsp.with_preinstalled(stock))

    def one(b):
        return {g.WAV1: 0x3000, g.TBL1: 0, g.LEV2: 0}

    def two(b):
        return {g.WAV1: 0x7800 * b // max(a.blocks - 1, 1), g.TBL1: 0x0100 if b % 2 else 0,
                g.WAV2: 0x7800 - 0x7800 * b // max(a.blocks - 1, 1), live.DCLK_SLOT: live.DCLK_DEFAULT}

    def frames(over):
        return lambda b: g.base_frame(sound, machines, trigger=(b == 0), overrides=over(b)).to_bytes()

    checks, report = {}, {"blocks": a.blocks, "cases": {}}
    g.OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)
        first = None
        for name, over in (("one oscillator", one), ("two oscillators moving", two)):
            t0 = time.perf_counter()
            py = g.run_blocks(init, frames(over), a.blocks)
            t1 = time.perf_counter()
            engine = g.native_on(init, wr, a.library)
            nat = g.run_blocks(engine, frames(over), a.blocks)
            t2 = time.perf_counter()
            diff = differences(py, nat)
            checks[name] = bool(py["ok"] and nat["ok"] and not diff)
            report["cases"][name] = {"python_ok": py["ok"], "native_ok": nat["ok"], "halt": nat.get("halt"),
                                     "differing": diff, "instructions": py.get("instructions"),
                                     "native_instructions": nat.get("instructions"),
                                     "python_s": round(t1 - t0, 1), "native_s": round(t2 - t1, 1),
                                     "host_fixups": dict(engine.counts)}
            report["library"] = engine.library
            first = first or py
        engine = g.native_on(init, wr, a.library, host_fixups=False)
        bare = g.run_blocks(engine, frames(one), a.blocks)
        diff = differences(first, bare)
        name = "control: no host fix-ups (must differ)"
        checks[name] = bool(diff) or not bare["ok"]
        report["cases"][name] = {"native_ok": bare["ok"], "halt": bare.get("halt"), "differing": diff}
    report["checks"] = checks
    (g.OUT / "native_check_report.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    for k, v in checks.items():
        print(f"  {'ok  ' if v else 'FAIL'} {k}  {report['cases'][k]}")
    passed = all(checks.values())
    print("PASS" if passed else "FAIL", f"{sum(checks.values())}/{len(checks)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
