"""The loadmap diagnostic: Waverider's section 7 with cycle marks at every stage of the frame.

    apply(section7) -> the same stream with loadmap.asm, its 31 mark stubs and the retargeted
        jumps (only when DNFW_WAVERIDER_LOADMAP=1: dsp.section7 calls it last)

A mark stub is `CALL wr_lm_mark; JUMP <the original target>` (csrc/waverider/sharc/loadmap.asm
has the mechanism). The build retargets chosen jumps and calls to the stubs: stock's calls on
the frame's path, the splice and entry-mark JUMPs we already patch, and every jump into a
Waverider stage. Segment k runs from mark k to the next mark, so the 31 records split the frame
by stage; reply word 2 carries them out (tools/dn2loadmap.py).

The plan (which bytes change, and what they were) is computed by `scripts/build_loadmap.py
--assemble` on the Waverider stream of that moment and committed in loadmap_code.json, with that
stream's sha256. apply() refuses any other stream: a changed DSP object means a new --assemble.
No sample changes: every mark restores every register, ASTAT and MODE1.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

from ..image import bootstream, sharc_object

CODE = pathlib.Path(__file__).with_name("loadmap_code.json")

MARK_DM = 0x2DFC80                      # loadmap.asm: the mark, then the publisher (pool.asm's padding)
MARK_SW = MARK_DM // 2                  # 0x16fe40
MARK_END = 0x2DFFC0                     # 64 bytes of zeros stay before sync.asm
STUBS_DM = 0x2DF780                     # 12 bytes a stub (load.asm's padding)
STUBS_SW = STUBS_DM // 2                # 0x16fbc0
STUB_SW = 6
STATE_DM = 0x2DFA40                     # saves, LAST, CUR, BLOCKS, PUBK, SEQ (load state's padding)
RECORDS_DM = 0x2DFA80                   # 12 bytes a segment: cycles, passes, spare
RECORD_BYTES = 12
RECORDS_END = 0x2DFC00                  # pool.asm
SNAP_AT = 0x80780000                    # DDR: the window's copy, header + 2 words a segment
MAGIC = 0x4C4D0000
WINDOW_BLOCKS = 4096
PUBLISH_EVERY = 16                      # blocks a half stays in reply word 2
REPLY_WORD2 = (0x2C49D8, 0x2C59D8)

# (name, what the segment from this mark holds), in stub order. Stubs 0-2 and 22-30 are on
# stock's path, 3 is the mark's own cost, 4 the publisher, 5-21 Waverider's voice loop.
MARKS = (
    ("emark", "the per-block routine from the handler's call: prologue, unpack, until the dispatch"),
    ("dispatch", "the machine dispatch: prologue and the stock machines, until Waverider's splice"),
    ("splice", "block_count.asm"),
    ("null", "one mark's own cost (two marks back to back)"),
    ("publish", "loadmap.asm's publisher"),
    ("w_entry", "wr_type5v: the loop's saves and setup, and track 1's header"),
    ("w_voice", "wr_t5v_loop: a track's header (every track, Waverider or not)"),
    ("w_p5voice", "wr_p5_voice: page 5's per-voice setup"),
    ("w_osc", "wr_t5v_osc: an oscillator's parameters, until the trim"),
    ("w_move", "wr_trim: the trim and MOVE (modulator, shapes, sync, PRST)"),
    ("w_modded", "wr_t5v_modded: the gain, table slot, pool, SMTH, pitch"),
    ("w_phase", "wr_p5_phase: page 5's WARP and FM setup and phase pass"),
    ("w_dclk", "wr_dclk_pre: DCLK"),
    ("w_read", "wr_render5: the reader (WARP/FM reader or the mip reader), DCLK's mix, the osc's return"),
    ("w_p5mid", "wr_p5_mid: between the oscillators, page 5 keeps osc 1 for the shaper"),
    ("w_p5ran", "wr_p5_ran: page 5 after osc 2: shaper, FOLD, ring/AM, FM mix"),
    ("w_fmpost", "wr_fm_post: the Formant's per-voice core side"),
    ("w_sub", "wr_sub_ran: the sub-oscillator"),
    ("w_noise", "wr_noise: the noise"),
    ("w_next", "wr_t5v_next: the next track"),
    ("w_fmend", "wr_fm_end: the last voice's IIR0 wait"),
    ("w_exit", "wr_t5v_exit: restores, then stock's chain until its first marked call"),
    ("t_1cdb56", "stock per-track call 0x1cdb56 (x16) and the loop around it"),
    ("t_b80c39", "stock per-track call 0xb80c39 (x16), then the call 0xb8265b (x16)"),
    ("t_b81368", "stock per-track call 0xb81368 (x16)"),
    ("t_b82342", "stock per-track call 0xb82342 (x16)"),
    ("t_b80345", "stock per-track call 0xb80345 (x16), to the dispatch's end"),
    ("s_1c1738", "the per-block routine's call 0x1c1738"),
    ("s_1c1f1e", "the per-block routine's call 0x1c1f1e"),
    ("s_1c244d", "the per-block routine's call 0x1c244d"),
    ("s_tail", "from the call 0x1ca84e: the routine's end, the handler's rest, other tasks and idle"),
)
N = len(MARKS)
HALVES = 2 * (3 + 2 * N)


class LoadmapError(RuntimeError):
    pass


def stub_sw(k: int) -> int:
    return STUBS_SW + STUB_SW * k


def _code() -> dict:
    if not CODE.exists():
        raise LoadmapError(f"{CODE.name} is missing: run scripts/build_loadmap.py --assemble")
    return json.loads(CODE.read_text(encoding="utf-8"))


def stubs(targets: list[int]) -> bytes:
    """Each stub's memory bytes: CALL wr_lm_mark; JUMP target."""
    if len(targets) != N:
        raise LoadmapError(f"{len(targets)} targets for {N} marks")
    be = b"".join(bytes.fromhex(f"06be00{MARK_SW:06x}063e00{t:06x}") for t in targets)
    return sharc_object.load_bytes(be)


