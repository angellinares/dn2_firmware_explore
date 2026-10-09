"""The DDR scan diagnostic's stream: fills, state, code placement and the idle patch."""

import pathlib
import struct

import pytest

from dnfw.image import bootstream
from dnfw.waverider import ddrscan, dsp

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMAGE = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"


@pytest.fixture(scope="module")
def stock():
    if not IMAGE.exists():
        pytest.skip("factory 1.11 image not present")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(IMAGE)).container.find(7).unpack()


def test_fills_cover_the_span_with_the_pattern():
    blocks = bootstream.walk(ddrscan.fills()).blocks
    assert all(b.flags & bootstream.FLAG_FILL and b.argument == ddrscan.PATTERN for b in blocks)
    assert blocks[0].target == ddrscan.SPAN[0]
    assert all(a.target + a.count == b.target for a, b in zip(blocks, blocks[1:]))
    assert blocks[-1].target + blocks[-1].count == ddrscan.SPAN[1] == ddrscan.DDR[1]
    assert all(b.count <= ddrscan.FILL_BLOCK and b.count % 4 == 0 for b in blocks)


def test_the_span_starts_past_the_stock_image():
    assert ddrscan.SPAN[0] > dsp.STOCK_DDR_END
    with pytest.raises(dsp.DspError):
        ddrscan.fills((0x80500000, 0x80600000))


def test_state_block():
    s = ddrscan.state()
    cur, start, end, pattern = struct.unpack_from("<IIII", s, 0x20)
    assert (cur, start, end, pattern) == (ddrscan.SPAN[0], ddrscan.SPAN[0], ddrscan.SPAN[1], ddrscan.PATTERN)
    assert struct.unpack_from("<II", s, 0x34) == (ddrscan.DDR[0], ddrscan.DDR[0])
    assert s[0x80:] == bytes(0x80)


def test_stream(stock):
    out = ddrscan.section7_ddrscan(stock)
    walked = bootstream.walk(out)
    assert walked.complete and walked.stopped_at == len(out)
    assert bootstream.read_span(out, dsp.l2_sw_to_load(dsp.IDLE_SITE_SW), 6) == ddrscan.objects()["scan_jump"]
    code = ddrscan.objects()["ddrscan"]
    assert bootstream.read_span(out, dsp.dm_to_load(ddrscan.SCAN_DM), len(code)) == code
    fills = [b for b in walked.blocks if b.flags & bootstream.FLAG_FILL and b.argument == ddrscan.PATTERN]
    assert sum(b.count for b in fills) == ddrscan.SPAN[1] - ddrscan.SPAN[0]


def test_decode_and_granules():
    assert ddrscan.decode(3 << 27 | 0x14CBFF) == (3, 0x14CBFF)
    assert ddrscan.granules([0b100] + [0] * 14 + [1 << 15]) == [2, 255]
