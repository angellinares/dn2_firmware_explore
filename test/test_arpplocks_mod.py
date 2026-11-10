"""The arp p-locks mod: applies to stock 1.11, refuses a changed image, and
combines with the boot screen (its core cave sits past the boot screen's code)."""

import pathlib

import pytest

from dnfw.mods import ModError, check_compatible
from dnfw.mods import arpplocks, bootscreen
from dnfw.checkout import resources_dir  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


def test_applies_every_edit(dn2_111):
    result = arpplocks.apply(dn2_111)
    content = result.payloads[arpplocks.SECTION]
    for e in arpplocks.SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        at = e["va"] - arpplocks.BASE
        assert content[at:at + len(new)] == new


def test_refuses_a_changed_image(dn2_111):
    section = dn2_111.container.find(arpplocks.SECTION)
    content = bytearray(section.unpack())
    at = arpplocks.SPEC["edits"][0]["va"] - arpplocks.BASE
    content[at] ^= 0xFF

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
        arpplocks.apply(Stub)


def test_combines_with_the_boot_screen():
    named = [(arpplocks.ID, arpplocks.extents()),
             (bootscreen.ID, bootscreen.extents(None, area_length=4096))]
    assert check_compatible(named) == []


def test_a_knob_push_in_the_arp_menu_reaches_the_clear(dn2_111):
    """Issue #317: the ARPEGGIATOR menu's key handler takes an encoder push and does
    nothing with it (0x4001975c, `addi.l #-41,%d2`). The mod puts a `jmp push_hook`
    there, and push_hook's knob table maps A..D to MODE, SPEED, RANGE and N.LEN
    (k 0, 2, 1, 3; E..H none). The clear itself is measured in the emulator
    (scripts/emu_arp_push_clear.py)."""
    import struct
    push = arpplocks.SPEC["code"]["labels"]["push_hook"]
    content = arpplocks.apply(dn2_111).payloads[arpplocks.SECTION]
    at = 0x4001975C - arpplocks.BASE
    stock = dn2_111.container.find(arpplocks.SECTION).unpack()
    assert stock[at:at + 6] == bytes.fromhex("0682ffffffd7")
    assert content[at:at + 6] == b"\x4e\xf9" + struct.pack(">I", push)
    labels = arpplocks.SPEC["code"]["labels"]
    # push_hook and its gates come after every earlier routine, so none of them moved
    assert push > max(v for k, v in labels.items() if not k.startswith(("push", "pg_")))
    # the knob table sits just before the first gate
    at_k = labels["pg_ui_mode"] - arpplocks.CODE_VA - 8
    assert arpplocks.BLOB[at_k:at_k + 8] == bytes([0, 2, 1, 3, 0xFF, 0xFF, 0xFF, 0xFF])


def test_a_turn_while_the_knob_is_down_goes_through_the_gate(dn2_111):
    """0.1.2 (#317 on the unit): a real knob turns a little while pushed, and that
    turn locked the value again. Each arp setter call in the menu now goes to a gate
    (pg_ui_*) that drops the turn while push_hook holds the knob's bit."""
    import struct
    labels = arpplocks.SPEC["code"]["labels"]
    content = arpplocks.apply(dn2_111).payloads[arpplocks.SECTION]
    for site, gate in ((0x40018EEE, "pg_ui_mode"), (0x40018F56, "pg_ui_spd"),
                       (0x40018FBE, "pg_ui_rng"), (0x40019026, "pg_ui_nlen")):
        at = site - arpplocks.BASE
        assert content[at:at + 6] == b"\x4e\xb9" + struct.pack(">I", labels[gate]), gate
