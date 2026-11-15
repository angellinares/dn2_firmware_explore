"""The send loop: it rewrites exactly the frame send's 24-byte copy loop, refuses an image
that is not stock there, and lands on 1.11 and 1.12.

What it does is measured in the emulator, not here (digikit's coupled-run, 2026-11-14):
4,030 instructions less in every audio interrupt, and the same transfer buffer contents.
`src/dnfw/mods/sendloop.py` has the detail.
"""

import pathlib

import pytest

from dnfw.checkout import resources_dir
from dnfw.mods import ModError
from dnfw.mods import sendloop

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIRMWARE = resources_dir(ROOT) / "00_Firmware"
IMAGES = {"1.11": FIRMWARE / "Digitone_II_OS1.11_dist.zip", "1.12": FIRMWARE / "Digitone_II_OS1.12.syx"}


@pytest.fixture(scope="module", params=sorted(IMAGES))
def image(request):
    path = IMAGES[request.param]
    if not path.exists():
        pytest.skip(f"Digitone II {request.param} is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    fw = load(read_image(path))
    return request.param, fw, fw.container.find(sendloop.SECTION).unpack()


def test_the_stock_loop_is_there_once(image):
    os, _, stock = image
    at = sendloop.SITES[os] - sendloop.BASE
    assert stock.count(sendloop.STOCK) == 1
    assert stock[at:at + 24] == sendloop.STOCK
    # the instruction before it loads the transfer buffer's address
    assert stock[at - 6:at] == bytes.fromhex("41f980002510")


def test_writes_the_loop_and_nothing_else(image):
    os, fw, stock = image
    at = sendloop.SITES[os] - sendloop.BASE
    out = sendloop.apply(fw).payloads[sendloop.SECTION]
    assert len(out) == len(stock)
    assert out[at:at + 24] == sendloop.NEW
    assert out[:at] == stock[:at] and out[at + 24:] == stock[at + 24:]
    (e,) = sendloop.extents(fw)
    assert (e.start, e.end) == (at, at + 24)


def test_refuses_an_image_already_changed(image):
    _, fw, _ = image
    from dnfw.cli.mods import _staged
    staged = _staged(fw, {sendloop.SECTION: sendloop.apply(fw).payloads[sendloop.SECTION]})
    with pytest.raises(ModError):
        sendloop.apply(staged)


def _run(code_is_new, source, count_bytes):
    """Both loops, as the instructions read: the 4-byte entries written, and %a0 %a3 %d0 after."""
    words = count_bytes >> 1                       # asr.l #1,%d0
    out, a3 = [], 0
    if code_is_new:
        end = words * 2                            # lea (%a3,%d0.l*2),%a2
        while end > a3:                            # cmpa.l %a3,%a2 / bhi.s (unsigned)
            out.append(0x80010000 | source[a3 // 2])
            a3 += 2
    else:
        d2 = 0
        while words > d2:                          # cmp.l %d2,%d0 / ble.s
            out.append(0x8001 << 16 | source[a3 // 2])
            d2, a3 = d2 + 1, a3 + 2
    return out, len(out) * 4, a3, words


@pytest.mark.parametrize("count", [0, 1, 2, 3, 0xA80, 2799, 2800])
def test_both_loops_build_the_same_entries(count):
    source = [(i * 40503 + 7) & 0xFFFF for i in range(1400)]
    assert _run(True, source, count) == _run(False, source, count)


def test_it_is_in_the_public_list_with_a_version():
    from dnfw.cli.mods import REGISTRY
    from dnfw.mods import history
    assert REGISTRY[sendloop.ID] is sendloop
    assert history.version(sendloop.ID) == "0.1.0"
