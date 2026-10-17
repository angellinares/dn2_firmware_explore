"""The Formant type in the whole Waverider voice, in digikit's SHARC engine, against live.render_two.

    python scripts/sharc_formant_voice.py [CASE ...] [--blocks 48] [--no-iir]

Tracks 0 and 1 play Waverider with page 5's TYPE at Formant (3), so formant.asm starts IIR0
on track 0's voice and collects it at track 1's FOLD, and collects track 1's at the loop's
end. The core runs in digikit's Rust engine. digikit's engine has no IIR0, so this script
runs digikit's IIR0 model (tools/sharc_dev/sharc_core/iir.py on a checkout with ElekLabs/
digikit#122, the order read on silicon; --iir-digikit) on the engine's memory when
formant.asm polls IIR0's DMASTAT, and hands the poll ACDONE. That is the same as IIR0
finishing at any time before the poll: between the start and the poll nothing else touches
IO or the voice's coefficients. Each track's output is compared bit for bit with
live.render_two fed the DSP's unpacked inputs, page 3's and page 5's words and TRIM.

| case | what moves |
|---|---|
| sweep | AMT (the vowel) from 0 to 127, a note at the start |
| shift | P1 stepping, AMT held, P2 64, osc 2 on |
| dry | P2 127: each track must equal the plain sound, bit for bit |
| sub | the sub on, P2 32, notes every 12 blocks (the glide jumps) |
| switch | TYPE Formant and Off in turn every 10 blocks |

`--no-iir` is the control: the IIR0 model does not run, so IO keeps the input and the
check must fail wherever the voice is wet. Exit 0 when every case matches.
"""

from __future__ import annotations

import argparse
import importlib
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as g                 # noqa: E402
from dnfw import sharcemu                      # noqa: E402
from dnfw.waverider import dsp, live           # noqa: E402
from dnfw.waverider import frame as FR         # noqa: E402

FOLD, NPOS, TYPE, AMT, WARP, FM, P1, P2 = live.SHAPE_SLOTS
SUB = live.SUB_SLOTS[0]
FORMANT = live.TYPE_FORMANT << 8
TRACKS = (0, 1)
IIR_DIGIKIT = pathlib.Path("D:/01_Code/Z_Personal/digikit-wt-accelsi")


