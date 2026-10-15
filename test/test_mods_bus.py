"""The hook bus (`dnfw.mods.bus`): the sites and counts the platform owns."""

import pathlib
import struct

import pytest

from dnfw.mods import ModError, bus, platform
from dnfw.patch import area

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BASE = platform.BASE
SITE = bus.EVENTS[b"PSLT"]["site"]

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.11 image")


@pytest.fixture(scope="module")
def stock():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX)).container.find(3).unpack()


def _at(content, va, n):
    return bytes(content[va - BASE:va - BASE + n])


def _bus_chunk(content):
    for c, d in area.parse(content[platform.STOCK_LENGTH:]):
        if c == area.CODE and area.CodeChunk.unpack(d).load == bus.BUS_VA:
            return area.CodeChunk.unpack(d).image
    return None


def test_the_dispatcher_is_assembled_where_the_events_say(stock):
    spec = platform.SPEC["bus"]
    code = bytes.fromhex(spec["code"])
    assert spec["load"] == bus.BUS_VA
    assert not any(code[:4 * bus.TABLE_SLOTS])                           # the table, empty
    entry = spec["symbols"]["ev_param_slot"] - bus.BUS_VA
    assert code[entry:entry + 2] == bytes.fromhex("2f0a")                 # move.l %a2,-(%sp)
    # its last instructions are the three it displaced, then the jump back
    assert code.endswith(bus.EVENTS[b"PSLT"]["stock"] and
                         bytes.fromhex("2f027264206f00084ef9400dc032"))
    assert _at(stock, SITE, 8).hex() == bus.EVENTS[b"PSLT"]["stock"]


def test_handlers_go_in_order_and_the_site_jumps_to_the_dispatcher(stock):
    out = platform.join(stock, [bus.subscribe(b"PSLT", 0x46B00000, 60),
                                bus.subscribe(b"PSLT", 0x46A00000, 40),
                                bus.subscribe(b"PSLT", 0x46C00000, 40)])
    entry = platform.SPEC["bus"]["symbols"]["ev_param_slot"]
    assert _at(out, SITE, 8) == bytes.fromhex("4ef9") + struct.pack(">I", entry) + bytes.fromhex("4e71")
    table = _bus_chunk(out)[:4 * bus.TABLE_SLOTS]
    assert struct.unpack(">8I", table) == (0x46A00000, 0x46C00000, 0x46B00000, 0, 0, 0, 0, 0)


def test_split_puts_the_site_back_and_drops_the_dispatchers(stock):
    out = platform.join(stock, [bus.subscribe(b"PSLT", 0x46A00000)])
    base, chunks = platform.split(out)
    assert base == platform.join(stock, [])[:platform.STOCK_LENGTH]     # stock, with the loader
    assert [c for c, _ in chunks] == [bus.EVNT]
    assert platform.add(out, []) == out


def test_no_subscriber_no_dispatcher(stock):
    out = platform.join(stock, [(b"BOOT", b"x")])
    assert _at(out, SITE, 8) == _at(stock, SITE, 8)
    assert _bus_chunk(out) is None


def test_a_count_writes_every_bound_and_split_restores_them(stock):
    out = platform.join(stock, [bus.contribute(b"PARM", 10), bus.contribute(b"MACH", 1)])
    for va, width, value in bus.bounds(platform.SPEC, b"PARM"):
        assert int.from_bytes(_at(out, va, width), "big") == value + 10
    for va, width, value in bus.bounds(platform.SPEC, b"MACH"):
        assert int.from_bytes(_at(out, va, width), "big") == value + 1
    assert len(bus.bounds(platform.SPEC, b"PARM")) == 53
    assert platform.split(out)[0] == platform.join(stock, [])[:platform.STOCK_LENGTH]


def test_a_count_reaches_a_displaced_copy(stock):
    """lfo4's hook at 0x400dd282 moves the LOAD's `moveq #6`: the machine count goes there."""
    site = 0x400DD282
    replay = _at(stock, site, 6)
    code = area.CodeChunk(0x46B00000, bytes(8) + replay).pack()
    out = platform.join(stock, [(area.CODE, code), platform.displace(site, 6, 0x46B00008),
                                bus.contribute(b"MACH", 1)])
    assert _at(out, site, 6) == replay                    # nothing hooked it here, so stock
    image = next(area.CodeChunk.unpack(d).image for c, d in area.parse(out[platform.STOCK_LENGTH:])
                 if c == area.CODE and area.CodeChunk.unpack(d).load == 0x46B00000)
    assert image[8:14] == bytes.fromhex("712a001c7407")


def test_a_hook_over_an_owned_bound_without_a_copy_is_refused(stock):
    hooked = bytearray(stock)
    hooked[0x400DD282 - BASE:0x400DD288 - BASE] = bytes.fromhex("4ef946b000004e71")[:6]
    with pytest.raises(ModError, match="machine types count"):
        platform.join(bytes(hooked), [bus.contribute(b"MACH", 1)])


def test_two_mods_adding_to_one_count_are_refused(stock):
    with pytest.raises(ModError, match="two mods add machine types"):
        platform.join(stock, [bus.contribute(b"MACH", 1), bus.contribute(b"MACH", 1)])


def test_eight_handlers_are_refused(stock):
    with pytest.raises(ModError, match="the bus takes 7"):
        platform.join(stock, [bus.subscribe(b"PSLT", 0x46A00000 + 4 * k) for k in range(8)])


def test_unknown_names_are_refused():
    with pytest.raises(ModError, match="no event"):
        bus.subscribe(b"NOPE", 0)
    with pytest.raises(ModError, match="no count"):
        bus.contribute(b"NOPE", 1)


def test_a_mod_writing_an_owned_byte_by_itself_conflicts():
    from dnfw.mods import Extent, check_compatible
    own = [Extent(3, SITE - BASE, 2, "a mod's own hook")]
    assert check_compatible([("a", own), ("b", platform.extents())])
