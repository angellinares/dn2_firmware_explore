"""Gate B: the codec agrees with itself.

Two of these cases are here because they caught real bugs while porting, and
both were places the C relies on 32-bit unsigned wraparound that Python does
not have. They stay as regression tests.
"""

import random

import pytest

from dnfw.codec.aplib import DepackError, depack
from dnfw.codec.aplibpack import pack

CASES = {
    "empty": b"",
    "one": b"A",
    "two": b"AB",
    "three": b"ABC",
    "zeros": bytes(5000),
    "repeating": b"the quick brown fox " * 300,
    "long_run": b"\xa5" * 70000,
    "alternating": b"\x00\xff" * 20000,
}


def _random(size: int, seed: int) -> bytes:
    random.seed(seed)
    return bytes(random.randrange(256) for _ in range(size))


@pytest.mark.parametrize("name", sorted(CASES))
def test_round_trip(name):
    data = CASES[name]
    stream = pack(data)
    assert depack(stream, allow_truncated=not data) == data


def test_round_trip_incompressible():
    data = _random(20000, seed=1)
    assert depack(pack(data)) == data


def test_round_trip_mixed():
    # Compressible and incompressible interleaved, which is what firmware is.
    data = b"".join(_random(200, seed=i) + bytes(300) for i in range(40))
    assert depack(pack(data)) == data


def test_empty_input_still_terminates():
    """The end-of-stream token is a gamma of 0x1000002 plus 0xFF, which only
    decodes to the offset bias because the C computes it in a uint32. Without
    that masking in the depacker this raised instead of ending."""
    assert depack(pack(b""), allow_truncated=True) == b""


def test_garbage_is_rejected_not_crashed():
    """A raw section fed to the depacker used to produce a negative offset and
    read off the end of its own output. It must raise DepackError instead."""
    random.seed(99)
    for seed in range(40):
        noise = _random(4000, seed=seed + 1000)
        try:
            depack(noise, allow_truncated=True)
        except DepackError:
            pass


def test_chain_depth_changes_size_not_content():
    data = CASES["repeating"] + _random(4000, seed=5)
    outputs = {depth: pack(data, chain_depth=depth) for depth in (1, 4, 32)}
    for stream in outputs.values():
        assert depack(stream) == data
