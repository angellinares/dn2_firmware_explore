"""`undeclared_writes`: every byte a build changes is inside an extent a mod declared."""

from dnfw.mods import Extent, undeclared_writes

STOCK = {3: bytes(10_000)}


def _built(*runs, grow=0):
    b = bytearray(STOCK[3]) + bytes(grow)
    for lo, hi in runs:
        b[lo:hi] = b"\x01" * (hi - lo)
    return {3: bytes(b)}


def test_declared_writes_pass():
    named = [("a", [Extent(3, 100, 50)]), ("b", [Extent(3, 9000, 1000), Extent(3, 10_000, 64)])]
    assert undeclared_writes(STOCK, _built((100, 150), (9990, 10_064), grow=64), named) == []


def test_a_write_outside_every_extent_is_named():
    found = undeclared_writes(STOCK, _built((100, 150), (5000, 5002)), [("a", [Extent(3, 100, 50)])])
    assert found == ["section 3 0x00001388..0x0000138a changed, and no mod declares it"]


def test_growth_past_the_declared_length_is_named():
    found = undeclared_writes(STOCK, _built(grow=40), [("a", [Extent(3, 10_000, 16)])])
    assert found == ["section 3 0x00002720..0x00002738 changed, and no mod declares it"]


def test_two_extents_together_cover_a_run():
    named = [("a", [Extent(3, 4000, 100)]), ("b", [Extent(3, 4100, 100)])]
    assert undeclared_writes(STOCK, _built((4050, 4150)), named) == []


def test_a_shorter_section_is_named():
    assert undeclared_writes(STOCK, {3: bytes(10)}, []) == ["section 3 shrank from 10,000 to 10 bytes"]


def test_another_sections_extent_does_not_count():
    assert undeclared_writes(STOCK, _built((10, 12)), [("a", [Extent(7, 10, 2)])]) != []
