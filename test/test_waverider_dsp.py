"""dnfw.waverider.dsp / live / harmonics: Milestone 5's section-7 builder and its contract.

The runner gate is scripts/sharc_waverider_m5.py; these need no runner, no WSL and
no firmware beyond the DN2 1.11 image (skipped cleanly when it is absent).
"""

from __future__ import annotations

import cmath
import hashlib
import json
import math
import pathlib
import struct

import pytest

from dnfw.image import bootstream, sharc_object
from dnfw.waverider import dsp, harmonics, live, reduce, render, testtable
from dnfw.waverider import render as reference

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGE = ROOT / "00_Resources" / "00_Firmware" / "Digitone_II_OS1.11_dist.zip"
SHARC = ROOT / "csrc" / "waverider" / "sharc"


@pytest.fixture(scope="module")
def stock7() -> bytes:
    if not IMAGE.exists():
        pytest.skip(f"{IMAGE.name} not present")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    sec = load(read_image(IMAGE)).container.find(7)
    return sec.unpack() or sec.raw_payload


@pytest.fixture(scope="module")
def built(stock7) -> bytes:
    return dsp.section7(stock7)


# -- the committed objects -----------------------------------------------------------------

def test_committed_objects_match_their_sources():
    spec = json.loads(dsp.CODE.read_text(encoding="utf-8"))
    for key in ("reader", "machine5_live", "idle_load", "block_count", "entry_mark", "modulator"):
        name = pathlib.Path(spec[key]["source"]).stem      # reader_m9 / machine9_live from M9a
        src = (SHARC / f"{name}.asm").read_bytes().replace(b"\r\n", b"\n")
        assert spec[key]["source_sha256"] == hashlib.sha256(src).hexdigest(), name
        csrc = json.loads((SHARC / f"{name}.json").read_text(encoding="utf-8"))
        assert csrc["object_parcels_be"] == spec[key]["object_parcels_be"], name
    assert spec["entry_jump"]["source"] == "JUMP 0x16f600;"
    assert spec["idle_jump"]["source"] == "JUMP 0x16f500;" and spec["idle_jump"]["at_sw"] == "0xb88abb"


def test_our_sources_avoid_dag1_m0_m3_in_memory_accesses():
    """No DM(..M0..M3..) access and no pre-modify read outside a DO loop (the two
    forms selas and selmap disagree on; docs/waverider-m5-dsp.md)."""
    import re
    for name in ("reader_m5", "machine5_live", "idle_load", "block_count", "entry_mark"):
        in_loop = False
        for line in (SHARC / f"{name}.asm").read_text().splitlines():
            code = line.split("//", 1)[0].strip().upper()
            if "DO " in code and "UNTIL" in code:
                in_loop = True
            assert not re.search(r"DM\s*\([^)]*\bM[0-3]\b", code), (name, line)
            # the one exception is the firmware's own return idiom, byte for byte
            # its `i12=dm(m7,i6)` (3b fe4d3f0e)
            if re.search(r"DM\s*\(\s*M\d+\s*,", code) and code != "I12 = DM(M7, I6);":
                assert in_loop, (name, line)
            if code.startswith(".WR5_LOOP_END"):
                in_loop = False


# -- the builder ------------------------------------------------------------------------------

def test_refuses_anything_but_stock(stock7):
    with pytest.raises(dsp.DspError):
        dsp.section7(stock7[:100] + bytes([stock7[100] ^ 1]) + stock7[101:])


def test_is_deterministic_and_walks(stock7, built):
    assert dsp.section7(stock7) == built
    w = bootstream.walk(built)
    assert w.complete and w.stopped_at == len(built)


def test_every_added_span_is_in_block_1s_free_tail_and_outside_every_stock_block(stock7):
    # Milestone 5c: M5's L1 block 2 silenced the instrument (docs/waverider-dsp-silence.md)
    stock_blocks = [b for b in bootstream.walk(stock7).blocks if b.count]
    for what, at, payload in dsp.spans():
        if at >= 0x80000000:                                    # the tables, in DDR above the image
            assert 0x8052FBE0 <= at and at + len(payload) <= 0x80A00000, what
        else:
            lo, hi = at - dsp.LOAD_ALIAS, at - dsp.LOAD_ALIAS + len(payload)
            assert 0x2DD52C <= lo and hi <= 0x2E8000, what      # above stock, below a 32 KB DM cache
            assert not (0x300000 <= lo < 0x320000), what        # nothing left in block 2
        for b in stock_blocks:
            assert not (b.target < at + len(payload) and at < b.target + b.count), what


def test_loaded_image_holds_our_bytes(built):
    for what, at, payload in dsp.spans():
        assert bootstream.read_span(built, at, len(payload)) == payload, what


