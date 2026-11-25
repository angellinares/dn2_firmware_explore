"""The parameter-slide mod: it applies to stock 1.11 (1.12 is test_pslide_112.py's), refuses a
changed image, writes only its eleven hooks and the clear mask's operand in the image, and runs
from one platform CODE chunk at 0x46c00000 with its state after it, its frame routine a handler
of the hook bus's ev_frame.

`scripts/gen_pslide_code.py` composes the SPEC from `scripts/build_pslide.compose` and refuses
to write it unless replaying it on stock gives the compose output byte for byte. What is asserted
here is that the shipped JSON still does what each edit needs. The behaviour is the emulator's.
"""

import pathlib
import struct
import sys

import pytest

from dnfw.checkout import resources_dir
from dnfw.mods import ModError, bus, check_compatible, platform, pslide, ramcheck
from dnfw.patch import area

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.11_dist.zip"
BASE = pslide.BASE
LABELS = pslide.SPEC["labels"]
BLOB = bytes.fromhex(pslide.SPEC["code"]["blob"])
# (site, the stock bytes, its label, where stock's path goes on): a jmp hook returns past the
# site; a jsr hook's routine calls or jumps to the stock routine the site called
JMP_HOOKS = ((0x400D8AE2, "274e0054200b", "h_prep", 0x400D8AE8),
             (0x40026BAC, "284220280040", "h_pre", 0x40026BB2),
             (0x40026C3E, "42b94058e550", "h_post", 0x40026C44),
             (0x40026642, "487980003af02f002f0222464e91", "h_lock", 0x40026650),
             (0x40053E1A, "71002d40ffc0", "copy_hook", 0x40053E20),
             (0x400555C2, "2f034eb94018b1c6", "paste_hook", 0x400555CA),
             (0x400550DA, "4eba99482f02", "euc_read", 0x400550E0),
             (0x4005520A, "2f032f022f0a4ebaf81a", "euc_set", 0x40055214),
             (0x4006793E, "4a83670000ee", "ui_push", 0x40067944))
JSR_HOOKS = ((0x40026C34, "4eb9400db092", "h_apply", 0x400DB092),
             (0x4006DDE6, "4eb940065a0c", "ui_draw", 0x40065A0C),
             (0x4006DF1A, "4eb940067470", "ui_knob", 0x40067470))
CLEAR_MASK = 0x4004FD36
SLD_BITS = 0x0068


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(pslide.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(dn2_111):
    return pslide.apply(dn2_111).payloads[pslide.SECTION]


def at(content: bytes, va: int, n: int) -> bytes:
    return content[va - BASE:va - BASE + n]


def call(opcode: str, target: int) -> bytes:
    return bytes.fromhex(opcode) + struct.pack(">I", target)


def stub(content):
    class Firmware:
        class container:
            @staticmethod
            def find(_):
                class Section:
                    @staticmethod
                    def unpack():
                        return bytes(content)
                return Section
    return Firmware


def test_changes_only_its_thirteen_sites(stock, applied):
    allowed = [(e.start, e.end) for e in pslide.extents()]
    stray = [i for i in range(len(stock))
             if stock[i] != applied[i] and not any(lo <= i < hi for lo, hi in allowed)]
    assert stray == []
    assert len(pslide.SPEC["edits"]) == len(JMP_HOOKS) + len(JSR_HOOKS) + 1


def test_the_code_is_one_chunk_with_its_state_and_its_frame_handler(applied):
    _, chunks = platform.split(applied)
    codes = {c.load: c for c in (area.CodeChunk.unpack(d) for cid, d in chunks if cid == area.CODE)}
    code = codes[pslide.SPEC["code"]["va"]]
    assert code.load == 0x46C00000
    assert code.image == BLOB
    assert code.bss == pslide.SPEC["code"]["bss"]
    assert bus.handlers(chunks) == {b"FRAM": [LABELS["slide_frame"]]}
    frame = bus.EVENTS[b"FRAM"]
    assert at(applied, frame["site"], 8) == (call("4ef9", platform.SPEC["bus"]["symbols"]["ev_frame"])
                                            + bytes.fromhex("4e71"))


@pytest.mark.parametrize("site, displaced, label, back", JMP_HOOKS)
def test_each_jmp_hook_goes_to_its_routine_and_back(stock, applied, site, displaced, label, back):
    """The site becomes `jmp label` (and NOPs); the chunk jumps back past the site, so stock's
    path runs on."""
    size = len(displaced) // 2
    assert at(stock, site, size).hex() == displaced
    assert at(applied, site, size) == call("4ef9", LABELS[label]) + bytes.fromhex("4e71") * ((size - 6) // 2)
    assert call("4ef9", back) in BLOB


@pytest.mark.parametrize("site, displaced, label, routine", JSR_HOOKS)
def test_each_jsr_hook_calls_its_routine_which_calls_stocks(stock, applied, site, displaced, label, routine):
    assert at(stock, site, 6).hex() == displaced
    assert at(applied, site, 6) == call("4eb9", LABELS[label])
    assert call("4ef9", routine) in BLOB or call("4eb9", routine) in BLOB


def test_clearing_a_trigs_own_settings_clears_sld(stock, applied):
    """[TRIG] + [PLAY], removal and placement clear a step's own settings with this mask
    (0x4004fd36 `andi.l #mask,%d0`): SLD's three bits go with them, the other bits as stock."""
    stock_mask = struct.unpack(">I", at(stock, CLEAR_MASK + 2, 4))[0]
    assert at(applied, CLEAR_MASK, 2) == at(stock, CLEAR_MASK, 2) == bytes.fromhex("0280")
    assert struct.unpack(">I", at(applied, CLEAR_MASK + 2, 4))[0] == stock_mask & ~SLD_BITS


def test_the_area_it_declares_is_the_area_it_writes(applied):
    assert pslide.area() == len(applied) - platform.STOCK_LENGTH


def test_ram_is_its_own():
    from dnfw.cli.mods import REGISTRY
    mine = pslide.ram()
    for mid, mod in REGISTRY.items():
        if mod is pslide:
            continue
        for x in list(getattr(mod, "ram", list)()) + list(platform.ram()):
            assert not any(x.overlaps(m) for m in mine), (mid, hex(x.start))
    assert ramcheck.in_stack_reserve(mine) == []


def test_nothing_it_names_above_bss_is_undeclared(stock, applied):
    assert ramcheck.undeclared(stock, applied, pslide.ram(), pslide.NOT_RAM) == []


def test_refuses_a_changed_image(stock):
    content = bytearray(stock)
    content[pslide.SPEC["edits"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        pslide.apply(stub(content))


def test_refuses_an_image_whose_guards_moved(stock):
    content = bytearray(stock)
    content[pslide.SPEC["guards"][0]["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError):
        pslide.apply(stub(content))


def test_byte_disjoint_from_every_other_mod(dn2_111):
    from dnfw.cli.mods import REGISTRY
    for mid, mod in REGISTRY.items():
        if mod is pslide:
            continue
        try:
            other = mod.extents(dn2_111)
        except TypeError:
            other = mod.extents()
        assert check_compatible([(pslide.ID, pslide.extents()), (mid, other)]) == [], mid


def test_the_json_reproduces_the_compose(stock):
    from dnfw.patch.assemble import available
    if not available():
        pytest.skip("no m68k assembler")
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_pslide
    built = build_pslide.compose(stock, log=lambda *_: None)
    assert built["blob"].hex() == pslide.SPEC["code"]["blob"]
    assert built["bss"] == pslide.SPEC["code"]["bss"]
    content = bytearray(stock)
    for e in pslide.SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new
    assert bytes(content) == built["content"]
