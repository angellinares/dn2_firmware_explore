"""The arpscale mod: it applies to stock 1.11, refuses anything else, writes only
its hooks in the image, and runs from one platform CODE chunk at 0x467a8000.

`scripts/gen_arpscale_code.py` composes the SPEC from `scripts/build_arpscale.compose`
and refuses to write it unless replaying it on stock gives the compose output byte
for byte. The behaviour is the emulator's (`scripts/emu_arpscale.py`): stock and the
mod playing a chord through the arp with the same offsets, against the rule.
"""

import pathlib
import struct

import pytest

from dnfw.mods import ModError, arpscale, check_compatible, platform
from dnfw.patch import area

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BASE = arpscale.BASE
ARP_SITE, MENU_SITE = 0x4002A390, 0x40098630
LOAD_SITE, SAVE_SITE = 0x400DD5A0, 0x400DD8C8
STEP_EXIT = 0x4002A39C


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(arpscale.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(dn2_111):
    return arpscale.apply(dn2_111).payloads[arpscale.SECTION]


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
    allowed = [(e.start, e.end) for e in arpscale.extents()]
    stray = [i for i in range(len(stock))
             if stock[i] != applied[i] and not any(lo <= i < hi for lo, hi in allowed)]
    assert stray == []
    assert len(arpscale.SPEC["edits"]) == 12


def test_the_code_is_one_platform_chunk_at_its_address(applied):
    _, chunks = platform.split(applied)
    (code,) = [area.CodeChunk.unpack(d) for cid, d in chunks if cid == area.CODE]
    assert code.load == arpscale.CODE_VA == 0x467A8000
    assert code.image == arpscale.BLOB
    assert platform.installed(applied)


def test_the_arp_hook_keeps_the_stock_sum_on_its_stock_path(stock, applied):
    """`add.l %d1,%d0; add.l %d2,%d0; bra 0x4002a39c` -> `jmp arp`; the chunk's
    stock path adds the octave and the semitone offset and leaves the same way."""
    assert at(stock, ARP_SITE, 6) == bytes.fromhex("d081d0826006")
    assert at(applied, ARP_SITE, 6) == jmp(arpscale.SPEC["labels"]["arp"])
    assert bytes.fromhex("d081d082") + jmp(STEP_EXIT) in arpscale.BLOB


def test_the_menu_hook_replays_the_displaced_destructor_calls(stock, applied):
    assert at(stock, MENU_SITE, 6) == bytes.fromhex("4e932f034e93")
    assert at(applied, MENU_SITE, 6) == jmp(arpscale.SPEC["labels"]["menu_hook"])
    assert bytes.fromhex("4e932f034e93") in arpscale.BLOB
    assert jmp(MENU_SITE + 6) in arpscale.BLOB


def test_the_store_hooks_still_copy_the_step_mask(stock, applied):
    """The stored sound's load and save each give up the copy of the step mask to
    their jmp; the chunk replays it before the marks and returns after it"""
    labels = arpscale.SPEC["labels"]
    for site, mask_copy, label in ((LOAD_SITE, "356b01500164", "load_marks"),
                                   (SAVE_SITE, "356b01640150", "save_marks")):
        assert at(stock, site, 6) == bytes.fromhex(mask_copy)
        assert at(applied, site, 6) == jmp(labels[label])
        assert bytes.fromhex(mask_copy) in arpscale.BLOB
        assert jmp(site + 6) in arpscale.BLOB


def test_the_toggle_is_read_and_written_as_one_byte_of_the_settings_block():
    assert bytes.fromhex("71b9") + struct.pack(">I", arpscale.FLAG) in arpscale.BLOB   # mvz.b FLAG
    assert bytes.fromhex("4879") + struct.pack(">I", arpscale.FLAG) in arpscale.BLOB   # pea FLAG
    assert bytes.fromhex("4eb9400bb4f8") in arpscale.BLOB                               # the writer
    assert b"ARP OFS IN SCALE\0" in arpscale.BLOB


def test_ram_is_its_own():
    from dnfw.cli.mods import REGISTRY
    mine = arpscale.ram()
    for mid, mod in REGISTRY.items():
        if mod is arpscale:
            continue
        for x in list(getattr(mod, "ram", list)()) + list(platform.ram()):
            assert not any(x.overlaps(m) for m in mine), (mid, hex(x.start))


def test_nothing_it_names_above_bss_is_undeclared(stock, applied):
    from dnfw.mods import ramcheck
    assert ramcheck.undeclared(stock, applied, arpscale.ram(),
                               getattr(arpscale, "NOT_RAM", ())) == []


def test_refuses_a_changed_image(stock):
    content = bytearray(stock)
    content[arpscale.SPEC["edits"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        arpscale.apply(stub(content))


def test_refuses_an_image_whose_guards_moved(stock):
    content = bytearray(stock)
    content[arpscale.SPEC["guards"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        arpscale.apply(stub(content))


def test_byte_disjoint_from_every_other_mod(dn2_111):
    from dnfw.cli.mods import REGISTRY
    for mid, mod in REGISTRY.items():
        if mod is arpscale:
            continue
        try:
            other = mod.extents(dn2_111)
        except TypeError:
            other = mod.extents()
        assert check_compatible([(arpscale.ID, arpscale.extents()), (mid, other)]) == [], mid