def test_the_six_patches_and_nothing_else_in_the_stock_blocks(stock7, built):
    entry = bootstream.read_span(built, dsp.sw_to_load(dsp.ENTRY_SW), 8)
    assert entry == bytes.fromhex("3e06160000f60100")          # jump 0x16f600 (the block counter) ; nop
    lookup = struct.unpack("<8I", bootstream.read_span(built, dsp.dm_to_load(dsp.LOOKUP_DM), 32))
    assert lookup == (0, 1, 2, 3, 4, 5, 0, 0)
    # the idle loop's back edge, jump (pc,-0x10) at sw 0xb88abb in L2, becomes JUMP 0x16f500
    site = dsp.l2_sw_to_load(dsp.IDLE_SITE_SW)
    assert bootstream.read_span(stock7, site, 6) == bytes.fromhex("3e07ff00f0ff")
    assert bootstream.read_span(built, site, 6) == bytes.fromhex("3e061600" "00f5")
    # the handler's call of the per-block routine: r4 = 0x268438 becomes JUMP 0x16f680
    call = dsp.sw_to_load(dsp.CALL_SITE_SW)
    assert bootstream.read_span(stock7, call, 6) == dsp.CALL_SITE_STOCK
    assert bootstream.read_span(built, call, 6) == dsp.objects()["emark_jump"]
    # the clamp min(R2, 4) stays stock: its R0 = 0x4 parcel pair at sw 0x1c294a
    clamp = dsp.sw_to_load(0x1C294A)
    assert bootstream.read_span(built, clamp, 4) == bootstream.read_span(stock7, clamp, 4) \
        == bytes.fromhex("800f0400")
    # the per-type setup table is not touched
    assert bootstream.read_span(built, 0x8052DB90, 24) == bootstream.read_span(stock7, 0x8052DB90, 24)
    # every stock block's payload differs from stock only at the two patches
    final = bootstream.walk(stock7).final
    head = built[:final.offset]
    diff = [k for k in range(final.offset) if head[k] != stock7[k]]
    entry_off = bootstream.spans(stock7, dsp.sw_to_load(dsp.ENTRY_SW), 8)[0][0]
    look_off = bootstream.spans(stock7, dsp.dm_to_load(dsp.LOOKUP_DM + 20), 4)[0][0]
    idle_off = bootstream.spans(stock7, dsp.l2_sw_to_load(dsp.IDLE_SITE_SW), 6)[0][0]
    call_off = bootstream.spans(stock7, dsp.sw_to_load(dsp.CALL_SITE_SW), 6)[0][0]
    table_off = bootstream.spans(stock7, dsp.sw_to_load(dsp.TABLE_SITE_SW), 6)[0][0]
    bound_off = bootstream.spans(stock7, dsp.sw_to_load(dsp.BOUND_SITE_SW), 6)[0][0]
    allowed = (set(range(entry_off, entry_off + 8)) | set(range(look_off, look_off + 4))
               | set(range(idle_off, idle_off + 6)) | set(range(call_off, call_off + 6))
               | set(range(table_off, table_off + 6)) | set(range(bound_off, bound_off + 6)))
    assert diff and set(diff) <= allowed


def test_the_command_dispatch_takes_eight_commands_from_the_moved_table(stock7, built):
    """`i4 = 0x268a68` -> `i4 = 0x2dfa00` and `lshift by -2` -> `-3`, each one field of a
    48-bit instruction (16-bit little-endian parcels); the moved table keeps the stock
    four, puts load.asm at 4 and case 0's code at 5..7, as stock does for 4 and up."""
    for sw, old, new in ((dsp.TABLE_SITE_SW, dsp.TABLE_SITE_STOCK, dsp.TABLE_SITE_NEW),
                         (dsp.BOUND_SITE_SW, dsp.BOUND_SITE_STOCK, dsp.BOUND_SITE_NEW)):
        assert bootstream.read_span(stock7, dsp.sw_to_load(sw), 6) == old
        assert bootstream.read_span(built, dsp.sw_to_load(sw), 6) == new
    # the immediate: parcels 2 and 3 hold 0x00268a68 / 0x002dfa00
    assert struct.unpack("<HH", dsp.TABLE_SITE_NEW[2:]) == (0x002D, 0xFA00) == (dsp.CMD_TABLE_DM >> 16,
                                                                                dsp.CMD_TABLE_DM & 0xFFFF)
    # the shift: the immediate byte -2 -> -3, the sign bits (0x78) stock's
    assert dsp.BOUND_SITE_NEW[:5] == dsp.BOUND_SITE_STOCK[:5] and dsp.BOUND_SITE_NEW[5] == 0xFD
    assert struct.unpack("<4I", bootstream.read_span(stock7, dsp.dm_to_load(0x268A68), 16)) == dsp.CMD_STOCK
    table = struct.unpack("<8I", bootstream.read_span(built, dsp.dm_to_load(dsp.CMD_TABLE_DM), 32))
    assert table == (*dsp.CMD_STOCK, dsp.LOAD_SW, dsp.CMD_STOCK[0], dsp.CMD_STOCK[0], dsp.CMD_STOCK[0])


