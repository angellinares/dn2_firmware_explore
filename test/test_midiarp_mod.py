"""The MIDI arpeggiator mod: the platform move, the layered-copy gate and the pool guard.

The behaviour of the hook is `scripts/emu_midiarp_layered.py`'s (the ISR's own call
into it, before and after, with controls); the last test here runs it when digikit's
emulator is reachable. What this file holds is what needs no emulator: the mod applies
and refuses as a platform mod, its RAM is its own, it combines with usbprobe, and the
hook's code has the two guards the emulator showed it needs.
"""

import pathlib
import shutil
import subprocess

import pytest

from dnfw.mods import ModError, RAM, check_compatible, midiarp, platform, usbprobe
from dnfw.patch import area

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BASE = midiarp.BASE
OLD_CAVE = (0x402D0664, 526)               # arp-midi-play4's cave, before the platform
ALLOC, FREE_LIST = 0x4012A408, 0x4460E4B8


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def applied(dn2_111):
    return midiarp.apply(dn2_111).payloads[midiarp.SECTION]


def _chunk(content):
    _, chunks = platform.split(content)
    return [area.CodeChunk.unpack(d) for cid, d in chunks if cid == area.CODE]


def test_applies_every_edit(applied):
    for e in midiarp.SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        at = e["va"] - BASE
        assert applied[at:at + len(new)] == new


def test_the_code_is_one_platform_chunk_at_its_address(applied):
    (code,) = _chunk(applied)
    assert code.load == midiarp.CODE_VA == 0x467D0000
    assert platform.installed(applied)


def test_the_cave_stays_stock(dn2_111, applied):
    """The 526-byte cave it used to fill is usbprobe's too: it is stock now."""
    stock = dn2_111.container.find(midiarp.SECTION).unpack()
    va, n = OLD_CAVE
    assert applied[va - BASE:va - BASE + n] == stock[va - BASE:va - BASE + n]
    assert not any(e.section == midiarp.SECTION and e.start < va - BASE + n and va - BASE < e.end
                   for e in midiarp.extents())


def test_the_length_lookup_is_rebuilt_from_the_image_not_shipped(dn2_111, applied):
    """No Elektron table bytes ship: the shipped blob has the 128 bytes blank, the
    applied chunk has what this image's own two length tables give."""
    stock = dn2_111.container.find(midiarp.SECTION).unpack()
    at = midiarp.SPEC["lut_va"] - midiarp.CODE_VA
    assert midiarp.BLOB[at:at + 128] == bytes(128)
    (code,) = _chunk(applied)
    assert code.image[at:at + 128] == midiarp.nlen_lut(stock)
    assert code.image[at:at + 128] != bytes(128)
    assert code.image[:at] == midiarp.BLOB[:at] and code.image[at + 128:] == midiarp.BLOB[at + 128:]


def test_refuses_a_changed_image(dn2_111):
    content = bytearray(dn2_111.container.find(midiarp.SECTION).unpack())
    content[midiarp.SPEC["edits"][0]["va"] - BASE] ^= 0xFF

    class Stub:
        class container:
            @staticmethod
            def find(_):
                class S:
                    @staticmethod
                    def unpack():
                        return bytes(content)
                return S
    with pytest.raises(ModError):
        midiarp.apply(Stub)


def test_ram_is_its_own():
    """0x467d0000.. is past arpplocks' code (0x467c8000, 1,944 B) and below the
    harnesses' scratch; no other mod's declared RAM touches it."""
    from dnfw.cli.mods import REGISTRY
    mine = midiarp.ram()
    assert [(x.start, x.end) for x in mine] == [(0x467D0000, 0x467D0000 + len(midiarp.BLOB))]
    for mid, mod in REGISTRY.items():
        if mod is midiarp:
            continue
        theirs = [x for x in getattr(mod, "ram", list)()] + [x for x in platform.ram()]
        for x in theirs:
            assert not any(x.overlaps(m) for m in mine), (mid, hex(x.start))
    arp = REGISTRY["arpplocks"]
    assert max(x.end for x in arp.ram() if x.section == RAM) <= mine[0].start


def test_nothing_it_names_above_bss_is_undeclared(dn2_111, applied):
    from dnfw.mods import ramcheck
    stock = dn2_111.container.find(midiarp.SECTION).unpack()
    assert ramcheck.undeclared(stock, applied, midiarp.ram(), getattr(midiarp, "NOT_RAM", ())) == []


