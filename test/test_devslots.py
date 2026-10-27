"""/devslots (csrc/wrstore/slotroute.c) is for diagnostic builds only (docs/for-dnx-devslots.md)."""

from dnfw.mods import waverider as W


def test_the_shipped_drive_chunk_has_no_devslots_route():
    code = bytes.fromhex(W.SPEC["drive"]["code"])
    assert b"/modinfo" in code and b"devslots" not in code