def test_the_loader_renders_through_case_3_from_the_frame_copy():
    spec = json.loads((SHARC / "load.json").read_text(encoding="utf-8"))
    assert int(spec["load_sw"], 16) == dsp.LOAD_SW == 0x16FB00
    be = bytes.fromhex(spec["object_parcels_be"])
    assert be[spec["instruction_offsets"][-1]:].hex() == "063e001c9f0f"      # JUMP 0x1c9f0f, case 3
    src = [ln.split("//", 1)[0].strip() for ln in (SHARC / "load.asm").read_text().splitlines()]
    assert {c for c in src if c.startswith("DM(0x")} == {
        "DM(0x2dfa20) = R10;", "DM(0x2dfa24) = R10;",                       # its state words
        "DM(0x2c49e8) = R10;", "DM(0x2c59e8) = R10;"}                       # reply word 6, both pages
    assert "I3 = 0x25c48c;" in src                                          # the frame copy, case 3's argument
    # what the dispatch set for case 3, restored before the jump (sw 0x1c9da2..0x1c9dbd)
    tail = src[src.index("I3 = 0x25c48c;") - 4:src.index("I3 = 0x25c48c;")]
    assert tail == ["R0 = 8;", "R11 = 8;", "R12 = 2;", "R13 = 4;"]
    # the bounds it checks are the build's own
    assert "R0 = 668;" in src and dsp.LOAD_MAX_WORDS == 668 == (2688 - 16) // 4
    assert "R0 = 0x80800000;" in src and dsp.LOAD_AREA[0] == 0x80800000
    assert "R0 = 0x200000;" in src and dsp.LOAD_AREA[1] - dsp.LOAD_AREA[0] == 0x200000
    assert "R0 = 0xffe00003;" in src                                        # below 2 MB, 4-aligned
    # the load area is DDR the stock image does not use, above both baked tables
    assert dsp.DDR_REGION[0] <= dsp.TABLES_DM[-1] + dsp.TABLE_BYTES <= dsp.LOAD_AREA[0]
    assert dsp.LOAD_AREA[1] <= dsp.DDR_REGION[1]
    assert dsp.LOAD_STATE_DM >= dsp.CMD_TABLE_DM + 32


def test_directory_names_both_tables():
    d = dsp.directory()
    assert struct.unpack_from("<4I", d) == (0x57525431, 2, 0x80600000, 0x80604000)


def test_the_tables_load_into_ddr_above_the_stock_image(stock7, built):
    # the stock stream's last DDR byte is 0x8052fbe0; the tables sit above it, below
    # the Digitakt II's pool at 0x80a00000, at their own addresses (no load alias)
    last = max(b.target + b.count for b in bootstream.walk(stock7).blocks
               if b.count and b.target >= 0x80000000)
    assert last == dsp.STOCK_DDR_END
    for k, at in enumerate(dsp.TABLES_DM):
        assert last < at and at + dsp.TABLE_BYTES <= 0x80A00000
        assert bootstream.read_span(built, at, dsp.TABLE_BYTES) == \
            reference.dsp_bytes(dsp.tables()[k])
    # L1 keeps only code and state: MOVE's shapes and their random state (M10b-4) sit
    # where table 0 began; after them the loader, its command table and its state, the
    # pool lookup, then SYNC (M10b-2) and its note table, which runs to the region's end
    sp = {what: (at, p) for what, at, p in dsp.spans()}
    assert sp["shapes.asm (wr_shape)"][0] == dsp.dm_to_load(0x2DF000)
    at, p = sp["MOVE's random state (zeros)"]
    assert at + len(p) == dsp.dm_to_load(dsp.LOAD_DM) and not any(p)
    at, p = sp["load state (zeros)"]
    assert at + len(p) == dsp.dm_to_load(dsp.POOL_DM) and not any(p)
    at, p = sp["pool.asm (wr_pool)"]
    assert at + len(p) == dsp.dm_to_load(dsp.SYNC_DM)
    at, p = sp["SYNC's note table, a word per RATE"]
    assert at == dsp.dm_to_load(dsp.SYNC_TABLE_DM) and at + len(p) == dsp.dm_to_load(dsp.REGION[1])
    assert struct.unpack_from("<101I", p) == live.sync_table()


