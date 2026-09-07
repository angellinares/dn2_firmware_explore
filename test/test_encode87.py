"""8-in-7 packing."""

import random

from dnfw.syx import encode87


def test_round_trip_every_length_up_to_three_groups():
    data = bytes(range(256)) * 2
    for length in range(0, 3 * encode87.GROUP + 2):
        chunk = data[:length]
        assert encode87.decode(encode87.encode(chunk)) == chunk


def test_encoded_bytes_are_all_seven_bit():
    payload = encode87.encode(bytes(range(256)))
    assert all(byte < 0x80 for byte in payload)


def test_a_full_packet_payload_carries_101_bytes():
    # The geometry the transport depends on: 116 encoded bytes -> 101 decoded.
    assert len(encode87.encode(bytes(101))) == 116
    assert len(encode87.decode(bytes(116))) == 101


def test_high_bits_survive():
    random.seed(7)
    data = bytes(random.randrange(256) for _ in range(1000))
    assert encode87.decode(encode87.encode(data)) == data
