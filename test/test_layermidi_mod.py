"""The layering-to-MIDI mod: it applies to stock 1.11, refuses anything else,
writes only its two hooks in the image, and runs from one platform CODE chunk
at 0x467d8000 (since 2026-10-03; layer-midi1..6 used a cave, which stays stock).

`scripts/gen_layermidi_code.py` composes the SPEC from
`scripts/build_layer_midi.compose` and refuses to write it unless replaying it on
stock gives the compose output byte for byte. What is asserted here is that the
shipped JSON still does, and what each edit means. `scripts/emu_layer_midi.py`
is the behavioural evidence (the ISR's own note and release loops).
"""

import pathlib
import struct

import pytest

from dnfw.mods import ModError, check_compatible, platform
from dnfw.mods import arpmodes, arpplocks, fxmod, layermidi, midiarp, moddest, usbprobe
from dnfw.patch import area

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BUILT = ROOT / "out/layer-midi7/section_3_MAIN_OS.aplib.bin"
BASE = layermidi.BASE
NOTE_SITE, RELEASE_SITE = 0x40026980, 0x40026D32
OLD_CAVE = (0x402D0664, 324)               # layer-midi1..6's cave, before the platform


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


def _chunks(content):
    _, chunks = platform.split(content)
    return [area.CodeChunk.unpack(d) for cid, d in chunks if cid == area.CODE]


def test_changes_nothing_else(stock, applied):
    """In the stock span only the hooks and the platform's loader; past it, the area."""
    allowed = [(e.start, e.end) for e in layermidi.extents()]
    stray = [i for i in range(len(stock))
             if stock[i] != applied[i] and not any(lo <= i < hi for lo, hi in allowed)]
    assert stray == []
    assert len(applied) > len(stock)


def test_the_code_is_one_platform_chunk_at_its_address(applied):
    (code,) = _chunks(applied)
    assert code.load == layermidi.CODE_VA == 0x467D8000
    assert code.image == layermidi.BLOB
    assert platform.installed(applied)


def test_the_cave_stays_stock(stock, applied):
    va, n = OLD_CAVE
    assert at(applied, va, n) == at(stock, va, n)
    assert not any(e.section == layermidi.SECTION and e.start < va - BASE + n and va - BASE < e.end
                   for e in layermidi.extents())


def test_is_the_build_script_output(applied):
    """Byte equality with `scripts/build_layer_midi.py`'s layer-midi7. Skips
    when it is absent: `out/` is scratch."""
    if not BUILT.exists():
        pytest.skip("out/layer-midi7 is not extracted; run scripts/build_layer_midi.py")
    assert applied == BUILT.read_bytes()


def test_ram_is_its_own():
    from dnfw.cli.mods import REGISTRY
    mine = layermidi.ram()
    assert [(x.start, x.end) for x in mine] == [(0x467D8000, 0x467D8000 + len(layermidi.BLOB))]
    for mid, mod in REGISTRY.items():
        if mod is layermidi:
            continue
        for x in list(getattr(mod, "ram", list)()) + list(platform.ram()):
            assert not any(x.overlaps(m) for m in mine), (mid, hex(x.start))


def test_nothing_it_names_above_bss_is_undeclared(stock, applied):
    from dnfw.mods import ramcheck
    assert ramcheck.undeclared(stock, applied, layermidi.ram(), getattr(layermidi, "NOT_RAM", ())) == []


def test_the_hooks_land_in_the_chunk():
    lo, hi = layermidi.CODE_VA, layermidi.CODE_VA + len(layermidi.BLOB)
    assert layermidi.SPEC["labels"] == layermidi.SPEC["code"]["labels"]
    assert all(lo <= va < hi for va in layermidi.SPEC["labels"].values())


def test_the_note_hook_is_a_jsr_over_one_whole_instruction(stock, applied):
    """`mvz.w 0x8000537e,%d1` (6 bytes, absolute) -> `jsr note_hook`; the chunk
    runs it last and returns past it."""
    assert at(stock, NOTE_SITE, 6) == bytes.fromhex("73f98000537e")
    assert at(applied, NOTE_SITE, 6) == (bytes.fromhex("4eb9")
                                         + struct.pack(">I", layermidi.SPEC["labels"]["note_hook"]))


def test_the_release_hook_is_a_jmp_and_the_cave_jumps_back(stock, applied):
    """`mvs.b 2(%a2),%d4; move.l %d4,-(%sp)` pushes onto the ISR's stack, so
    the site is a jmp, and the chunk ends with both and `jmp 0x40026d38`."""
    assert at(stock, RELEASE_SITE, 6) == bytes.fromhex("792a00022f04")
    assert at(applied, RELEASE_SITE, 6) == (bytes.fromhex("4ef9")
                                            + struct.pack(">I", layermidi.SPEC["labels"]["release_hook"]))
    tail = bytes.fromhex("792a00022f04") + bytes.fromhex("4ef9") + struct.pack(">I", RELEASE_SITE + 6)
    assert tail in layermidi.BLOB


def test_guards_the_pool_before_allocating():
    """The stock allocator pops without an empty check; the code reads the
    free-list head (0x4460e4b8) itself before calling it."""
    assert bytes.fromhex("20394460e4b8") in layermidi.BLOB       # move.l 0x4460e4b8,%d0
    assert bytes.fromhex("4eb94012a408") in layermidi.BLOB       # jsr the allocator


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


def test_refuses_midiarp_by_hand_and_says_why(dn2_111):
    """Disjoint bytes now, but both turn layered copies on MIDI tracks into MIDI:
    refused by hand (`matrix.REFUSED`) until the maintainer re-checks the pair."""
    from dnfw.cli.mods import _staged
    from dnfw.mods import matrix
    assert check_compatible([(layermidi.ID, layermidi.extents()), (midiarp.ID, midiarp.extents())]) == []
    assert frozenset((layermidi.ID, midiarp.ID)) in matrix.NOTES
    assert matrix.refused_by_hand([midiarp.ID, layermidi.ID]) == [(layermidi.ID, midiarp.ID)]
    registry = {layermidi.ID: layermidi, midiarp.ID: midiarp}
    (pair,) = matrix.pairs(dn2_111, registry, lambda mod, f: mod.apply(f), _staged)
    assert not pair.combines and matrix.cell(pair) == "NO"


def test_combines_with_usbprobe_in_either_order(dn2_111):
    """It used to refuse the pair: the cave was usbprobe's too."""
    from dnfw.cli.mods import _staged
    from dnfw.mods import matrix
    registry = {layermidi.ID: layermidi, usbprobe.ID: usbprobe}
    (pair,) = matrix.pairs(dn2_111, registry, lambda mod, f: mod.apply(f), _staged)
    assert pair.combines and not pair.order_only and not pair.overlaps, pair.reason()
    for first, second in ((layermidi, usbprobe), (usbprobe, layermidi)):
        both = second.apply(_staged(dn2_111, {3: first.apply(dn2_111).payloads[3]})).payloads[3]
        assert platform.installed(both)
        assert all(at(both, e["va"], len(e["new"]) // 2) == bytes.fromhex(e["new"])
                   for e in layermidi.SPEC["edits"])
        assert layermidi.CODE_VA in [c.load for c in _chunks(both)]


def test_byte_disjoint_from_the_other_arp_and_fx_mods(dn2_111):
    for other in (arpmodes.extents(), arpplocks.extents(), fxmod.extents(),
                  moddest.extents(dn2_111), midiarp.extents(), usbprobe.extents()):
        assert check_compatible([(layermidi.ID, layermidi.extents()), ("other", other)]) == []