def test_the_pool_directory_starts_empty_inside_the_load_area(built):
    # the ColdFire writes the pool's directory last; until then the boot stream's zeros
    # make pool.asm fall back to slot 0, and its tables fit below the directory
    assert dsp.LOAD_AREA[0] + dsp.POOL_SLOTS * dsp.TABLE_BYTES <= dsp.POOL_DIR < dsp.LOAD_AREA[1]
    assert dsp.POOL_SLOTS == 127
    assert bootstream.read_span(built, dsp.POOL_DIR, dsp.POOL_ZEROS) == bytes(dsp.POOL_ZEROS)


# -- the contract -------------------------------------------------------------------------------

def test_increment_table_is_equal_tempered_at_48k():
    t = live.increment_table()
    assert len(t) == 129
    assert t[69] == pytest.approx(440 / 48000 * 2 ** 32, rel=1e-7)
    assert all(b > a for a, b in zip(t, t[1:]))
    assert t[128] < 2 ** 31                                    # TRUNC stays in range
    assert live.table_bytes() == struct.pack("<129f", *t)


def test_increment_follows_the_note():
    assert live.increment(72.0) == 2 * live.increment(60.0)
    assert live.increment(-5.0) == live.increment(0.0)         # clamped
    assert live.increment(200.0) == live.increment(127.0)
    lo, mid, hi = live.increment(60.0), live.increment(60.5), live.increment(61.0)
    assert lo < mid < hi


def test_position_and_slot_from_frame_words():
    assert live.position(0) == 0
    assert live.position(0x7800) == 15 << 16                   # the frame: the sound's own 0x7800
    assert live.position(0x7F00) == 15 << 16                   # clamped
    assert live.position(0x4000) == 0x4000 << 5
    assert live.slot(0x0000, 2) == 0 and live.slot(0x0100, 2) == 1   # TBL1 1, as the probe read it
    assert live.slot(0x0200, 2) == 0                           # out of range -> 0


def test_tun1_is_the_sounds_own_scale():
    """Read on the instrument through the USB probe, 2026-09-30."""
    assert live.tuned(60.0, 0x4000) == 60.0
    assert live.tuned(60.0, 0x4100) == 61.0
    assert live.tuned(60.0, 0x4c00) == 72.0
    assert live.tuned(60.0, 0x3400) == 48.0
    assert live.tuned(60.0, 0x4080) == 60.5
    assert live.tuned(3.0, 0x0400) == 0.0                      # below note 0 -> 0


def test_render_blocks_carries_phase_across_a_slot_change():
    tables = dsp.tables()
    a, ph = live.render_blocks(tables, [(60.0, 0, 0)], 32)
    b, _ = live.render_blocks(tables, [(60.0, 0, 0x100)], 32, ph)
    both, _ = live.render_blocks(tables, [(60.0, 0, 0), (60.0, 0, 0x100)], 32)
    assert both == a + b


def test_render_two_is_osc1_alone_when_lev2_is_0():
    tables = dsp.tables()
    one, _ = live.render_blocks(tables, [(60.0, 0x7800, 0, 0x4000, 0x6400)] * 3, 32)
    two = live.render_two(tables, [(60.0, (0x7800, 0, 0x4000, 0x6400), (0, 0x100, 0x4c00, 0))] * 3, 32)
    assert two == one


def test_render_two_mixes_osc2_with_its_own_phase():
    tables = dsp.tables()
    osc = (0x7800, 0, 0x4000, 0x6400)
    one, _ = live.render_blocks(tables, [(60.0, *osc)] * 3, 32)
    assert live.render_two(tables, [(60.0, osc, osc)] * 3, 32) == [2 * x for x in one]
    silent1 = (0x7800, 0, 0x4000, 0)
    assert live.render_two(tables, [(60.0, silent1, osc)] * 3, 32) == one   # osc 2 alone


def test_detn_is_a_detune_from_osc1():
    assert live.tuned2(60.0, 0x4000, 0x4c00) == 72.0          # TUNE +12 moves osc 2 too
    assert live.tuned2(60.0, 0x4700, 0x4c00) == 79.0          # + DETN +7
    assert live.tuned2(60.0, 0x4700, 0x4000) == 67.0
    tables = dsp.tables()
    up = (0x7800, 0, 0x4c00, 0)                                 # osc 1 silent, TUNE +12
    alone, _ = live.render_blocks(tables, [(72.0, 0x7800, 0, 0x4000, 0x6400)] * 3, 32)
    assert live.render_two(tables, [(60.0, up, (0x7800, 0, 0x4000, 0x6400))] * 3, 32) == alone


# -- the tables -----------------------------------------------------------------------------------

def _partial(frame, h):
    n = len(frame)
    return abs(sum(v * cmath.exp(-2j * math.pi * h * k / n) for k, v in enumerate(frame))) / n


def test_slot0_is_the_saw_at_pos0_and_the_sine_at_pos15():
    t0 = dsp.tables()[0]
    assert t0 == list(reversed(testtable.table()))
    assert _partial(t0[0], 2) > 0.2 * _partial(t0[0], 1)       # bright: harmonics present
    assert _partial(t0[15], 2) < 1e-3 * _partial(t0[15], 1)    # pure sine