def apply(section7: bytes) -> bytes:
    """Waverider's section 7 -> the loadmap build's. Refuses a stream the plan was not made on."""
    spec = _code()
    digest = hashlib.sha256(section7).hexdigest()
    if digest != spec["base_section7_sha256"]:
        raise LoadmapError(f"section 7 {digest[:12]}... is not the stream the loadmap plan was made on "
                           f"({spec['base_section7_sha256'][:12]}...): rerun scripts/build_loadmap.py --assemble")
    if [m["name"] for m in spec["marks"]] != [m[0] for m in MARKS]:
        raise LoadmapError("loadmap_code.json's marks are not MARKS")
    code = sharc_object.load_bytes(bytes.fromhex(spec["loadmap"]["object_parcels_be"]))
    if MARK_DM + len(code) > MARK_END:
        raise LoadmapError(f"loadmap.asm is {len(code)} bytes: past {MARK_END:#x}")
    if RECORDS_DM + RECORD_BYTES * N > RECORDS_END:
        raise LoadmapError(f"{N} records do not fit before {RECORDS_END:#x}")
    stub = stubs([m["target_sw"] for m in spec["marks"]])
    from . import dsp                    # noqa: PLC0415  (dsp imports this module lazily)
    for what, dm, payload in (("stubs", STUBS_DM, stub), ("loadmap.asm", MARK_DM, code),
                              ("state and records", STATE_DM, bytes(RECORDS_END - STATE_DM))):
        if any(bootstream.read_span(section7, dsp.dm_to_load(dm), len(payload))):
            raise LoadmapError(f"the {what} span at DM {dm:#x} is not zeros in Waverider's stream")
    # the padding there is fill blocks (no bytes in the file): the code goes in blocks of its own,
    # loaded after the fill; the state and the records stay the fill's zeros
    out = bytearray(bootstream.insert_before_final(
        section7, dsp.stream_blocks(dsp.dm_to_load(STUBS_DM), stub) + dsp.stream_blocks(dsp.dm_to_load(MARK_DM), code)))
    for p in spec["patches"]:
        at, old, new = p["load"], bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        if bootstream.read_span(section7, at, len(old)) != old:
            raise LoadmapError(f"{p['what']}: the bytes at {at:#x} are not {old.hex()}")
        bootstream.write_span(out, at, new)
    result = bytes(out)
    walked = bootstream.walk(result)
    if not walked.complete or walked.stopped_at != len(result):
        raise LoadmapError(f"the loadmap stream does not walk ({walked.reason})")
    return result


