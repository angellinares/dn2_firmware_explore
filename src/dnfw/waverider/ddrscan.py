"""A diagnostic DSP stream: does anything write the DSP's spare DDR while the instrument plays?

    section7_ddrscan(stock) -> stock DN2 1.11's section 7, plus the idle-time stub
        (`dsp.section7_idle_only`), plus ddrscan.asm, plus fill blocks that write PATTERN
        over the spare DDR before any stock code runs.

The chip is 512 MB (`0x80000000..0xa0000000`: the init program's DMC_CFG word is
`0x0622`, one 4 Gbit part 16 bits wide). The stock image ends at `0x8052fbe0` and its
init writes up to `0x80530be3` (the emulator's engine-init snapshot), so the span starts
at `0x80531000`. Waverider is absent from this build, so its 4 MB is scanned too.

The fill blocks' ARGUMENT is the fill value (ADSP-2156x HRM, "Fill Block"); stock's are all
0. ddrscan.asm reads the span back in the idle task and publishes what differs through
reply word 2 (`tools/dn2ddrscan.py`). Its state block carries START, END and PATTERN, so the
emulator check (`scripts/sharc_ddrscan_check.py`) runs the same code on a small span.
"""

from __future__ import annotations

import json
import pathlib
import struct

from dnfw.image import bootstream, sharc_object
from dnfw.waverider import dsp

SCAN_DM = 0x2DF000                     # ddrscan.asm, after idle_load.asm's padding (dsp.IDLE_PAD_END)
SCAN_SW = SCAN_DM // 2                 # 0x16f800
SCAN_STATE_DM = 0x2DF800               # its saves, pointers, counters and PUB[0..19]
SCAN_STATE_BYTES = 0x100
SCAN_END_DM = SCAN_STATE_DM + SCAN_STATE_BYTES
PUB_DM = SCAN_STATE_DM + 0x80
PUB_ENTRIES = 20
REPLY_WORD2 = (0x2C49D8, 0x2C59D8)

DDR = (0x80000000, 0xA0000000)         # the 512 MB part
SPAN = (0x80531000, 0xA0000000)        # past the stock image and what its init writes
PATTERN = 0xA5C35A3C
FILL_BLOCK = 64 << 20                  # each fill block at most 64 MB
GRANULE = 2 << 20                      # PUB[4..19]'s bitmap: 256 granules of 2 MB

CODE = pathlib.Path(__file__).with_name("ddrscan_code.json")


def objects() -> dict[str, bytes]:
    """The committed ddrscan.asm and the idle back edge's JUMP to it."""
    spec = json.loads(CODE.read_text(encoding="utf-8"))
    return {name: sharc_object.load_bytes(bytes.fromhex(spec[name]["object_parcels_be"]))
            for name in ("ddrscan", "scan_jump")}


def state(span: tuple[int, int] = SPAN, pattern: int = PATTERN) -> bytes:
    """The scanner's state block at boot: CUR = START, END, PATTERN; FIRST = LAST = DDR's
    base (offset 0); everything else 0."""
    out = bytearray(SCAN_STATE_BYTES)
    struct.pack_into("<IIII", out, 0x20, span[0], span[0], span[1], pattern)
    struct.pack_into("<II", out, 0x34, DDR[0], DDR[0])
    return bytes(out)


def fills(span: tuple[int, int] = SPAN, pattern: int = PATTERN) -> bytes:
    """Fill blocks writing PATTERN over SPAN, FILL_BLOCK bytes at most each."""
    if span[0] % 4 or span[1] % 4 or not (DDR[0] <= span[0] < span[1] <= DDR[1]):
        raise dsp.DspError(f"the span {span[0]:#x}..{span[1]:#x} is not word-aligned DDR")
    if span[0] < dsp.STOCK_DDR_END:
        raise dsp.DspError("the span starts inside the stock image")
    out = b""
    for at in range(span[0], span[1], FILL_BLOCK):
        count = min(FILL_BLOCK, span[1] - at)
        out += bootstream.block(at, flags=bootstream.FLAG_FILL, argument=pattern, count=count)
    return out


def section7_ddrscan(stock: bytes, span: tuple[int, int] = SPAN, pattern: int = PATTERN) -> bytes:
    """Stock + the idle stub + ddrscan.asm + SPAN filled with PATTERN. The idle loop's back
    edge goes to the scanner, which goes on to the idle stub."""
    base = dsp.section7_idle_only(stock)
    obj = objects()
    code = obj["ddrscan"]
    if SCAN_STATE_DM - SCAN_DM - len(code) < 64:
        raise dsp.DspError("ddrscan.asm leaves fewer than 64 bytes of NOP padding")
    if len(obj["scan_jump"]) != len(dsp.IDLE_SITE_STOCK):
        raise dsp.DspError(f"the scan JUMP is {len(obj['scan_jump'])} bytes, not {len(dsp.IDLE_SITE_STOCK)}")
    if not (dsp.IDLE_PAD_END <= SCAN_DM and SCAN_END_DM <= dsp.REGION[1]):
        raise dsp.DspError("ddrscan's spans leave the block-1 region")
    added = [("ddrscan.asm (wr_scan)", dsp.dm_to_load(SCAN_DM), code + bytes(SCAN_STATE_DM - SCAN_DM - len(code))),
             ("ddrscan state", dsp.dm_to_load(SCAN_STATE_DM), state(span, pattern))]
    dsp._check_free(stock, added)
    extra = b"".join(bootstream.block(at, payload) for _, at, payload in added) + fills(span, pattern)
    out = bytearray(bootstream.insert_before_final(base, extra))
    bootstream.write_span(out, dsp.l2_sw_to_load(dsp.IDLE_SITE_SW), obj["scan_jump"])
    return dsp._finish(out)


def decode(word: int) -> tuple[int, int]:
    """A reply word 2 as the ColdFire reads it (big-endian u32) -> (PUB index, value)."""
    return word >> 27, word & 0x7FFFFFF


def granules(bitmap: list[int]) -> list[int]:
    """PUB[4..19] -> the 2 MB granules that ever held a changed word."""
    return [16 * k + b for k, w in enumerate(bitmap) for b in range(16) if w >> b & 1]
