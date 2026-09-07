"""Gate A: a decoded and re-encoded image is byte-identical to the original.

This is the strongest single check in the project. It exercises the framing,
8-in-7 packing, packet checksums, block and sequence numbering, markers,
preamble, section table and trailer all at once, with compression held
constant -- so a failure here is a transport or container bug and cannot be
blamed on the packer.
"""

import pytest

from dnfw.firmware.build import build
from dnfw.firmware.load import load
from dnfw.firmware.verify import verify

from .conftest import IMAGES


@pytest.mark.parametrize("key", sorted(IMAGES))
def test_round_trip_is_byte_identical(key, request):
    raw = request.getfixturevalue(f"{key}_raw")
    assert build(load(raw)) == raw


@pytest.mark.parametrize("key", sorted(IMAGES))
def test_stock_image_verifies(key, request):
    firmware = request.getfixturevalue(key)
    report = verify(firmware)
    assert report.ok, [c for c in report.checks if not c.ok]


@pytest.mark.parametrize("key", sorted(IMAGES))
def test_header_fields_are_what_we_recorded(key, request):
    _, device, build_string, version, signed = IMAGES[key]
    firmware = request.getfixturevalue(key)
    assert firmware.envelope.device == device
    assert firmware.container.build == build_string
    assert firmware.container.version == version
    assert firmware.signed is signed


def test_dn2_key_derives_from_the_string_we_measured(dn2):
    assert dn2.key is not None
    assert dn2.key.derivation_string == "Multiplier"


def test_dn1_is_unsigned(dn1):
    """The Digitone trailer is 32 zero bytes. Recorded because it means a DN1
    rebuild needs checksums only, and because a future OS that starts signing
    would fail this test rather than pass silently."""
    assert dn1.key is None


def test_sections_are_stored_the_way_we_recorded(dn2):
    kinds = {s.id: s.unpack() is not None for s in dn2.container.sections}
    assert kinds == {5: False, 2: True, 3: True, 4: False, 7: True}
