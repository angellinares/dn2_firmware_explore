"""/devslots (csrc/wrstore/slotroute.c) is for diagnostic builds only (docs/for-dnx-devslots.md)."""

from dnfw.mods import waverider as W


def test_the_shipped_drive_chunk_has_no_devslots_route():
    code = bytes.fromhex(W.SPEC["drive"]["code"])
    assert b"/modinfo" in code and b"devslots" not in code


def test_the_full_state_blocks_cover_the_saved_state_exactly():
    """slotroute.c: 197 blocks of 64 KiB, the last partial, cover 0x405cd85c..0x41218970."""
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parent.parent / "csrc/wrstore/slotroute.c").read_text(encoding="utf-8")
    num = lambda name: int(re.search(rf"#define {name}\s+(0x[0-9A-Fa-f]+|\d+)u", src).group(1), 0)
    full, block, blocks = num("FULL_BYTES"), num("BLOCK"), num("BLOCKS")
    assert full == 0x41218970 - 0x405CD85C
    assert (blocks - 1) * block < full <= blocks * block
    assert num("BLOCK_BASE") + 2 * 256 + blocks - 1 < num("BLOCK_BASE") + 3 * 256
