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
