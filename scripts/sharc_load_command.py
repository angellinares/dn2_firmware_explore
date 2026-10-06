"""Command 4 (load.asm) in digikit's SHARC runner: a load frame reaches the loader,
writes its chunk to DDR, acknowledges it, and renders as a repeat of the frame before it.

    python scripts/sharc_load_command.py [--digikit DIR] [--frame-be FRAME]

From the Milestone 2 post-init snapshot on Waverider's section 7, in two parts:

1. **The handler, to the render call.** The firmware's per-frame handler sw 0x1c9d6b
   runs on a frame placed where it reads it (the receive page `0x2c29d0 +
   (DM(0x2c0450) << 12)`) and stops at case 3's `cjump 0x1c2712` (sw 0x1c9fbc), or at
   case 0's code:

   | frame | must hold there |
   |---|---|
   | a load frame, a good chunk | load.asm ran; the chunk is in DDR; reply word 6 = the sequence (halves swapped); R12 = 0x25c48c, the frame copy |
   | the same, one checksum bit off | the chunk written; word 6 = the sequence with the ColdFire's bit 31 flipped (refused); R12 = 0x25c48c |
   | a destination past the area | nothing in DDR; word 6 = the refused sequence; R12 = 0x25c48c |
   | a render frame (command 3) | load.asm did not run; R12 = the receive page, as stock |
   | command 5 | case 0's code (sw 0x1c9dc2), as stock does for any command of 4 or more |

   It stops there because the runner cannot take the render further on this path:
   entered through case 3, sw 0x1c2712 ends with I6 = 0 and halts at its return
   ("return target 0x1"), the stock image included (2026-10-04). Every other gate
   calls sw 0x1c2712 directly, as part 2 does.
2. **The render from the frame copy.** Two calls of sw 0x1c2712 the way case 3 makes
   them: the second either on the same frame again (the control) or with R12 =
   0x25c48c, the copy the first call left. Every byte the second call writes must be
   the control's. The frame is one from the instrument (`--frame-be`) with track 0's
   four trigger bits set, so the second call renders a sounding voice. The control
   repeats it whole, triggers included, because that is what a load frame replays;
   which frames the ColdFire may replace is the ColdFire's rule, not this gate's.

The bytes of the patches and of the moved table are `test/test_waverider_dsp.py`'s;
selmap's reading of both is recorded in `docs/drive-load-command.md`.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as g                 # noqa: E402
from dnfw.waverider import dsp                 # noqa: E402
from dnfw.waverider import frame as FR         # noqa: E402

HANDLER = 0x1C9D6B
HANDLER_CALLER = 0x1C9FF9                       # past the engine task's cjump and its delay slots
RENDER_CALL = 0x1C9FBC                          # case 3's `cjump 0x1c2712 (db)`
CASE0 = 0x1C9DC2                                # case 0's code: silence
RX_PAGE_WORD = 0x2C0450
RX_BASE = 0x2C29D0
REPLY_BASE = 0x2C49D0
FRAME_COPY = 0x25C48C
SEQ = 0x12345678


def load_frame(dest: int, payload: list[int], seq: int = SEQ, sum_delta: int = 0, cmd: int = 4) -> bytes:
    """A load frame as the DSP sees it (little-endian words)."""
    words = [cmd | len(payload) << 16, dest, seq, (sum(payload) + sum_delta) & 0xFFFFFFFF, *payload]
    out = struct.pack(f"<{len(words)}I", *words)
    return out + bytes(FR.FRAME_BYTES - len(out))


def handler_call(runner, frame: bytes):
    page = g.m2.word(runner.state, RX_PAGE_WORD) or 0
    i7 = g.m2.word_reg(runner, "I7")
    r = runner.fresh_call(HANDLER, regs={"I6": i7, "I7": i7 - 16}, return_address=HANDLER_CALLER)
    rx = RX_BASE + (page << 12)
    for k in range(0, len(frame), 4):
        g.m2.poke(r.state, rx + k, struct.unpack_from("<I", frame, k)[0])
    return r, rx


def to_render_call(init, frame: bytes):
    """Part 1: the handler from INIT on FRAME, to case 3's render call or case 0."""
    seen = {}

    def at_load(runner):
        seen["load"] = True

    f = g.fixups({dsp.LOAD_SW: at_load})
    r, rx = handler_call(init, frame)
    before = dict(r.state.overlay)
    res = g.fx.run(r, 20_000_000, f, stop_at=(RENDER_CALL, CASE0))
    if res[0] != "stop":
        halt = f"{res[1].reason} at {res[1].pc_sw:#x}" if res[0] == "halt" else f"{res[0]} at {res[1]:#x}"
        return False, {"halt": halt}
    return True, {"at": res[1], "rx": rx, "R12": g.m2.word_reg(r, "R12"), "load": seen.get("load", False),
                  "written": {a: v for a, v in r.state.overlay.items() if before.get(a) != v}, "runner": r}


