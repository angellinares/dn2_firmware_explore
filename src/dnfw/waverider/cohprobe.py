"""A diagnostic DSP stream: do the DM and PM data caches agree on DDR, on the DSP itself?

    section7_cohprobe(stock) -> stock DN2 1.11's section 7, plus the idle-time stub
        (`dsp.section7_idle_only`), plus cohprobe.asm in the idle loop's back edge (as
        ddrscan.asm).

The SHARC+ Programming Reference (chapter 8, "Coherency Between DM and PM Caches") says a
hardware cross-check keeps the DM and PM data caches coherent. fftselftest3 (2026-10-09)
changed two things at once, so it did not show which one fixed fftselftest's zeros.
cohprobe.asm writes on one bus and reads on the other in the idle task, in five cases (A-E,
`CASES`), and publishes the bad reads per case through reply word 2
(`tools/dn2cohprobe.py`). Each DDR case has its own 16 KB of Waverider's DDR region, which
this build does not use. The emulator check is `scripts/sharc_cohprobe_check.py`.
"""

from __future__ import annotations

import json
import pathlib

from dnfw.image import bootstream, sharc_object
from dnfw.waverider import dsp

CODE_DM = 0x2DF000                     # cohprobe.asm, after idle_load.asm's padding (dsp.IDLE_PAD_END)
CODE_SW = CODE_DM // 2                 # 0x16f800, ddrscan.asm's: the same back-edge JUMP
STATE_DM = 0x2DF800                    # saves, CALLS, OFF, TICK, IDX, PUB, case E's words
STATE_BYTES = 0x140
CALLS_DM = STATE_DM + 0x30
PUB_DM = STATE_DM + 0x80
L1_WORDS_DM = STATE_DM + 0x100         # case E: 16 words in L1 block 1
REPLY_WORD2 = (0x2C49D8, 0x2C59D8)
PUB_ENTRIES = 20
LINES = 16                             # cache lines a case checks each call, 64 bytes apart
SPAN = 0x4000                          # each DDR case's bytes; OFF moves 1 KB a call

CASES = {
    "A": ("DM read, PM write, DM read", dsp.DDR_REGION[0]),
    "B": ("PM read, DM write, PM read", dsp.DDR_REGION[0] + SPAN),
    "C": ("PM write, DM read", dsp.DDR_REGION[0] + 2 * SPAN),
    "D": ("DM write, DM read (the same-bus control)", dsp.DDR_REGION[0] + 3 * SPAN),
    "E": ("PM write, DM read on L1 (the uncached control)", L1_WORDS_DM),
}
PUB_NAMES = ("calls",
             *(f"bad, case {c}" for c in CASES), *(f"stale, case {c}" for c in CASES),
             "first bad: 0x1000 | case << 8 | line", "its value low 27", "its value >> 27",
             "V low 27", "V >> 27",
             "SHL1C_CFG low 27", "SHL1C_CFG >> 27", "SHL1C_CFG2 low 27", "SHL1C_CFG2 >> 27")

CODE = pathlib.Path(__file__).with_name("cohprobe_code.json")


def objects() -> dict[str, bytes]:
    """The committed cohprobe.asm and the idle back edge's JUMP to it."""
    spec = json.loads(CODE.read_text(encoding="utf-8"))
    return {name: sharc_object.load_bytes(bytes.fromhex(spec[name]["object_parcels_be"]))
            for name in ("cohprobe", "probe_jump")}


def section7_cohprobe(stock: bytes) -> bytes:
    """Stock + the idle stub + cohprobe.asm. The idle loop's back edge goes to the probe,
    which goes on to the idle stub."""
    base = dsp.section7_idle_only(stock)
    obj = objects()
    code = obj["cohprobe"]
    if STATE_DM - CODE_DM - len(code) < 64:
        raise dsp.DspError("cohprobe.asm leaves fewer than 64 bytes of NOP padding")
    if len(obj["probe_jump"]) != len(dsp.IDLE_SITE_STOCK):
        raise dsp.DspError(f"the probe JUMP is {len(obj['probe_jump'])} bytes, not {len(dsp.IDLE_SITE_STOCK)}")
    if not (dsp.IDLE_PAD_END <= CODE_DM and STATE_DM + STATE_BYTES <= dsp.REGION[1]):
        raise dsp.DspError("cohprobe's spans leave the block-1 region")
    if CASES["D"][1] + SPAN > dsp.DDR_REGION[1]:
        raise dsp.DspError("cohprobe's DDR cases leave Waverider's DDR region")
    added = [("cohprobe.asm (wr_coh)", dsp.dm_to_load(CODE_DM), code + bytes(STATE_DM - CODE_DM - len(code))),
             ("cohprobe state", dsp.dm_to_load(STATE_DM), bytes(STATE_BYTES))]
    dsp._check_free(stock, added)
    extra = b"".join(bootstream.block(at, payload) for _, at, payload in added)
    out = bytearray(bootstream.insert_before_final(base, extra))
    bootstream.write_span(out, dsp.l2_sw_to_load(dsp.IDLE_SITE_SW), obj["probe_jump"])
    return dsp._finish(out)


def decode(word: int) -> tuple[int, int]:
    """A reply word 2 as the ColdFire reads it (big-endian u32) -> (PUB index, value)."""
    return word >> 27, word & 0x7FFFFFF


def first_bad(marker: int) -> tuple[str, int] | None:
    """PUB[11] -> (case letter, line), or None when no read was bad."""
    if not marker & 0x1000:
        return None
    return "ABCDE"[(marker >> 8 & 0xF) - 1], marker & 0xFF