def test_harmonics_frame_k_is_partial_k_plus_1():
    t = harmonics.table()
    assert len(t) == reduce.FRAMES and all(len(f) == reduce.POINTS for f in t)
    for k in (0, 1, 7, 15):
        strongest = max(range(1, 20), key=lambda h: _partial(t[k], h))
        assert strongest == k + 1


def test_tables_are_original_and_distinct():
    t0, t1 = dsp.tables()
    assert t0 != t1
    assert render.dsp_bytes(t0) != render.dsp_bytes(t1)


def test_the_region_is_written_end_to_end_and_code_is_nop_padded():
    sp = [x for x in dsp.spans() if x[1] < 0x80000000]       # L1 (the tables are in DDR)
    at = [a - dsp.LOAD_ALIAS for _, a, _ in sp]
    ends = [a - dsp.LOAD_ALIAS + len(p) for _, a, p in sp]
    assert at[0] == dsp.REGION[0] and ends[-1] == dsp.REGION[1]
    assert all(e == a for e, a in zip(ends, at[1:]))           # no unwritten gap
    obj = dsp.objects()
    code_spans = [x for x in sp if "asm" in x[0]]
    assert len(code_spans) == 10                              # + modulator.asm (M10a), shapes.asm (M10b-4), load.asm, pool.asm, sync.asm (M10b-2)
    for (what, _, payload), code in zip(code_spans, (obj["reader"], obj["machine5_live"], obj["idle_load"],
                                                     obj["block_count"], obj["entry_mark"], obj["modulator"],
                                                     obj["shapes"], obj["load"], obj["pool"], obj["sync"])):
        assert payload[:len(code)] == code
        assert len(payload) - len(code) >= 64 and not any(payload[len(code):]), what


def test_the_idle_only_stream_is_stock_but_the_stub(stock7):
    """section7_idle_only: the stock engine with the idle stub and nothing of Waverider."""
    built = dsp.section7_idle_only(stock7)
    w = bootstream.walk(built)
    assert w.complete and w.stopped_at == len(built)
    site = dsp.l2_sw_to_load(dsp.IDLE_SITE_SW)
    assert bootstream.read_span(built, site, 6) == bytes.fromhex("3e061600" "00f5")
    # idle-only: the handler's call of the per-block routine stays stock
    assert bootstream.read_span(built, dsp.sw_to_load(dsp.CALL_SITE_SW), 6) == dsp.CALL_SITE_STOCK
    code = dsp.objects()["idle_load"]
    assert bootstream.read_span(built, dsp.dm_to_load(dsp.IDLE_DM), len(code)) == code
    assert bootstream.read_span(built, dsp.dm_to_load(dsp.IDLE_STATE_DM), 0x20) == bytes(0x20)
    # none of Waverider: the entry and the lookup stay stock
    assert bootstream.read_span(built, dsp.sw_to_load(dsp.ENTRY_SW), 8) == dsp.ENTRY_STOCK
    lookup = struct.unpack("<8I", bootstream.read_span(built, dsp.dm_to_load(dsp.LOOKUP_DM), 32))
    assert lookup == dsp.LOOKUP_STOCK
    final = bootstream.walk(stock7).final
    diff = [k for k in range(final.offset) if built[k] != stock7[k]]
    idle_off = bootstream.spans(stock7, site, 6)[0][0]
    assert diff and set(diff) <= set(range(idle_off, idle_off + 6))