def render_call(state_runner, frame: bytes | None):
    """Part 2: sw 0x1c2712 as case 3 calls it (m4.unpack_call), on FRAME in the receive
    bank, or, with FRAME None, on the frame copy 0x25c48c."""
    m2, m4 = g.m2, g.m4
    s = state_runner.state
    idx = m2.word(s, m4.RX_INDEX) or 0
    i7 = m2.word_reg(state_runner, "I7")
    rx = m4.RX_BASE + (idx << 8)
    r = state_runner.fresh_call(m4.UNPACK, regs={"R4": 0x268438, "R8": m4.UNPACK_LOCAL,
                                                 "R12": rx if frame is not None else FRAME_COPY,
                                                 "I6": i7, "I7": i7 - 16},
                                return_address=m4.UNPACK_CALLER)
    for k in range(10):
        m2.poke(r.state, m4.UNPACK_LOCAL + 4 * k, 0)
    m2.poke(r.state, i7 + 4, 0)
    m2.poke(r.state, i7 + 8, m4.RX_PAGE + (idx << 11))
    if frame is not None:
        for k in range(0, len(frame), 4):
            m2.poke(r.state, rx + k, struct.unpack_from("<I", frame, k)[0])
    return r


def two_renders(init, first: bytes, second: bytes | None):
    """-> (bytes the second call wrote, None) or (None, why it stopped)."""
    state, written = init, None
    for frame in (first, second):
        r = render_call(state, frame)
        before = dict(r.state.overlay)
        res = g.fx.run(r, 20_000_000, g.fixups())
        if not (res[0] == "halt" and res[1].pc_sw == g.m4.UNPACK_RETURN):
            halt = f"{res[1].reason} at {res[1].pc_sw:#x}" if res[0] == "halt" else f"{res[0]} at {res[1]:#x}"
            return None, halt
        written = {a: v for a, v in r.state.overlay.items() if before.get(a) != v}
        state = r
    return written, None


def word_at(runner, dm: int) -> int:
    return g.m2.word(runner.state, dm) or 0