def case_words(name: str, b: int, n: int) -> tuple[dict, bool]:
    """(page 5's and page 3's words for both tracks, a note on block b)."""
    if name == "sweep":
        return {TYPE: FORMANT, AMT: round(0x7F00 * b / max(n - 1, 1)), g.LEV2: 0}, b == 0
    if name == "shift":
        return {TYPE: FORMANT, AMT: 0x3000, P1: (b * 9 % 128) << 8, P2: 0x4000, g.LEV2: 0x6400}, b == 0
    if name == "dry":
        return {TYPE: FORMANT, AMT: 0x5000, P1: 0x2000, P2: 0x7F00, g.LEV2: 0x6400}, b == 0
    if name == "sub":
        return {TYPE: FORMANT, AMT: 0x6800 if b // 12 % 2 else 0x0800, P2: 0x2000, SUB: 0x6400, g.LEV2: 0}, b % 12 == 0
    if name == "switch":
        return {TYPE: FORMANT if b // 10 % 2 == 0 else 0, AMT: 0x2000 + 64 * b, g.LEV2: 0x6400}, b == 0
    raise SystemExit(f"no case {name}")


CASES = ("sweep", "shift", "dry", "sub", "switch")


class Bus:
    """digikit's IIR0 model's view of the engine: its registers here, memory in the engine
    (word addresses 0x28000000 + DM >> 2 for L1)."""

    def __init__(self, engine, const):
        self.engine, self.mmrs, self.concrete, self.Const = engine, {}, None, const
        self.overlay = self

    @staticmethod
    def _dm(byte: int) -> int:
        return byte - dsp.LOAD_ALIAS if dsp.LOAD_ALIAS <= byte < dsp.LOAD_ALIAS + 0x400000 else byte

    def __contains__(self, byte: int) -> bool:
        return True

    def __getitem__(self, byte: int) -> int:
        a = self._dm(byte)
        return ((self.engine.native_word(a & ~3) or 0) >> (8 * (a & 3))) & 0xFF

    def __setitem__(self, byte: int, value: int) -> None:
        a = self._dm(byte)
        w = self.engine.native_word(a & ~3) or 0
        sh = 8 * (a & 3)
        self.engine.poke(a & ~3, (w & ~(0xFF << sh)) | (value & 0xFF) << sh)


def iir_model(path: pathlib.Path):
    sys.path.insert(0, str(path))
    return (importlib.import_module("tools.sharc_dev.sharc_core.iir"),
            importlib.import_module("tools.sharc_dev.sharc_core.values").Const)


def run_case(name, a, dk, stock, sound, machines, wr, tables, iir, const) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)
        init.state.mmrs[iir.IIR_DMASTAT] = g.fx.Const(0)      # the engine refuses an MMR it has no value for
        state = g.native_on(init, wr)
        runs = []

        def fb(b):
            words, note = case_words(name, b, a.blocks)
            over = {**words}
            f = g.base_frame(sound, machines, trigger=note, overrides=over, others={1: 5},
                             trigger_others=note)
            for s, v in words.items():
                f.param(1, s, v)
            return f.to_bytes()

        shapes = {t: [] for t in TRACKS}
        subs = {t: [] for t in TRACKS}

        def at_loop(r):
            for t in TRACKS:
                shapes[t].append(tuple(g.frame_word(r.state, FR.slot_offset(t, s)) for s in live.SHAPE_SLOTS))
                subs[t].append(tuple(g.frame_word(r.state, FR.slot_offset(t, s)) for s in live.SUB_SLOTS))

        def at_poll(r):                                       # after R2 = DMASTAT: IIR0 ran, ACDONE
            if not a.no_iir:
                bus = Bus(r, const)
                bus.mmrs[iir.IIR_CHNPTR] = const(dsp.iir_word(dsp.FORMANT_TCB_DM) + 12)
                iir._iir_write(bus, iir.IIR_CTL1, 0x501)
                runs.append(1)
            r.set_reg(g.fx.UREG_CODES["R2"], 0x40)

        run = g.run_blocks(state, fb, a.blocks, extra_hooks={dsp.COUNT_SW: at_loop, POLL_AND: at_poll})
        if not run["ok"]:
            return False, f"halted: {run.get('halt')}"
        bad = {}
        for t in TRACKS:
            got = g.track_series(run, t)
            seq = [(i[t]["note"], (i[t]["wav1"], i[t]["tbl1"], i[t]["tun1"], i[t]["lev1"], *i[t]["move1"],
                                   i[t]["sync"][0], i[t]["smth"][0]),
                    (*i[t]["osc2"], *i[t]["move2"], i[t]["sync"][1], i[t]["smth"][1]),
                    (i[t]["trig"], i[t]["triggered"], i[t]["prst"], i[t]["song"], i[t]["tempo"], i[t]["dclk"]))
                   for i in run["t5_inputs"] if t in i]
            n = len(seq)
            trims = [i[t]["trim"] for i in run["t5_inputs"] if t in i]
            want = live.render_two(tables, seq, g.BLOCK, "float32", subs=subs[t][-n:], shapes=shapes[t][-n:],
                                   trims=trims)
            bad[t] = g.mismatches(got, want)
            if name == "dry":
                plain = live.render_two(tables, seq, g.BLOCK, "float32", subs=subs[t][-n:], trims=trims)
                bad[t] += g.mismatches(got, plain)
        ok = all(v == 0 for v in bad.values())
        return ok, f"{a.blocks} blocks, IIR0 ran {len(runs)} times, samples that differ: " + \
            ", ".join(f"track {t} {v}" for t, v in bad.items())


def layout() -> tuple[list[int], dict[str, int]]:
    """formant.asm's instruction offsets (bytes) and labels (instruction indexes), from selas."""
    import sharc_resolve_jumps as rj  # noqa: PLC0415
    import sharc_waverider_m3 as m3  # noqa: PLC0415
    src = ROOT / "csrc/waverider/sharc/formant.asm"
    text = src.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        (work / "x.asm").write_text(text, encoding="utf-8", newline="\n")
        _, offs = m3._selas(work / "x.asm", work)
    return offs, rj.labels(text)


POLL_AND = None


def main(argv=None) -> int:
    global POLL_AND
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="*", default=list(CASES))
    ap.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    ap.add_argument("--iir-digikit", type=pathlib.Path, default=IIR_DIGIKIT)
    ap.add_argument("--image", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--blocks", type=int, default=48)
    ap.add_argument("--no-iir", action="store_true", help="the control: IIR0's model does not run")
    a = ap.parse_args(argv)
    dk = g.m1.Digikit(a.digikit)
    g.fx.bind(str(a.digikit / "tools"))
    iir, const = iir_model(a.iir_digikit)
    g.m4.IMAGE = a.image
    stock = g.m1.dn2_section7(a.image)
    sound, machines = g.m4.init_sound(a.image)
    wr = g.Image(dk, dsp.section7(stock))
    tables = dsp.tables()
    offs, labels = layout()
    POLL_AND = dsp.FORMANT_SW + offs[labels["wr_fm_poll"] + 1] // 2    # the instruction after the DMASTAT read
    ok_all = True
    for name in a.cases:
        ok, what = run_case(name, a, dk, stock, sound, machines, wr, tables, iir, const)
        ok_all &= ok
        print(f"  {name}: {'PASS' if ok else 'FAIL'}  {what}", flush=True)
    print("PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