def test_combines_with_usbprobe_in_either_order(dn2_111):
    """It used to refuse the pair: its cave was the one usbprobe's routines run from."""
    from dnfw.cli.mods import _staged
    from dnfw.mods import matrix
    registry = {midiarp.ID: midiarp, usbprobe.ID: usbprobe}
    (pair,) = matrix.pairs(dn2_111, registry, lambda mod, f: mod.apply(f), _staged)
    assert pair.combines and not pair.order_only and not pair.overlaps, pair.reason()
    for first, second in ((midiarp, usbprobe), (usbprobe, midiarp)):
        one = first.apply(dn2_111).payloads[3]
        both = second.apply(_staged(dn2_111, {3: one})).payloads[3]
        assert platform.installed(both)
        assert all(both[e["va"] - BASE:e["va"] - BASE + len(e["new"]) // 2] == bytes.fromhex(e["new"])
                   for e in midiarp.SPEC["edits"])
        assert [c.load for c in _chunk(both)] == [midiarp.CODE_VA]


def test_declared_bytes_are_disjoint_from_every_other_mod(dn2_111):
    from dnfw.cli.mods import REGISTRY, _apply_default
    named = [(mid, list(mod.extents(dn2_111)) + list(getattr(mod, "ram", list)()))
             for mid, mod in REGISTRY.items() if mid in (midiarp.ID, "usbprobe", "arpplocks", "arpmodes",
                                                         "lfowaves", "bootscreen", "fxmod", "moddest",
                                                         "layermidi")]
    bad = [c for c in check_compatible(named) if "midiarp" in c]
    assert bad == []


# -- the hook's code, read from the blob ---------------------------------------------

def _hook():
    """The voice-trigger hook's instructions, from its first test of the MIDI mask to its `rts`."""
    from dnfw.image import objdump
    tool = objdump.find_tool()
    if tool is None:
        pytest.skip("no m68k objdump on PATH")
    listing = objdump.disassemble(midiarp.BLOB, midiarp.CODE_VA, tool)
    start = next(i for i, ins in enumerate(listing) if ins.text == "mvsw 0x8000537c,%d1")
    end = next(i for i in range(start, len(listing)) if listing[i].text == "rts")
    return [ins.text for ins in listing[start:end + 1]]


def test_every_allocation_is_behind_a_pool_guard():
    """The allocator (`0x4012a408`) pops its free list with no empty check; an empty pop
    clears low memory. midiarp makes one allocation, in the voice-trigger hook, and the
    code before it must read the list's head, branch out when it is empty and walk the
    links: take a record only while a reserve is free."""
    from dnfw.image import objdump
    listing = [ins.text for ins in objdump.disassemble(midiarp.BLOB, midiarp.CODE_VA, objdump.require_tool())]         if objdump.find_tool() else pytest.skip("no m68k objdump on PATH")
    assert listing.count(f"jsr 0x{ALLOC:x}") == 1, "midiarp allocates in one place; a second one needs a guard"
    hook = _hook()
    call = hook.index(f"jsr 0x{ALLOC:x}")
    guard = hook[next(i for i, t in enumerate(hook) if f"0x{FREE_LIST:x}" in t):call]
    assert guard[0] == f"moveal 0x{FREE_LIST:x},%a1", "the free list's head is read first"
    assert any(t.startswith("beq") for t in guard), "an empty pool leaves the hook"
    assert "moveal %a1@(92),%a1" in guard, "the links are walked, not just the head"
    assert any(t.startswith("bpl") for t in guard), "...a reserve deep"
    assert "moveq #3,%d1" in guard, "four records: the head and three more"


def test_a_layered_copy_is_gated_before_anything_is_taken():
    """The copy flag (bit 17) is tested, and the copy is played only as its own track's
    arp note (bit 19, arp MODE on), all before the pool is touched; and the note is the
    ISR's entry (%a4, the %a2 of the ISR), never the record's inline fields."""
    hook = _hook()
    call = hook.index(f"jsr 0x{ALLOC:x}")
    lead = hook[:call]
    assert "btst #17,%d1" in lead and "btst #19,%d1" in lead
    assert "tstb %a1@(403)" in lead, "the track's arp MODE, +52 + 0x15f"
    assert lead.index("btst #19,%d1") < next(i for i, t in enumerate(lead) if f"0x{FREE_LIST:x}" in t)
    assert not any(f"%a2@({off})" in t for t in hook for off in (38, 39, 40))
    assert "moveb %a4@(2),%a3@(38)" in hook


# -- the emulator evidence, when it can be run --------------------------------------

def _wsl_path(p: pathlib.Path) -> str:
    return subprocess.run(["wsl", "-e", "wslpath", "-a", str(p)], capture_output=True, text=True,
                          check=True).stdout.strip()


def test_the_emulator_harness_passes_on_this_build(applied, tmp_path):
    """`scripts/emu_midiarp_layered.py --new`: the hook, entered as the ISR enters it, on a
    layered copy and on an empty and a draining pool, with its controls."""
    if shutil.which("wsl") is None:
        pytest.skip("no WSL")
    probe = subprocess.run(["wsl", "-e", "bash", "-c",
                            "test -d /root/dn2-sections-111 && test -x /root/dn2-emu-venv/bin/python && "
                            "test -d /mnt/d/01_Code/Z_Personal/digikit-up && echo yes"],
                           capture_output=True, text=True)
    if probe.stdout.strip() != "yes":
        pytest.skip("digikit's emulator is not set up in WSL (docs/emulator.md)")
    section = tmp_path / "section_3_MAIN_OS.bin"
    section.write_bytes(applied)
    script = _wsl_path(ROOT / "scripts/emu_midiarp_layered.py")
    done = subprocess.run(
        ["wsl", "-e", "bash", "-c",
         f"DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u {script} "
         f"--new {_wsl_path(section)} < /dev/null"],
        capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-1500:]
    assert "all checks pass" in done.stdout
    assert "FAIL" not in done.stdout