def swapped(v: int) -> int:
    return ((v << 16) | (v >> 16)) & 0xFFFFFFFF


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--digikit", default=str(ROOT.parent / "digikit-wt-sharcemu"))
    ap.add_argument("--frame-be", default=str(ROOT / "out/probe-frames/tail_idle.frame_be.0.bin"))
    a = ap.parse_args(argv)

    digikit = pathlib.Path(a.digikit)
    dk = g.m1.Digikit(digikit)
    g.fx.bind(str(digikit / "tools"))
    image_zip = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
    g.m4.IMAGE = image_zip
    stock = g.m1.dn2_section7(image_zip)
    wr = g.Image(dk, dsp.section7(stock))

    f = bytearray(g.swap16(pathlib.Path(a.frame_be).read_bytes()))
    for at in FR.TRIG_MASKS:                    # track 0 triggered: the render sounds a voice
        struct.pack_into("<H", f, at, struct.unpack_from("<H", f, at)[0] | 1)
    live = bytes(f)
    payload = [(0x01000100 * (i + 1)) & 0xFFFFFFFF for i in range(dsp.LOAD_MAX_WORDS)]
    dest = 0x1230
    area = dsp.LOAD_AREA[0]
    answer = REPLY_BASE + 0x18                  # reply word 6 (load.asm)
    REFUSED = 0x8000                            # the ColdFire's bit 31 in the swapped halves

    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)
        results = {}

        cases = {
            "load": load_frame(dest, payload),
            "bad sum": load_frame(dest, payload, sum_delta=1),
            "out of range": load_frame(dsp.LOAD_AREA[1] - dsp.LOAD_AREA[0] - 8, payload),
            "wraps": load_frame(0xFFFFFFF0, payload),
            "render frame": live,
            "command 5": load_frame(dest, payload, cmd=5),
        }
        for name, frame in cases.items():
            ok, got = to_render_call(init, frame)
            if not ok:
                print(f"1 {name}: {got}")
                results[name] = False
                continue
            r = got["runner"]
            in_ddr = [word_at(r, area + dest + 4 * i) for i in range(len(payload))] == payload
            nothing_in_ddr = not any(area <= x < dsp.LOAD_AREA[1] for x in got["written"])
            w6 = word_at(r, answer)
            to_copy = got["at"] == RENDER_CALL and got["R12"] == FRAME_COPY
            if name == "load":
                checks = {"load.asm ran": got["load"], "chunk in DDR": in_ddr,
                          "word 6 = the sequence": w6 == swapped(SEQ),
                          "R12 = the frame copy": to_copy}
            elif name == "bad sum":
                checks = {"chunk written": in_ddr, "word 6 = the refused sequence": w6 == swapped(SEQ) ^ REFUSED,
                          "R12 = the frame copy": to_copy}
            elif name in ("out of range", "wraps"):
                checks = {"nothing in DDR": nothing_in_ddr, "word 6 = the refused sequence": w6 == swapped(SEQ) ^ REFUSED,
                          "R12 = the frame copy": to_copy}
            elif name == "render frame":
                checks = {"load.asm did not run": not got["load"], "nothing in DDR": nothing_in_ddr,
                          "R12 = the receive page": got["at"] == RENDER_CALL and got["R12"] == got["rx"]}
            else:
                checks = {"case 0's code": got["at"] == CASE0, "load.asm did not run": not got["load"],
                          "nothing in DDR": nothing_in_ddr}
            print(f"1 {name}: " + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in checks.items()))
            results[name] = all(checks.values())

        ref, err = two_renders(init, live, live)
        got, err2 = two_renders(init, live, None)
        if err or err2:
            print("2 render from the copy:", err or err2)
            results["render from the copy"] = False
        else:
            diff = sorted({x & ~3 for x in set(ref) | set(got) if ref.get(x) != got.get(x)})
            # Allowed: a pointer into the frame, kept on the stack (below the call's I7),
            # at the same offset from each call's own frame (the receive bank, or the copy).
            rx = g.m4.RX_BASE + ((g.m2.word(init.state, g.m4.RX_INDEX) or 0) << 8)
            top = dsp.LOAD_ALIAS + g.m2.word_reg(init, "I7")

            def value(w, x):
                return int.from_bytes(bytes(int(w.get(x + i, 0)) for i in range(4)), "little")

            pointers = [x for x in diff if dsp.LOAD_ALIAS + 0x2F0000 <= x < top
                        and value(ref, x) - rx == value(got, x) - FRAME_COPY]
            rest = [x for x in diff if x not in pointers]
            print(f"2 render from the copy: the control's second call wrote {len(ref):,} bytes; "
                  f"{len(pointers)} stack words differ only as pointers into the frame; "
                  f"{len(rest)} other words differ" + (f", first {[hex(x) for x in rest[:6]]}" if rest else ""))
            results["render from the copy"] = not rest and len(ref) > 0
    passed = all(results.values())
    print("PASS" if passed else "FAIL", f"{sum(results.values())}/{len(results)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
