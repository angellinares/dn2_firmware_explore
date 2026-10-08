"""scripts/sharc_waverider_m3.fix_subword: selas drops (SWSE) on an indexed load and emits
Type 3a; the fix re-encodes it as Type 3d with the width bits (PRM 14-19, 14-22)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import pytest  # noqa: E402

import sharc_waverider_m3 as m3  # noqa: E402


def test_swse_load_becomes_type_3d():
    # selas's `R4 = DM(I0, M6) (SWSE)`: Type 3a, u=1 i=0 m=6 cond=31 ureg=4, no compute
    be = bytes.fromhex("51be02000000")
    out = m3.fix_subword(be, [0], ["R4 = DM(I0, M6) (SWSE);"])
    assert out.hex() == "51be42310000"
    w = int.from_bytes(out, "big")
    assert w >> 45 == 0b010 and (w >> 19) & 0xF == 0b0110          # Type 3d's fixed bits
    assert ((w >> 30) & 1, (w >> 16) & 1, (w >> 17) & 1) == (1, 1, 0)  # l, x, w: (swse)
    assert (w >> 23) & 0x7F == 4 and (w >> 41) & 7 == 0 and (w >> 38) & 7 == 6


def test_other_lines_and_wrong_input_are_left_or_refused():
    be = bytes.fromhex("51be02000000")
    assert m3.fix_subword(be, [0], ["R4 = DM(I0, M6);"]) == be
    with pytest.raises(SystemExit):
        m3.fix_subword(be, [0], ["R5 = DM(I0, M6) (SWSE);"])        # fields aren't this load's
