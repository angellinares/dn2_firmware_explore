"""Does the Waverider voice read sound parameters 48, 49 (WaveTone's MAST, FINE) or 58..64?
(The shape page, docs/waverider-shape.md, keeps its eight records there.)

Runs the shipped Waverider DSP (section 7) in digikit's runner for a few blocks with a
note on, with those parameters at their default and then at their extreme, and compares
every track buffer the loop produced. Control: TUN1 (param 25), which the voice does read,
must change the render.

    python scripts/sharc_waverider_inert.py
"""
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as g  # noqa: E402
from dnfw import sharcemu  # noqa: E402
from dnfw.waverider import dsp  # noqa: E402

BLOCKS = 6
CASES = {
    "base": {},
    "MAST+FINE 0x7f00": {48: 0x7F00, 49: 0x7F00},
    "MAST+FINE 0x0000": {48: 0x0000, 49: 0x0000},
    "slots 58..64 0x7f00": {s: 0x7F00 for s in range(58, 65)},
    "slots 58..64 0x4000": {s: 0x4000 for s in range(58, 65)},
    "control: TUN1 +12": {25: 0x4C00},
}

dk = g.m1.Digikit(sharcemu.path())
g.fx.bind(str(sharcemu.path() / "tools"))
image = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
g.m4.IMAGE = image
stock = g.m1.dn2_section7(image)
sound, machines = g.m4.init_sound(image)
wr = g.Image(dk, dsp.with_preinstalled(stock))

results = {}
with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
    snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
    for name, over in CASES.items():
        state = g.init_on(snap, m2mach, wr)
        run = g.run_blocks(
            state,
            lambda b, over=over: g.base_frame(sound, machines, trigger=(b == 1), overrides=over).to_bytes(),
            BLOCKS)
        bits = run["buffer_bits"]
        results[name] = repr(bits)
        print(f"{name:24s} blocks {run['blocks']} ok {run['ok']} loop entries {run['loop_entries']}", flush=True)

base = results["base"]
print("render compared with base (every track buffer, every block):")
for name, r in results.items():
    if name != "base":
        print(f"  {name:24s} {'IDENTICAL' if r == base else 'DIFFERENT'}")
print("done", flush=True)