def test_the_idle_stub_is_placed_and_returns_where_its_source_says():
    """idle_load.asm: its skip lands on wr_idle_out, it returns to the idle loop's top,
    and its variables sit in the state block's free tail, clear of the render loop's."""
    spec = json.loads((SHARC / "idle_load.json").read_text(encoding="utf-8"))
    assert int(spec["load_sw"], 16) == dsp.IDLE_SW == 0x16F500
    be = bytes.fromhex(spec["object_parcels_be"])
    offs = spec["instruction_offsets"]
    text = (SHARC / "idle_load.asm").read_text()
    # wr_idle's own instructions: the file goes on with wr_prst (M10b-3), tested below
    text = text[:text.index(".wr_idle..end:")]
    src = [ln.split("//", 1)[0].strip() for ln in text.splitlines()]
    src = [c for c in src if c and not c.startswith(".") and not c.endswith(":")]
    at = {c: dsp.IDLE_SW + o // 2 for c, o in zip(src, offs)}
    assert at["R8 = DM(0x2de100);"] == 0x16F57B                   # wr_idle_out.
    assert at["R8 = DM(0x2de10c);"] == 0x16F55A                   # wr_idle_after.
    assert be[offs[src.index("IF GE JUMP 0x16f53d;")]:][:6].hex() == "06220016f53d"
    assert at["R11 = DM(0x2de13c);"] == 0x16F53D                  # wr_idle_busy.
    last = offs[len(src) - 1]
    assert be[last:last + 6].hex() == "063e00b88aab" and dsp.IDLE_RETURN_SW == 0xB88AAB
    # its DM: 0x2de100..0x2de117, after the 16 reader blocks (to 0x2de100) and inside the state block
    assert dsp.READER_BLOCKS_DM + 16 * dsp.READER_BLOCK_BYTES == dsp.IDLE_STATE_DM
    assert dsp.IDLE_STATE_DM + dsp.IDLE_STATE_BYTES <= dsp.STATE_DM + dsp.STATE_BYTES == dsp.INC_TABLE_DM
    stores = {c for c in src if c.startswith("DM(")}
    assert stores <= {"DM(0x2de100) = R8;", "DM(0x2de104) = R9;", "DM(0x2de108) = R10;", "DM(0x2de134) = R11;",
                      "DM(0x2de114) = R9;", "DM(0x2de10c) = R8;", "DM(0x2de110) = R9;",
                      "DM(0x2de128) = R9;", "DM(0x2de12c) = R9;",
                      "DM(0x2c49d4) = R9;", "DM(0x2c59d4) = R9;", "DM(0x2c49dc) = R9;", "DM(0x2c59dc) = R9;",
                      "DM(0x2c49e0) = R9;", "DM(0x2c59e0) = R9;"}


def test_the_block_counter_goes_on_to_the_loop():
    spec = json.loads((SHARC / "block_count.json").read_text(encoding="utf-8"))
    assert int(spec["load_sw"], 16) == dsp.COUNT_SW == 0x16F600
    be = bytes.fromhex(spec["object_parcels_be"])
    assert be[spec["instruction_offsets"][-1]:].hex() == "063e0016ed00"   # JUMP 0x16ed00, the loop
    src = [ln.split("//", 1)[0].strip() for ln in (SHARC / "block_count.asm").read_text().splitlines()]
    stores = {c for c in src if c.startswith("DM(")}
    assert stores == {"DM(0x2de11c) = R8;", "DM(0x2de120) = R9;", "DM(0x2de118) = R8;",
                      "DM(0x2c49d8) = R8;", "DM(0x2c59d8) = R8;", "DM(0x2de124) = R8;"}
    assert dsp.IDLE_STATE_DM + dsp.IDLE_STATE_BYTES >= 0x2DE124 and dsp.IDLE_STATE_DM + dsp.IDLE_STATE_BYTES <= dsp.INC_TABLE_DM


def test_the_entry_mark_does_the_displaced_load_and_returns_to_the_call():
    spec = json.loads((SHARC / "entry_mark.json").read_text(encoding="utf-8"))
    assert int(spec["load_sw"], 16) == dsp.EMARK_SW == 0x16F680
    be = bytes.fromhex(spec["object_parcels_be"])
    offs = spec["instruction_offsets"]
    assert be[offs[-1]:].hex() == "063e001c9fbc"                    # JUMP 0x1c9fbc, the cjump
    assert sharc_object.load_bytes(be[offs[-2]:offs[-1]]) == dsp.CALL_SITE_STOCK  # r4 = 0x268438, as stock
    src = [ln.split("//", 1)[0].strip() for ln in (SHARC / "entry_mark.asm").read_text().splitlines()]
    assert {c for c in src if c.startswith("DM(")} == {"DM(0x2de138) = R9;", "DM(0x2de13c) = R9;"}
    assert dsp.IDLE_STATE_DM + dsp.IDLE_STATE_BYTES >= 0x2DE140


def test_the_reader_returns_in_the_firmwares_shape():
    lines = [ln.split("//", 1)[0].strip() for ln in (SHARC / "reader_m5.asm").read_text().splitlines()]
    lines = [ln for ln in lines if ln]
    k = lines.index("I12 = DM(M7, I6);")
    assert lines[k + 2] == "JUMP (M14, I12) (DB);" and lines[k + 1] != lines[k + 2]
    assert lines[k + 4] == "RFRAME;"                           # second delay slot


# -- M10a: MOVE ----------------------------------------------------------------------------------

def test_move_defaults_leave_pos_and_lev_untouched():
    for s in (0, 0x8000, 0xFFFF):
        assert live.move_apply(0x3C00, 0x6400, live.MPOS_NONE, 0, s) == (0x3C00, 0x6400)


def test_move_rate_is_one_second_at_50_and_doubles_every_10():
    one = live.MOVE_RATE[0] << 5                                 # RATE 50
    assert abs(one * 1500 / 2 ** 32 - 1.0) < 1e-4
    assert (live.MOVE_RATE[0] << 6) == 2 * one                    # RATE 60: twice as fast
    assert live.move_step(0, 0x3200, 0x0100, 0, False) == one


def test_move_shapes():
    up, down, tri, upl, downl, tril, sq = 0x0000, 0x0100, 0x0400, 0x0500, 0x0600, 0x0700, 0x0800
    for d in (down, downl):
        assert live.move_shape(0, d) == 0xFFFF and live.move_shape(0xFFFFFFFF, d) == 0
    for u in (up, upl):
        assert live.move_shape(0x40000000, u) == 0x4000
    for t in (tri, tril):
        assert live.move_shape(0x40000000, t) == 0x8000 and live.move_shape(0xC0000000, t) == 0x7FFE
    assert live.move_shape(0x10000000, sq) == 0xFFFF and live.move_shape(0x90000000, sq) == 0


def test_exp_shapes_curve_from_end_to_end():
    up, down = 0x0200, 0x0300
    assert live.move_shape(0, up) == 0 and live.move_shape(0xFFFFFFFF, up) >= 0xFFFC
    assert live.move_shape(0x80000000, up) == 0x2000               # half way: an eighth
    assert live.move_shape(0, down) >= 0xFFFC and live.move_shape(0xFFFFFFFF, down) == 0
    assert live.move_shape(0x80000000, down) == 0x1FFF
    xs = [live.move_shape(p << 24, up) for p in range(256)]
    assert all(b >= a for a, b in zip(xs, xs[1:]))


def test_names_sort_the_shapes_by_nature_and_a_value_past_the_last_is_the_last():
    assert live.MOVE_SHAPES[:live.ONE_SHOTS] == ("Ramp Up", "Ramp Down", "Exp Up", "Exp Down", "Tri Once")
    assert live.MOVE_SHAPES[live.RND_HOLD:] == ("Rnd Hold", "Rnd Glide")
    assert live.move_band(0x7F00) == live.RND_GLIDE
    assert all(len(n) <= 9 and "&" not in n for n in live.MOVE_SHAPES)   # the header, the font


def test_one_shots_hold_their_end_and_loops_wrap():
    near = 0xFFFF0000
    for one in range(live.ONE_SHOTS):
        assert live.move_step(near, 0x6400, one << 8, 0, False) == 0xFFFFFFFF   # holds
    for loop in range(live.ONE_SHOTS, len(live.MOVE_SHAPES)):
        assert live.move_step(near, 0x6400, loop << 8, 0, False) < near         # wraps


def test_random_shapes_draw_on_a_wrap_and_on_a_restart_only():
    r = live.MoveRandom()
    hold = live.RND_HOLD << 8
    r.step(0, 0x1000, 0x2000, hold, False)                       # moving on: no draw
    assert r.values(0) == [0, 0] and r.x == 0
    r.step(0, 0xFFFF0000, 0x10, hold, False)                     # a wrap: a new value
    first = live.rnd_next(0) >> 16
    assert r.values(0) == [0, first]
    r.step(0, 0, 0x10, hold, True)                               # a restart: another
    assert r.values(0) == [first, live.rnd_next(live.rnd_next(0)) >> 16]
    r.step(1, 0xFFFF0000, 0x10, 0x0700, False)                   # not a random shape
    assert r.values(1) == [0, 0]
    assert live.move_shape(0x12345678, hold, (5, 9)) == 9


def test_glide_runs_from_the_value_before_to_the_new_one_smoothly():
    g = live.RND_GLIDE << 8
    assert live.move_shape(0, g, (1000, 5000)) == 1000
    assert live.move_shape(0x80000000, g, (1000, 5000)) == 3000
    assert live.move_shape(0xFFFFFFFF, g, (1000, 5000)) in (4999, 5000)
    assert live.move_shape(0x80000000, g, (5000, 1000)) == 3000
    ys = [live.move_shape(p << 24, g, (0, 0xFFFF)) for p in range(256)]
    assert all(b >= a for a, b in zip(ys, ys[1:]))
    assert ys[1] - ys[0] < ys[128] - ys[127]                     # slow at the ends


def test_the_random_generator_does_not_repeat_soon():
    x, seen = 0, set()
    for _ in range(100_000):
        x = live.rnd_next(x)
        assert x not in seen
        seen.add(x)


def test_trig_restarts_only_when_on():
    p = 0x12345678
    assert live.move_step(p, 0, 0x0700, live.TRIG_RESTART, True) == live.MOVE_RATE[0]
    assert live.move_step(p, 0, 0x0700, 0x100, True) == p + live.MOVE_RATE[0]    # TRIG 1: free
    assert live.move_step(p, 0, 0x0700, live.TRIG_RESTART, False) == p + live.MOVE_RATE[0]


def test_mpos_and_mlev_full_depth():
    assert live.move_apply(0, 0x6400, 0x6400, 0, 0xFFFF)[0] in (0x77FF, 0x7800)  # +50 at the top: the far end
    assert live.move_apply(0x100, 0x6400, 0, 0, 0xFFFF)[0] == 0               # never below 0
    assert live.move_apply(0, 0x6400, live.MPOS_NONE, 0x7F00, 0)[1] == 0      # MLEV 127 at shape 0: silent


def test_prst_on_restarts_the_oscillator_on_a_note():
    tables = dsp.tables()
    o1 = (0x3C00, 0, 0x4000, 0x6400, 0x3200, live.MPOS_NONE, 0, 0)
    off = (0, 0, 0x4000, 0, 0x3200, live.MPOS_NONE, 0, 0)
    note = lambda trig, prst: (60.0, o1, off, (live.TRIG_RESTART, trig, prst))
    fresh = live.render_two(tables, [note(False, live.PRST_ON)], 32)
    # three blocks, then a note with PRST On: that block is the first block again
    seq = [note(False, live.PRST_ON)] * 3 + [note(True, live.PRST_ON)]
    assert live.render_two(tables, seq, 32)[-32:] == fresh
    seq_off = [note(False, live.PRST_OFF)] * 3 + [note(True, live.PRST_OFF)]
    assert live.render_two(tables, seq_off, 32)[-32:] != fresh


def _code(name: str) -> tuple[bytes, list[int], list[str]]:
    """An assembled object's big-endian parcels, its instruction offsets and its
    instructions, in source order."""
    spec = json.loads((SHARC / f"{name}.json").read_text(encoding="utf-8"))
    src = [ln.split("//", 1)[0].strip() for ln in (SHARC / f"{name}.asm").read_text().splitlines()]
    src = [c for c in src if c and not c.startswith(".") and not c.endswith(":")]
    return bytes.fromhex(spec["object_parcels_be"]), spec["instruction_offsets"], src


def test_prst_moved_to_the_idle_span_and_returns_into_the_loop():
    """M10b-3: wr_mod_b ends by jumping to wr_prst in idle_load.asm's span (the reply
    report took PRST's room in the reader span); wr_prst's exits go to wr_t5v_modded,
    and idle_load still fits its span with the build's 64 B of padding."""
    be, offs, src = _code("idle_load")
    start = src.index("R6 = PASS R6;")                       # wr_prst's first instruction
    prst_sw = dsp.IDLE_SW + offs[start] // 2
    rbe, roffs, rsrc = _code("reader_m9")
    jump = rsrc.index(f"JUMP {prst_sw:#x};")
    assert rbe[roffs[jump]:roffs[jump] + 6].hex() == f"063e00{prst_sw:06x}"
    assert be[offs[-1]:offs[-1] + 6].hex() == "063e0016edf3"   # -> wr_t5v_modded
    assert dsp.IDLE_DM + len(be) + 64 <= dsp.COUNT_DM
    assert dsp.READER_DM + len(rbe) + 64 <= dsp.LOOP_DM


def test_the_report_writes_the_live_reply_tail():
    """M10b-3: the shape's high byte goes to byte 2t + osc of the reply's tail
    (0x2c49d0 + 0xa9c), in the page DM 0x2c0450 selects."""
    _, _, src = _code("reader_m9")
    assert "R10 = DM(0x2c0450);" in src and "R12 = 0x2c546c;" in src
    assert 0x2C49D0 + 0xA9C == 0x2C546C
    assert "DM(0, I0) = R8;" in src
    assert not any("XOR" in c or "NOT " in c for c in src)


def test_the_boot_stream_stays_under_the_coldfire_loaders_1_mib(built):
    assert len(built) <= dsp.STREAM_LIMIT
    print(f"section 7: {len(built):,} B, {dsp.STREAM_LIMIT - len(built):,} B of headroom")


def test_only_load_asm_writes_the_answer_word():
    # load.asm answers in reply word 6 (both pages). idle_load.asm's timing totals in
    # words 3 and 4 overwrote the answers there on the instrument (2026-10-05), which no
    # runner gate saw: the runner never runs the idle task. So no other source of ours
    # may store to word 6, and load.asm stores nowhere else in the reply's first words.
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent / "csrc" / "waverider" / "sharc"
    store = re.compile(r"DM\((0x2c[45]9[0-9a-f]{2})\)\s*=", re.I)
    writers = {}
    for src in root.glob("*.asm"):
        for line in src.read_text(encoding="utf-8").splitlines():
            m = store.search(line.split("//", 1)[0])
            if m:
                writers.setdefault(int(m.group(1), 16) & 0xFFF, set()).add(src.stem)
    assert writers.get(0x9E8) == {"load"}, writers.get(0x9E8)
    assert all("load" not in names for off, names in writers.items() if off != 0x9E8 and off < 0x9EC)
