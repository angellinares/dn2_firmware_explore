"""The degreetranspose mod: it applies to stock 1.11, refuses anything else, writes only
its hooks and two widened masks in the image, and runs from one platform CODE chunk at 0x467b8000.

`scripts/gen_degreetranspose_code.py` composes the SPEC from
`scripts/build_degreetranspose.compose` and refuses to write it unless replaying it on
stock gives the compose output byte for byte. The behaviour is the emulator's
(`scripts/emu_degreetranspose.py`): the mod's keys pressed on the panel, and the notes
played against stock and the rule.
"""

import pathlib
import struct

import pytest

from dnfw.mods import ModError, check_compatible, degreetranspose, platform
from dnfw.patch import area

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BASE = degreetranspose.BASE
VOICE_SITE, VOICE_BACK = 0x400269A4, 0x400269AA
KEY_SITE, KEY_BACK, KEY_DONE = 0x4005FB76, 0x4005FB7C, 0x4005FC24
RELEASE_SITE, RELEASE_BACK = 0x4005ED2C, 0x4005ED32
DRAW_SITE, DRAW_DONE = 0x4005CA66, 0x4005CB4A
BLINK_SITE, BLINK_FLIP, BLINK_REDRAW, BLINK_LEAVE = 0x4005BEB6, 0x4005BEC2, 0x4005BED0, 0x4005BEE0


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(degreetranspose.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(dn2_111):
    return degreetranspose.apply(dn2_111).payloads[degreetranspose.SECTION]


def at(content: bytes, va: int, n: int) -> bytes:
    return content[va - BASE:va - BASE + n]


def jmp(va: int) -> bytes:
    return bytes.fromhex("4ef9") + struct.pack(">I", va)


def stub(content: bytes):
    class Stub:
        class container:
            @staticmethod
            def find(_):
                class S:
                    @staticmethod
                    def unpack():
                        return bytes(content)
                return S
    return Stub


def test_changes_only_the_hooks(stock, applied):
    allowed = [(e.start, e.end) for e in degreetranspose.extents()]
    stray = [i for i in range(len(stock))
             if stock[i] != applied[i] and not any(lo <= i < hi for lo, hi in allowed)]
    assert stray == []
    assert len(degreetranspose.SPEC["edits"]) == 13


def test_the_code_is_one_platform_chunk_at_its_address(applied):
    _, chunks = platform.split(applied)
    (code,) = [area.CodeChunk.unpack(d) for cid, d in chunks if cid == area.CODE]
    assert code.load == degreetranspose.CODE_VA == 0x467B8000
    assert code.image == degreetranspose.BLOB
    assert platform.installed(applied)


def test_the_note_hook_replays_the_range_check_and_returns_to_its_branch(stock, applied):
    """`moveq #127,%d1; and.l %d2,%d1; cmp.l %d1,%d2` -> `jmp voice`; the chunk replays
    them and jumps to the `bne.w` that skips a note out of 0..127."""
    assert at(stock, VOICE_SITE, 6) == bytes.fromhex("727fc282b481")
    assert at(applied, VOICE_SITE, 6) == jmp(degreetranspose.SPEC["labels"]["voice"])
    assert bytes.fromhex("727fc282b481") + jmp(VOICE_BACK) in degreetranspose.BLOB


def test_the_key_hook_returns_to_stock_or_to_stocks_redraw(stock, applied):
    assert at(stock, KEY_SITE, 6) == bytes.fromhex("49f94011f7e4")
    assert at(applied, KEY_SITE, 6) == jmp(degreetranspose.SPEC["labels"]["keys"])
    assert bytes.fromhex("49f94011f7e4") in degreetranspose.BLOB
    assert jmp(KEY_BACK) in degreetranspose.BLOB
    assert jmp(KEY_DONE) in degreetranspose.BLOB


def test_the_release_hook_replays_the_handlers_head_and_returns_to_its_switch(stock, applied):
    """`addq.l #4,%sp; move.l %d0,%d4; moveq #53,%d0` -> `jmp release`; the chunk ends
    with `moveq #53,%d0` and goes back to the switch on the key code."""
    assert at(stock, RELEASE_SITE, 6) == bytes.fromhex("588f28007035")
    assert at(applied, RELEASE_SITE, 6) == jmp(degreetranspose.SPEC["labels"]["release"])
    assert bytes.fromhex("7035") + jmp(RELEASE_BACK) in degreetranspose.BLOB


def test_the_draw_hook_replays_the_track_object_call_and_leaves_through_the_epilogue(stock, applied):
    """`move.l 152(%a2),-(%sp); jsr 0x4003efde` -> `jmp draw; nop; nop`, after stock has
    drawn the pattern's transpose; the chunk makes the same call and ends at the epilogue."""
    assert at(stock, DRAW_SITE, 10) == bytes.fromhex("2f2a00984eb94003efde")
    assert at(applied, DRAW_SITE, 10) == jmp(degreetranspose.SPEC["labels"]["draw"]) + bytes.fromhex("4e714e71")
    assert bytes.fromhex("2f2a00984eb94003efde") in degreetranspose.BLOB
    assert jmp(DRAW_DONE) in degreetranspose.BLOB


def test_the_blink_hook_returns_to_stocks_flip_redraw_or_return(stock, applied):
    assert at(stock, BLINK_SITE, 6) == bytes.fromhex("4a2802206606")
    assert at(applied, BLINK_SITE, 6) == jmp(degreetranspose.SPEC["labels"]["blink"])
    for target in (BLINK_FLIP, BLINK_REDRAW, BLINK_LEAVE):
        assert jmp(target) in degreetranspose.BLOB


def test_ram_is_its_own():
    from dnfw.cli.mods import REGISTRY
    mine = degreetranspose.ram()
    for mid, mod in REGISTRY.items():
        if mod is degreetranspose:
            continue
        for x in list(getattr(mod, "ram", list)()) + list(platform.ram()):
            assert not any(x.overlaps(m) for m in mine), (mid, hex(x.start))


def test_nothing_it_names_above_bss_is_undeclared(stock, applied):
    from dnfw.mods import ramcheck
    assert ramcheck.undeclared(stock, applied, degreetranspose.ram(),
                               getattr(degreetranspose, "NOT_RAM", ())) == []


def test_refuses_a_changed_image(stock):
    content = bytearray(stock)
    content[degreetranspose.SPEC["edits"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        degreetranspose.apply(stub(content))


def test_refuses_an_image_whose_guards_moved(stock):
    content = bytearray(stock)
    content[degreetranspose.SPEC["guards"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        degreetranspose.apply(stub(content))


def test_byte_disjoint_from_every_other_mod(dn2_111):
    from dnfw.cli.mods import REGISTRY
    for mid, mod in REGISTRY.items():
        if mod is degreetranspose:
            continue
        try:
            other = mod.extents(dn2_111)
        except TypeError:
            other = mod.extents()
        assert check_compatible([(degreetranspose.ID, degreetranspose.extents()), (mid, other)]) == [], mid
