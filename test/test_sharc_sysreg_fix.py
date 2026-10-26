"""scripts/sharc_waverider_m3.fix_sysreg_read: selas's 48-bit `Rn = <system register>` carries the wrong
source code; the fix writes the PRM's (stock DN2 1.11 and DT2 1.16 code agree, 2026-10-25)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import pytest  # noqa: E402

import sharc_waverider_m3 as m3  # noqa: E402


@pytest.mark.parametrize("selas, text, fixed", [
    ("76be00000000", "R0 = EMUCLK;", "76be80000000"),     # selas's EMUCLK is the decoder's LCNTR
    ("76be82800000", "R5 = EMUCLK2;", "76bf02800000"),    # its EMUCLK2 is EMUCLK
    ("767f80000000", "R0 = LCNTR;", "76be00000000"),      # its LCNTR is CURLCNTR
    ("773e00000000", "R0 = MODE1;", "773f00000000"),      # its MODE1 is USTAT1; stock's R1 = MODE1 is 773f00
    ("76fe80000000", "R0 = PX1;", "76fe00000000"),        # stock's R0 = PX1 (sw 0x1c0f18)
])
def test_the_source_field_gets_the_prm_code(selas, text, fixed):
    assert m3.fix_sysreg_read(bytes.fromhex(selas), [0], [text]).hex() == fixed


def test_compressed_forms_and_other_lines_are_left():
    be = bytes.fromhex("76be803f") + bytes.fromhex("51be02000000")
    assert m3.fix_sysreg_read(be, [0, 4], ["R0 = EMUCLK;", "R4 = DM(I0, M6) (SWSE);"]) == be


def test_unchecked_moves_and_unexpected_words_are_refused():
    with pytest.raises(SystemExit):
        m3.fix_sysreg_read(bytes(6), [0], ["MODE1 = R0;"])               # a write: not checked
    with pytest.raises(SystemExit):
        m3.fix_sysreg_read(bytes.fromhex("76be00000000"), [0], ["R3 = EMUCLK;"])   # dest isn't R3
    with pytest.raises(SystemExit):
        m3.fix_sysreg_read(bytes.fromhex("51be02000000"), [0], ["R0 = EMUCLK;"])   # not Type 5a
