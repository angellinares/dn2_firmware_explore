"""The OS update buffer: a Digitone II image of more than 20,764 data packets does not verify.

The running 1.11 OS writes packet n at state + 20 + 101 n into a static buffer and never checks
the size (docs/version-gate.md section 5b). One packet over would write past the buffer.
"""

import dataclasses

from dnfw.firmware import verify as v


def _buffer(firmware):
    return next(c for c in v.verify(firmware).checks if c.name == "fits the OS's 2 MiB update buffer")


def test_stock_fits_with_room(dn2):
    check = _buffer(dn2)
    assert check.ok, check
    assert dn2.packets < v.UPDATE_PACKETS


def test_the_last_packet_fits_and_one_more_does_not(dn2):
    assert _buffer(dataclasses.replace(dn2, packets=v.UPDATE_PACKETS)).ok
    over = _buffer(dataclasses.replace(dn2, packets=v.UPDATE_PACKETS + 1))
    assert not over.ok
    assert over.detail.endswith("101 bytes too many"), over.detail


def test_the_buffer_is_2_mib_from_state_plus_0x20():
    # Packet n lands at state + 20 + 101 n. The next object starts at state + 0x20 + 0x200000.
    assert 20 + v.UPDATE_PACKETS * v.UPDATE_PACKET_BYTES == 0x20 + 0x200000
