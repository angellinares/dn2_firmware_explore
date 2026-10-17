"""formant.asm's wr_fm_coef in digikit's SHARC engine (Rust), bit for bit against dnfw.waverider.formant.

    python scripts/sharc_formant_check.py [--calls 400] [--python]

Builds stock + the idle stub plus formant.asm at sw 0x173800 and its DDR tables (the vowel
pairs, SHIFTS, the level table), then calls wr_fm_coef as one voice would block after
block: AMT moving (a sweep, jumps, an LFO's fractions and words past the top), P1 stepping,
now and then a note. After each call it compares, bit for bit, the glided position and the
25 coefficient words with `formant.Voice`'s and `formant.leveled`'s, and checks that the
states (words 5 and 6 of each biquad) and the loop's registers I3, I4 and I5 are untouched.
Prints the instructions a call takes. Exit 0 when every call matches.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import struct
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as m5                                 # noqa: E402
from dnfw import sharcemu                                       # noqa: E402
from dnfw.image import bootstream, sharc_object                 # noqa: E402
from dnfw.waverider import dsp, formant as F                    # noqa: E402

RETURN = dsp.IDLE_RETURN_SW
STATE_AT = 0x8070AC00          # the test's voice state (2 words) and coefficients (35 words), DDR
COEF_AT = 0x8070AD00
SENTINEL = 0x5A5A0000          # the states' words, which the routine must not touch


def bits(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]


def tables() -> list[tuple[int, bytes]]:
    """The DDR tables formant.asm reads: (address, bytes)."""
    pairs = []
    for i in range(len(F.VOWELS) - 1):
        (_, fa, ba), (_, fb, bb) = F.VOWELS[i], F.VOWELS[i + 1]
        pairs += list(fa) + [y - x for x, y in zip(fa, fb)] + list(ba) + [y - x for x, y in zip(ba, bb)]
    levels = [v for row in F.levels() for v in row]
    return [(dsp.FORMANT_VOWELS_AT, struct.pack(f"<{len(pairs)}f", *pairs)),
            (dsp.FORMANT_SHIFTS_AT, struct.pack("<128f", *F.SHIFTS)),
            (dsp.FORMANT_LEVELS_AT, struct.pack(f"<{len(levels)}f", *levels))]


def stream(stock: bytes) -> bytes:
    spec = json.loads(dsp.CODE.read_text(encoding="utf-8"))["formant"]
    code = sharc_object.load_bytes(bytes.fromhex(spec["object_parcels_be"]))
    out = dsp.section7_idle_only(stock)
    out = bootstream.insert_before_final(out, bootstream.block(dsp.dm_to_load(dsp.FORMANT_DM), code))
    for at, payload in tables():
        out = bootstream.insert_before_final(out, bootstream.block(at, payload))
    return out


def inputs(n: int, seed: int = 11) -> list[tuple[int, int, bool]]:
    """(AMT word, P1 word, note) per call: a sweep, jumps, LFO fractions, words past the top."""
    rnd = random.Random(seed)
    out = []
    for b in range(n):
        part = b * 5 // n
        if part == 0:
            amt = round(0x7F00 * b / (n // 5))                     # a sweep: the glide follows
        elif part == 1:
            amt = rnd.choice((0, 0x7F00, 0x2000, 0x6A00))          # jumps: the glide steps
        elif part == 2:
            amt = rnd.randrange(0, 0x10000)                        # LFO words, past the top too
        else:
            amt = rnd.randrange(0, 0x7F01)
        p1 = (rnd.randrange(128) << 8) if b % 7 == 0 or part > 2 else ((b // 7) % 128) << 8
        out.append((amt, p1 | (rnd.randrange(256) if part == 4 else 0), rnd.random() < 0.08))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path, default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    p.add_argument("--calls", type=int, default=400)
    p.add_argument("--python", action="store_true", help="the Python runner, a second opinion (default: Rust)")
    a = p.parse_args(argv)
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    image = m5.Image(dk, stream(stock))
    voice = F.Voice()
    bad, steps = 0, []
    with tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = m5.init_on(snap, m2mach, image)
        if a.python:
            raise SystemExit("--python: not wired yet; the Rust engine is the check")
        import sharc_native  # noqa: PLC0415
        eng = sharc_native.Engine(sharcemu.native_library(), image.memory, init)
        U = m5.fx.UREG_CODES
        for at in range(STATE_AT, STATE_AT + 8, 4):
            eng.poke(at, 0)
        for k in range(35):
            eng.poke(COEF_AT + 4 * k, SENTINEL + k if k % 7 >= 5 else 0)
        for n, (amt, p1, note) in enumerate(inputs(a.calls)):
            eng.core.fresh_call(dsp.FORMANT_SW, RETURN)
            for name, v in (("R4", amt), ("R5", p1), ("R6", int(note)), ("I1", STATE_AT), ("I2", COEF_AT),
                            ("I3", 0x1111), ("I4", 0x2222), ("I5", 0x3333)):
                eng.set_reg(U[name], v)
            kind, info, count = eng.run(100_000, {}, RETURN)
            steps.append(count)
            voice.position = F.glide(voice.position, F.position_of(amt), note)
            want = [w for bq in F.leveled(voice.position, F.p1_of(p1)) for w in bq]
            got = [eng.native_word(COEF_AT + 4 * (7 * (k // 5) + k % 5)) for k in range(25)]
            states = [eng.native_word(COEF_AT + 4 * k) for k in range(35) if k % 7 >= 5]
            regs = [eng.native_reg(U[r]) for r in ("I3", "I4", "I5")]
            ok = (info.reason == "reached the stop address"
                  and eng.native_word(STATE_AT) == bits(voice.position) and eng.native_word(STATE_AT + 4) == 1
                  and got == [bits(w) for w in want]
                  and states == [SENTINEL + k for k in range(35) if k % 7 >= 5]
                  and regs == [0x1111, 0x2222, 0x3333])
            if not ok:
                bad += 1
                if bad <= 5:
                    print(f"  call {n}: AMT {amt:#06x} P1 {p1:#06x} note {note}: {info.reason}")
                    print(f"    position {eng.native_word(STATE_AT):#010x} want {bits(voice.position):#010x}")
                    for k, (g, w) in enumerate(zip(got, want)):
                        if g != bits(w):
                            print(f"    word {k}: {g:#010x} want {bits(w):#010x} ({w})")
                    if regs != [0x1111, 0x2222, 0x3333]:
                        print(f"    I3, I4, I5 = {regs}")
    print(f"{a.calls} calls, {bad} differ; instructions a call: {min(steps)} to {max(steps)}")
    print("PASS" if bad == 0 else "FAIL")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
