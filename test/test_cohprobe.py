"""The cache coherence diagnostic's stream: code placement, state, the idle patch and the decoders."""

import hashlib
import json
import pathlib

import pytest

from dnfw.image import bootstream
from dnfw.waverider import cohprobe, dsp

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMAGE = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"


@pytest.fixture(scope="module")
def stock():
    if not IMAGE.exists():
        pytest.skip("factory 1.11 image not present")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(IMAGE)).container.find(7).unpack()


def test_the_committed_code_is_the_source():
    spec = json.loads(cohprobe.CODE.read_text(encoding="utf-8"))["cohprobe"]
    src = (ROOT / spec["source"]).read_bytes().replace(b"\r\n", b"\n")
    assert spec["source_sha256"] == hashlib.sha256(src).hexdigest()
    assert int(spec["load_sw"], 16) == cohprobe.CODE_SW


def test_the_cases_stay_in_their_memory():
    ddr = [at for c, (_, at) in cohprobe.CASES.items() if c != "E"]
    assert all(dsp.DDR_REGION[0] <= at and at + cohprobe.SPAN <= dsp.DDR_REGION[1] for at in ddr)
    assert all(b - a == cohprobe.SPAN for a, b in zip(ddr, ddr[1:]))
    e = cohprobe.CASES["E"][1]
    assert cohprobe.PUB_DM + 4 * cohprobe.PUB_ENTRIES <= e
    assert e + 4 * cohprobe.LINES <= cohprobe.STATE_DM + cohprobe.STATE_BYTES <= dsp.REGION[1]


def test_stream(stock):
    out = cohprobe.section7_cohprobe(stock)
    walked = bootstream.walk(out)
    assert walked.complete and walked.stopped_at == len(out)
    assert bootstream.read_span(out, dsp.l2_sw_to_load(dsp.IDLE_SITE_SW), 6) == cohprobe.objects()["probe_jump"]
    code = cohprobe.objects()["cohprobe"]
    assert bootstream.read_span(out, dsp.dm_to_load(cohprobe.CODE_DM), len(code)) == code
    assert bootstream.read_span(out, dsp.dm_to_load(cohprobe.STATE_DM), cohprobe.STATE_BYTES) == bytes(cohprobe.STATE_BYTES)


def test_decoders():
    assert cohprobe.decode(11 << 27 | 0x1203) == (11, 0x1203)
    assert cohprobe.first_bad(0) is None
    assert cohprobe.first_bad(0x1000 | 3 << 8 | 15) == ("C", 15)
    assert len(cohprobe.PUB_NAMES) == cohprobe.PUB_ENTRIES
