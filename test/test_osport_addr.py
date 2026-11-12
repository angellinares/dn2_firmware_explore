"""dnfw.osport.addr: the committed 1.11 -> 1.12 map against addresses read by hand on the two stock
images (2026-11-12, vault "OS 1.12 migration.md"). Reads only the map, so it needs no firmware."""

import pytest

from dnfw import osport

# (1.11, 1.12): each read by hand, byte for byte, on the stock images. The map holds only addresses that
# the mods and their generators name; scripts/osport_check.py checks the map itself, LZ4, eMMC and the
# update validator included, against the images.
KNOWN = [
    (0x40026980, 0x40026980),            # layermidi hook 1: same address and bytes
    (0x40026D32, 0x40026D32),            # layermidi hook 2
    (0x400187F6, 0x400187F6),            # midiarp
    (0x400D905E, 0x400D91C2),            # midiarp, +0x164
    (0x40121D86, 0x40122066),            # midiarp: a jsr operand, +0x2e0 (another project gave the opcode, 2 B off)
    (0x4012A408, 0x4012A6E8),            # the MIDI record allocator
    (0x4012166E, 0x4012194E),            # the SysEx handler
    (0x401F7F94, 0x401F83A4),            # the parameter table's base, a data value
]


@pytest.mark.parametrize("old,new", KNOWN, ids=[f"{o:#x}" for o, _ in KNOWN])
def test_the_map_gives_each_address_read_by_hand(old, new):
    assert osport.addr("1.12", old) == new


def test_the_source_version_maps_to_itself():
    assert osport.addr("1.11", 0x40026980) == 0x40026980


def test_an_address_the_map_did_not_decide_stops_the_build():
    with pytest.raises(osport.NotPorted):
        osport.addr("1.12", 0x4464ABF0)          # the 1.11 heap start: no instruction names it
    with pytest.raises(osport.NotPorted):
        osport.addr("1.13", 0x40026980)          # no map for that version


def test_mod_ram_above_both_dma_sections_stays():
    """RAM above 1.12's DMA section passed the three checks (refscan, data scan, touch run), so a mod's
    chunk there keeps its address, in either window"""
    assert osport.addr("1.12", 0x46710000) == 0x46710000          # the platform's data window
    assert osport.addr("1.12", 0x4E710000) == 0x4E710000          # the same RAM, uncached


def test_mod_ram_that_1_12_dma_now_covers_must_move():
    with pytest.raises(osport.NotPorted, match="DMA"):
        osport.addr("1.12", 0x46708000)                           # bootscreen's 1.11 chunk


def test_stock_dma_addresses_follow_the_map():
    assert osport.addr("1.12", 0x4E6DF100) == 0x4E6E7100          # the SSI receive ring, +0x8000


def test_the_1_12_header_is_the_generator_s_output():
    import pathlib
    import subprocess
    import sys
    root = pathlib.Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, str(root / "scripts/gen_dn2_header.py"), "--os", "1.12", "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_sram_addresses_carry_over():
    assert osport.addr("1.12", 0x800052A0) == 0x800052A0            # the kit pointer


def test_a_site_moves_with_its_relocated_words():
    """layermidi's guard on the MIDI pool's head: `movea.l 0x4460e4b8,%a0`, the address +0x1000"""
    image = bytearray(0x200000)
    new_va = osport.addr("1.12", 0x4012A40E)
    at = new_va - 0x40000400
    image[at:at + 6] = bytes.fromhex("20794460f4b8")
    assert osport.site("1.12", 0x4012A40E, bytes.fromhex("20794460e4b8"), bytes(image)) \
        == (new_va, bytes.fromhex("20794460f4b8"))
    image[at:at + 2] = bytes.fromhex("2279")                        # another instruction: refused
    with pytest.raises(osport.NotPorted):
        osport.site("1.12", 0x4012A40E, bytes.fromhex("20794460e4b8"), bytes(image))


def test_render_keeps_1_11_text_and_moves_addresses_for_1_12():
    ns = {"ALLOC": 0x4012A408, "FREE": 0x4460E4B8, "COUNT": 19, "CODE_VA": 0x467D8000, "__builtins__": {}}
    t = "    jsr     {ALLOC:#x}\n    move.l  {FREE:#x},%d0\n    moveq   #{COUNT},%d1\n    lea     {CODE_VA + 4:#x},%a0\n"
    want = ["    jsr     0x4012a408", "    move.l  0x4460e4b8,%d0", "    moveq   #19,%d1",
            "    lea     0x467d8004,%a0", ""]
    assert osport.render(t, ns, "1.11") == chr(10).join(want)
    out = osport.render(t, ns, "1.12")
    assert "jsr     0x4012a6e8" in out and "0x4460f4b8" in out and "#19" in out and "0x467d8004" in out


def test_rebind_names_the_constant_it_cannot_move():
    with pytest.raises(osport.NotPorted, match="FLAG"):
        osport.rebind({"FLAG": 0x405CD8AE}, "1.12")
    assert osport.rebind({"FLAG": 0x405CD8AE}, "1.12", {"FLAG": 0x405CE8AE})["FLAG"] == 0x405CE8AE


def test_render_refuses_a_moved_literal():
    """A stock address written as a literal in a template would not move: render names it"""
    template = "    jmp     0x40137566              | a literal: 0x40137574 in a comment is fine\n"
    assert osport.render(template, {}, "1.11") == template
    with pytest.raises(osport.NotPorted, match="0x40137566"):
        osport.render(template, {}, "1.12")
    assert osport.render("    jmp     {T:#x}\n", {"T": 0x40137566}, "1.12") == "    jmp     0x40137846\n"
