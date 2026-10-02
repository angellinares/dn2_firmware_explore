"""The layering-to-MIDI mod: it applies to stock 1.11, refuses anything else,
reproduces the build that passed on the instrument, and writes only its two
hooks and its cave.

`scripts/gen_layermidi_code.py` composes the SPEC from
`scripts/build_layer_midi.compose` and refuses to write it unless replaying it on
stock gives the compose output byte for byte. What is asserted here is that the
shipped JSON still does, and what each edit means. `scripts/emu_layer_midi.py`
is the behavioural evidence (the ISR's own note and release loops).
"""

import pathlib
import struct

import pytest

from dnfw.mods import ModError, check_compatible
from dnfw.mods import arpmodes, arpplocks, fxmod, layermidi, midiarp, moddest, usbprobe

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BUILT = ROOT / "out/layer-midi6/section_3_MAIN_OS.aplib.bin"
BASE = layermidi.BASE
NOTE_SITE, RELEASE_SITE = 0x40026980, 0x40026D32
CAVE = 0x402D0664


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(layermidi.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(dn2_111):
    return layermidi.apply(dn2_111).payloads[layermidi.SECTION]


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


def test_applies_every_edit(applied):
    for e in layermidi.SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        assert at(applied, e["va"], len(new)) == new, e["what"]


def test_changes_nothing_else(stock, applied):
    allowed = [(e.start, e.end) for e in layermidi.extents()]
    stray = [i for i in range(len(stock))
             if stock[i] != applied[i] and not any(lo <= i < hi for lo, hi in allowed)]
    assert stray == []
    assert len(applied) == len(stock)


def test_is_the_build_that_passed(applied):
    """Byte equality with `layer-midi6`, the image that passed on the
    instrument (2026-10-02). Skips when it is absent: `out/` is scratch."""
    if not BUILT.exists():
        pytest.skip("out/layer-midi6 is not extracted; run scripts/build_layer_midi.py")
    assert applied == BUILT.read_bytes()


def test_the_note_hook_is_a_jsr_over_one_whole_instruction(stock, applied):
    """`mvz.w 0x8000537e,%d1` (6 bytes, absolute) -> `jsr note_hook`; the cave
    runs it last and returns past it."""
    assert at(stock, NOTE_SITE, 6) == bytes.fromhex("73f98000537e")
    assert at(applied, NOTE_SITE, 6) == (bytes.fromhex("4eb9")
                                         + struct.pack(">I", layermidi.SPEC["labels"]["note_hook"]))


def test_the_release_hook_is_a_jmp_and_the_cave_jumps_back(stock, applied):
    """`mvs.b 2(%a2),%d4; move.l %d4,-(%sp)` pushes onto the ISR's stack, so
    the site is a jmp, and the cave ends with both and `jmp 0x40026d38`."""
    assert at(stock, RELEASE_SITE, 6) == bytes.fromhex("792a00022f04")
    assert at(applied, RELEASE_SITE, 6) == (bytes.fromhex("4ef9")
                                            + struct.pack(">I", layermidi.SPEC["labels"]["release_hook"]))
    tail = bytes.fromhex("792a00022f04") + bytes.fromhex("4ef9") + struct.pack(">I", RELEASE_SITE + 6)
    cave = next(bytes.fromhex(e["new"]) for e in layermidi.SPEC["edits"] if e["va"] == CAVE)
    assert tail in cave


def test_the_cave_was_free(stock):
    for e in layermidi.SPEC["edits"]:
        if e["what"] == "layer-midi code cave":
            assert at(stock, e["va"], len(e["new"]) // 2) == bytes(len(e["new"]) // 2)


def test_guards_the_pool_before_allocating():
    """The stock allocator pops without an empty check; the cave reads the
    free-list head (0x4460e4b8) itself before calling it."""
    cave = next(bytes.fromhex(e["new"]) for e in layermidi.SPEC["edits"] if e["va"] == CAVE)
    assert bytes.fromhex("20394460e4b8") in cave                 # move.l 0x4460e4b8,%d0
    assert bytes.fromhex("4eb94012a408") in cave                 # jsr the allocator


def test_refuses_a_changed_image(stock):
    content = bytearray(stock)
    content[layermidi.SPEC["edits"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        layermidi.apply(stub(content))


def test_refuses_an_image_whose_guards_moved(stock):
    content = bytearray(stock)
    content[layermidi.SPEC["guards"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        layermidi.apply(stub(content))


def test_refuses_midiarp_and_says_why(dn2_111):
    """The same cave on purpose: midiarp's voice-trigger hook would send the
    layered notes too, from the wrong fields."""
    assert check_compatible([(layermidi.ID, layermidi.extents()), (midiarp.ID, midiarp.extents())])
    with pytest.raises(ModError):
        layermidi.apply(stub(midiarp.apply(dn2_111).payloads[3]))
    from dnfw.mods.matrix import NOTES
    assert frozenset((layermidi.ID, midiarp.ID)) in NOTES


def test_byte_disjoint_from_the_other_arp_and_fx_mods(dn2_111):
    for other in (arpmodes.extents(), arpplocks.extents(), fxmod.extents(),
                  moddest.extents(dn2_111)):
        assert check_compatible([(layermidi.ID, layermidi.extents()), ("other", other)]) == []
    assert check_compatible([(layermidi.ID, layermidi.extents()), (usbprobe.ID, usbprobe.extents())])
