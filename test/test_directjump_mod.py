"""The direct-jump mod: it applies to stock 1.11, refuses anything else, writes only its seven
hooks and two entries in the PTN view's vtables in the image, and runs from one platform CODE
chunk at 0x46790000.

`scripts/gen_directjump_code.py` composes the SPEC from `scripts/build_direct_jump.compose`
and refuses to write it unless replaying it on stock gives the compose output byte for byte.
What is asserted here is that the shipped JSON still does what each edit needs. The behaviour
is the emulator's (`scripts/emu_directjump.py`): the switch, the timing and the start step.
"""

import pathlib
import struct

import pytest

from dnfw.checkout import resources_dir
from dnfw.mods import ModError, directjump, platform
from dnfw.patch import area

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.11_dist.zip"
BASE = directjump.BASE
LABELS = directjump.SPEC["labels"]
# (site, the stock instructions the hook displaces, its label)
HOOKS = ((0x400FA1E0, "4fef001c2e8a", "cue_hook"),
         (0x400DA406, "123942c5a91e", "tick_hook"),
         (0x400DA45A, "737942c5aab4", "arm_hook"),
         (0x400DA6E6, "43f942c5a9c4", "switch_hook"),
         (0x400D9E10, "2a7942c5a9a0", "early_hook"),
         (0x400DA7A6, "2e3c000dbba0", "kit_hook"),
         (0x400DA7C2, "203c0001dd59", "phase_hook"))
PTN_KEYS_SLOT, PTN_KEYS = 0x402008CC, 0x400FA6BE
PTN_LEDS_SLOT, PTN_LEDS = 0x4020097C, 0x400FA6B4


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(directjump.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(dn2_111):
    return directjump.apply(dn2_111).payloads[directjump.SECTION]


def at(content: bytes, va: int, n: int) -> bytes:
    return content[va - BASE:va - BASE + n]


def jmp(target: int) -> bytes:
    return bytes.fromhex("4ef9") + struct.pack(">I", target)


def test_changes_only_its_nine_sites(stock, applied):
    allowed = [(e.start, e.end) for e in directjump.extents()]
    stray = [i for i in range(len(stock))
             if stock[i] != applied[i] and not any(lo <= i < hi for lo, hi in allowed)]
    assert stray == []
    assert len(directjump.SPEC["edits"]) == len(HOOKS) + 2


def test_the_code_is_one_platform_chunk_at_its_address(applied):
    _, chunks = platform.split(applied)
    (code,) = [area.CodeChunk.unpack(d) for cid, d in chunks if cid == area.CODE]
    assert code.load == directjump.CODE_VA == 0x46790000
    assert code.image == directjump.BLOB


@pytest.mark.parametrize("site, displaced, label", HOOKS)
def test_each_hook_replays_what_it_displaced_and_returns(stock, applied, site, displaced, label):
    """Each 6-byte site becomes `jmp label`; the chunk holds the stock instruction and a `jmp`
    back past the site, so stock's path runs on when the mod does not act."""
    assert at(stock, site, 6).hex() == displaced
    assert at(applied, site, 6) == jmp(LABELS[label])
    assert jmp(site + 6) in directjump.BLOB
    assert bytes.fromhex(displaced) in directjump.BLOB


def test_the_ptn_view_keys_go_to_the_mod_and_on_to_stock(stock, applied):
    assert at(stock, PTN_KEYS_SLOT, 4) == struct.pack(">I", PTN_KEYS)
    assert at(applied, PTN_KEYS_SLOT, 4) == struct.pack(">I", LABELS["ptn_keys"])
    assert jmp(PTN_KEYS) in directjump.BLOB


def test_the_ptn_view_leds_go_to_the_mod_and_on_to_stock(stock, applied):
    assert at(stock, PTN_LEDS_SLOT, 4) == struct.pack(">I", PTN_LEDS)
    assert at(applied, PTN_LEDS_SLOT, 4) == struct.pack(">I", LABELS["ptn_leds"])
    assert jmp(PTN_LEDS) in directjump.BLOB


def test_the_switch_is_written_through_the_settings_writer():
    assert bytes.fromhex("4879") + struct.pack(">I", directjump.FLAG) in directjump.BLOB   # pea FLAG
    assert bytes.fromhex("4eb9400bb4f8") in directjump.BLOB                               # the writer
    assert bytes.fromhex("71b9") + struct.pack(">I", directjump.FLAG) in directjump.BLOB   # mvz.b FLAG


def test_the_messages():
    for line in (b"Direct Jump ON\0", b"Direct Jump OFF\0"):
        assert line in directjump.BLOB


def test_refuses_an_image_whose_ptn_view_is_not_stock(stock):
    changed = bytearray(stock)
    changed[PTN_KEYS_SLOT - BASE + 3] ^= 0xFF

    class Firmware:
        class container:
            @staticmethod
            def find(_):
                class Section:
                    @staticmethod
                    def unpack():
                        return bytes(changed)
                return Section

    with pytest.raises(ModError, match="0x402008cc is not stock"):
        directjump.apply(Firmware)