# -- reading it back (tools/dn2loadmap.py) --------------------------------------------------

FRAME_CYCLES = 666_667                  # a block at 1 GHz, 1,500 blocks a second
PAGE_WORDS = 24
PAGE_DATA = 22
PAGES = 3
ROWS_AT = 0x1C + 0x54 + 0x44            # page word 0 in the reply record (row 1, entry 11)
ROWS_SPAN = 0x54 * (PAGE_WORDS // 2 - 1) + 8


def unswap(v: int) -> int:
    """The ColdFire's big-endian read of a DSP word has its halves swapped."""
    return (v & 0xFFFF) << 16 | v >> 16


def page_words(record: bytes) -> list[int]:
    """The 24 page words from ROWS_SPAN bytes read at the record copy + ROWS_AT (big-endian)."""
    out = []
    for j in range(PAGE_WORDS):
        at = 0x54 * (j // 2) + 4 * (j % 2)
        out.append(unswap(int.from_bytes(record[at:at + 4], "big")))
    return out


def decode_page(words: list[int]) -> tuple[int, int, list[int]] | None:
    """-> (SEQ & 0xff, p, its 22 SNAP words), or None: no loadmap tag, or a torn read."""
    w0 = words[0]
    if w0 >> 16 != MAGIC >> 16 or (w0 & 0xFF) >= PAGES:
        return None
    x = 0
    for w in words[:PAGE_WORDS - 1]:
        x ^= w
    if x != words[PAGE_WORDS - 1]:
        return None
    return (w0 >> 8) & 0xFF, w0 & 0xFF, words[1:PAGE_WORDS - 1]


def snapshot(pages: dict[int, list[int]]) -> dict:
    """Pages 0-2 of one window -> its segments: (name, cycles, passes) each, per window."""
    snap = [w for p in range(PAGES) for w in pages[p]]
    if snap[0] != MAGIC | N:
        raise LoadmapError(f"SNAP's header is {snap[0]:#x}, not {MAGIC | N:#x}: another layout")
    blocks = snap[1]
    segs = [(MARKS[k][0], snap[3 + 2 * k], snap[4 + 2 * k]) for k in range(N)]
    return {"blocks": blocks, "seq": snap[2], "segments": segs}


def table(snap: dict) -> list[str]:
    """Per segment: passes and cycles per block, cycles a pass, % of a frame, net of the marks."""
    blocks = snap["blocks"]
    segs = snap["segments"]
    null = next(s for s in segs if s[0] == "null")
    mark = null[1] / max(1, null[2])                  # cycles of one mark (each segment holds one per pass)
    out = [f"window {snap['seq']}: {blocks} blocks; one mark {mark:.0f} cycles",
           f"{'segment':10s} {'passes/blk':>10s} {'cycles/blk':>11s} {'per pass':>9s} {'% frame':>8s} {'net %':>7s}"]
    total = net_total = 0.0
    for name, cyc, n in segs:
        per_block, passes = cyc / blocks, n / blocks
        net = max(0.0, per_block - passes * mark)
        total += per_block
        net_total += net
        out.append(f"{name:10s} {passes:10.2f} {per_block:11,.0f} {cyc / max(1, n):9,.0f} "
                   f"{100 * per_block / FRAME_CYCLES:8.2f} {100 * net / FRAME_CYCLES:7.2f}")
    out.append(f"{'all':10s} {'':10s} {total:11,.0f} {'':9s} {100 * total / FRAME_CYCLES:8.2f} "
               f"{100 * net_total / FRAME_CYCLES:7.2f}   (s_tail holds the idle time)")
    return out
