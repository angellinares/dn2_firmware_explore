"""The reload-confirm mod: it applies to stock 1.11, refuses anything else,
writes only its two hooks in the image, and runs from one platform CODE chunk
at 0x467e0000.

`scripts/gen_reloadconfirm_code.py` composes the SPEC from
`scripts/build_reload_confirm.compose` and refuses to write it unless replaying
it on stock gives the compose output byte for byte. What is asserted here is
that the shipped JSON still does, and what each edit means. The behaviour is the
emulator's (the build script's docstring): the prompt, NO, YES, and the stock
path with the toggle off.
"""

import pathlib
import struct

import pytest

from dnfw.mods import ModError, check_compatible, platform, reloadconfirm
from dnfw.patch import area

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BASE = reloadconfirm.BASE
KEY_SITE, MENU_SITE = 0x4005F1A2, 0x4009863E


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(reloadconfirm.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(dn2_111):
    return reloadconfirm.apply(dn2_111).payloads[reloadconfirm.SECTION]


def at(content: bytes, va: int, n: int) -> bytes:
    return content[va - BASE:va - BASE + n]


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


def _chunks(content):
    _, chunks = platform.split(content)
    return [area.CodeChunk.unpack(d) for cid, d in chunks if cid == area.CODE]


def test_changes_only_the_hooks(stock, applied):
    allowed = [(e.start, e.end) for e in reloadconfirm.extents()]
    stray = [i for i in range(len(stock))
             if stock[i] != applied[i] and not any(lo <= i < hi for lo, hi in allowed)]
    assert stray == []
    assert len(reloadconfirm.SPEC["edits"]) == 2


def test_the_code_is_one_platform_chunk_at_its_address(applied):
    (code,) = _chunks(applied)
    assert code.load == reloadconfirm.CODE_VA == 0x467E0000
    assert code.image == reloadconfirm.BLOB
    assert platform.installed(applied)


def test_the_key_hook_replays_the_stock_reload_when_off(stock, applied):
    """`move.l 160(%a2),-(%sp); jsr 0x400f6df8` (10 bytes) -> `jmp key_hook`
    and two nops; with the toggle off the chunk runs both and jumps back past them."""
    labels = reloadconfirm.SPEC["labels"]
    assert at(stock, KEY_SITE, 10) == bytes.fromhex("2f2a00a04eb9400f6df8")
    assert at(applied, KEY_SITE, 10) == (bytes.fromhex("4ef9") + struct.pack(">I", labels["key_hook"])
                                         + bytes.fromhex("4e714e71"))
    replay = bytes.fromhex("2f2a00a04eb9400f6df8") + bytes.fromhex("4ef9") + struct.pack(">I", KEY_SITE + 10)
    assert replay in reloadconfirm.BLOB
    assert bytes.fromhex("71b9") + struct.pack(">I", reloadconfirm.FLAG) in reloadconfirm.BLOB  # mvz.b FLAG


def test_the_menu_hook_ends_with_the_displaced_epilogue(stock, applied):
    labels = reloadconfirm.SPEC["labels"]
    assert at(stock, MENU_SITE, 6) == bytes.fromhex("4cef7c7c0018")
    assert at(applied, MENU_SITE, 6) == bytes.fromhex("4ef9") + struct.pack(">I", labels["menu_hook"])
    tail = bytes.fromhex("4cef7c7c0018") + bytes.fromhex("4ef9") + struct.pack(">I", MENU_SITE + 6)
    assert tail in reloadconfirm.BLOB


def test_the_yes_reload_is_the_temporary_one():
    """The answer pushes (sequencer, 1, pattern, 1, 1): the 1 FUNC + NO passes,
    not the menu RELOAD's 0 (the saved pattern)."""
    call = (bytes.fromhex("48780001" "48780001" "2f02" "48780001" "2f00")
            + bytes.fromhex("4eb9400444da"))
    assert call in reloadconfirm.BLOB


def test_the_toggle_is_written_through_the_settings_writer():
    assert bytes.fromhex("4879") + struct.pack(">I", reloadconfirm.FLAG) in reloadconfirm.BLOB
    assert bytes.fromhex("4eb9400bb4f8") in reloadconfirm.BLOB


def test_the_wording():
    for line in (b"RELOAD CONFIRM\0", b"ARE YOU SURE YOU WANT TO\0", b"RELOAD THE PATTERN? Y/N\0"):
        assert line in reloadconfirm.BLOB
    # the longest line a stock YES/NO prompt shows is 27 characters
    assert max(len("ARE YOU SURE YOU WANT TO"), len("RELOAD THE PATTERN? Y/N")) <= 27


def test_the_toggle_byte_is_not_stock_code_or_data(stock):
    """Zero in the image (BSS), and below the image's end, so not appended data."""
    assert reloadconfirm.FLAG - BASE >= len(stock) or stock[reloadconfirm.FLAG - BASE] == 0


def test_ram_is_its_own():
    from dnfw.cli.mods import REGISTRY
    mine = reloadconfirm.ram()
    for mid, mod in REGISTRY.items():
        if mod is reloadconfirm:
            continue
        for x in list(getattr(mod, "ram", list)()) + list(platform.ram()):
            assert not any(x.overlaps(m) for m in mine), (mid, hex(x.start))


def test_nothing_it_names_above_bss_is_undeclared(stock, applied):
    from dnfw.mods import ramcheck
    assert ramcheck.undeclared(stock, applied, reloadconfirm.ram(),
                               getattr(reloadconfirm, "NOT_RAM", ())) == []


def test_refuses_a_changed_image(stock):
    content = bytearray(stock)
    content[reloadconfirm.SPEC["edits"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        reloadconfirm.apply(stub(content))


def test_refuses_an_image_whose_guards_moved(stock):
    content = bytearray(stock)
    content[reloadconfirm.SPEC["guards"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        reloadconfirm.apply(stub(content))


def test_byte_disjoint_from_every_other_mod(dn2_111):
    from dnfw.cli.mods import REGISTRY
    for mid, mod in REGISTRY.items():
        if mod is reloadconfirm:
            continue
        try:
            other = mod.extents(dn2_111)
        except TypeError:
            other = mod.extents()
        assert check_compatible([(reloadconfirm.ID, reloadconfirm.extents()), (mid, other)]) == [], mid
