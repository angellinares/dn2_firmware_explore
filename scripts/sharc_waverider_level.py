"""How loud is Waverider next to WaveTone, patch for patch? Peak and RMS of a held C5 in
digikit's SHARC runner, the shipped DSP (section 7), track 0, after the voice and after the amp.

    python scripts/sharc_waverider_level.py [--blocks 14]

Cases: WaveTone as the machine's defaults leave it (control); Waverider osc 1 alone, osc 1 + 2,
and the owner's patch (osc 1 + 2 at 100, sub 100, noise PNK 100, DEC 40); each Waverider case on
Prim. (a pool table is normalised by the reduce step, not measured here). Levels are the
runner's float samples (1.0 = full scale), printed in dBFS.
"""
import argparse
import math
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as g  # noqa: E402
from dnfw import sharcemu  # noqa: E402
from dnfw.waverider import dsp  # noqa: E402

LEV1, LEV2 = 30, 36
SUB, NOIS, NOIS_TYPE, COLR, DEC = 50, 54, 55, 56, 57
OWNER = {LEV1: 0x6400, LEV2: 0x6400, SUB: 0x6400, NOIS: 0x6400, NOIS_TYPE: 0x0100, COLR: 0x4000, DEC: 0x2800}
CASES = [
    ("WaveTone, machine defaults", 1, {}),
    ("Waverider osc 1 at 100", 5, {LEV1: 0x6400, LEV2: 0, SUB: 0, NOIS: 0}),
    ("Waverider osc 1 + osc 2 at 100", 5, {LEV1: 0x6400, LEV2: 0x6400, SUB: 0, NOIS: 0}),
    ("Waverider sub 100 alone", 5, {LEV1: 0, LEV2: 0, SUB: 0x6400, NOIS: 0}),
    ("Waverider noise PNK 100 alone", 5, {LEV1: 0, LEV2: 0, SUB: 0, NOIS: 0x6400, NOIS_TYPE: 0x0100,
                                          COLR: 0x4000, DEC: 0x7F00}),
    ("Waverider owner's patch", 5, OWNER),
]


def db(x):
    return 20 * math.log10(x) if x > 0 else float("-inf")


def stats(xs):
    peak = max(abs(v) for v in xs)
    rms = math.sqrt(sum(v * v for v in xs) / len(xs))
    return peak, rms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=14)
    ap.add_argument("--settle", type=int, default=5, help="blocks to skip before measuring")
    ap.add_argument("--note", type=lambda s: int(s, 0), default=0x4800, help="the trig note word (C5)")
    a = ap.parse_args()
    dk = g.m1.Digikit(sharcemu.path())
    g.fx.bind(str(sharcemu.path() / "tools"))
    image = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
    g.m4.IMAGE = image
    stock = g.m1.dn2_section7(image)
    sound, machines = g.m4.init_sound(image)
    wr = g.Image(dk, dsp.with_preinstalled(stock))
    rows = []
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        for name, machine, over in CASES:
            state = g.init_on(snap, m2mach, wr)
            run = g.run_blocks(
                state,
                lambda b, machine=machine, over=over: g.base_frame(
                    sound, machines, t0=machine, trigger=(b == 1), overrides=over, note=a.note).to_bytes(),
                a.blocks)
            if not run["ok"]:
                print(f"{name}: run stopped: {run.get('halt')}", flush=True)
                continue
            settle = a.settle * g.BLOCK
            voice = g.track_series(run, 0)[settle:]
            amp = run["amp_out"][settle:]
            vp, vr = stats(voice)
            ap_, ar = stats(amp)
            rows.append((name, vp, vr, ap_, ar))
            print(f"{name:34s} voice peak {db(vp):7.1f} dBFS rms {db(vr):7.1f} | after amp peak "
                  f"{db(ap_):7.1f} rms {db(ar):7.1f}", flush=True)
    if rows:
        base = rows[0]
        print("\nrelative to WaveTone's defaults (voice RMS, dB):")
        for name, vp, vr, ap_, ar in rows[1:]:
            print(f"  {name:34s} {db(vr) - db(base[2]):+6.1f} dB   (after amp {db(ar) - db(base[4]):+6.1f} dB)")


if __name__ == "__main__":
    main()
