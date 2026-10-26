"""The stall probe (dnfw.waverider.stallprobe): its generator matches the committed stall.asm, its layout
fits, and what it publishes reads back."""

from __future__ import annotations

import hashlib
import json
import re
import struct

from dnfw.waverider import dsp
from dnfw.waverider import stallprobe as sp

TARGET = re.compile(r"((?:C?JUMP|CALL)\s+)0x[0-9a-fA-F]+")


def test_stall_asm_is_the_generator_output():
    committed = sp.SOURCE.read_text(encoding="utf-8")
    assert TARGET.sub(r"\g<1>0x0", committed) == TARGET.sub(r"\g<1>0x0", sp.asm())


def test_the_committed_object_is_of_this_source_and_fits():
    spec = json.loads(sp.CODE.read_text(encoding="utf-8"))["stall"]
    text = sp.SOURCE.read_bytes().replace(b"\r\n", b"\n")
    assert spec["source_sha256"] == hashlib.sha256(text).hexdigest()
    assert sp.STALL_DM + len(spec["object_parcels_be"]) // 2 <= sp.STALL_END


def test_the_state_block_layout():
    spans = sorted([(sp.SAVE_DM, sp.SAVE_DM + 4 * len(sp.REGS)), (sp.TICK_DM, sp.T0_DM + 4),
                    (sp.PARAM_DM, sp.PARAM_DM + 32), (sp.RESULTS_DM, sp.RESULTS_DM + 8 * len(sp.tests())),
                    (sp.PUBTAB_DM, sp.PUBTAB_DM + 4 * sp.MAX_PUB), (sp.SCRATCH_DM, sp.SCRATCH_DM + 12),
                    (sp.OUT_OLD_DM, sp.OUT_OLD_DM + 4 * sp.SAMPLES), (sp.OUT_NEW_DM, sp.OUT_NEW_DM + 4 * sp.SAMPLES)])
    for (_, e1), (s2, _) in zip(spans, spans[1:]):
        assert e1 <= s2
    assert spans[-1][1] <= sp.STATE_DM + sp.STATE_BYTES
    assert dsp.REGION[0] <= sp.STATE_DM and sp.STALL_END <= dsp.REGION[1]


def test_state_at_boot():
    st = sp.state()
    word = lambda at: struct.unpack_from("<I", st, at - sp.STATE_DM)[0]  # noqa: E731
    assert word(sp.NHALVES_DM) == 2 * len(sp.published())
    assert word(sp.PARAM_DM + 8) == sp.INC
    assert all(word(sp.RESULTS_DM + 8 * k) == sp.LEAST0 for k in range(len(sp.tests())))
    assert [word(sp.PUBTAB_DM + 4 * k) for k in range(len(sp.published()))] == [a for _, a in sp.published()]
    assert word(sp.SCRATCH_DM) == (-15 & 0xFFFFFFFF)


def test_rows_are_guarded():
    rows = sp.rows()
    assert len(rows) == 2 * sp.ROW_BYTES
    a = struct.unpack(f"<{sp.ROW_BYTES // 2}h", rows[:sp.ROW_BYTES])
    frame = a[1:1 + 2 ** sp.BITS]
    assert a[0] == frame[-1] and a[-2:] == frame[:2]


def test_publishing_round_trip():
    names = [n for n, _ in sp.published()]
    assert len(names) == len(set(names)) <= sp.MAX_PUB
    values = {n: (0x10001 * (k + 3)) & 0xFFFFFFFF for k, n in enumerate(names)}
    halves = {}
    for k in range(2 * len(names)):
        v = values[names[k >> 1]]
        half = (v >> 16) if k & 1 else (v & 0xFFFF)
        assert sp.decode((k + 1) << 16 | half) == (k, half)
        halves[k] = half
    assert sp.words(halves) == values


def test_report_gives_the_stall_of_one_pair():
    w = {f"{t}.least": 1000 for t in sp.tests()}
    w["ld_add.least"] = 1000 + 3 * 8 * sp.PASSES
    w["reader_old.least"], w["reader_new.least"] = 80 * sp.SAMPLES, 50 * sp.SAMPLES
    text = "\n".join(sp.report(w))
    assert "ld_add" in text and "+3.00 cycles a pair" in text
    assert "+30.0 cycles a sample" in text
