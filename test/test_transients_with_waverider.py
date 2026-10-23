"""The FM drum transients and Waverider combine (owner, 2026-10-23).

Waverider rebuilds the DSP boot stream: its blocks go in before the final block, and it writes
six runs over stock code (`dsp.site_loads`). The transient bank is in none of them, so
Waverider takes a section 7 that is stock but for the bank (`dsp._check_stock`) and carries the
bank through, and the transients mod finds the bank by its load address in Waverider's stream.

Here: both orders give the same section 7; its bank holds the new samples and the factory
entries after them; outside the bank it is Waverider's own section 7; the two mods' extents do
not overlap; and anything else changed in section 7 is still refused.
"""

import hashlib
import math
import pathlib
import struct
import wave

import pytest

from dnfw.cli import mods as cli_mods
from dnfw.image import bootstream
from dnfw.mods import ModError, check_compatible, transients, waverider
from dnfw.waverider import dsp

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
SLOTS = 3


@pytest.fixture(scope="module")
def stock():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def hits(tmp_path_factory):
    folder = tmp_path_factory.mktemp("hits")
    entries = []
    for k in range(SLOTS):
        samples = [int(20000 * math.exp(-n / (300 + 200 * k)) * math.sin(n * (0.05 + 0.03 * k)))
                   for n in range(transients.ENTRY_SAMPLES)]
        data = struct.pack(f"<{len(samples)}h", *samples)
        with wave.open(str(folder / f"{k:02d}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(transients.RATE)
            w.writeframes(data)
        entries.append(data)
    return sorted(folder.glob("*.wav")), b"".join(entries)


def _then(firmware, first, second):
    """FIRMWARE with FIRST's payloads applied, then SECOND's, staged as `dnfw mods apply` does."""
    payloads = dict(first(firmware).payloads)
    payloads.update(second(cli_mods._staged(firmware, payloads)).payloads)
    return payloads


def test_the_bank_constants_are_the_transients_mod_s(stock):
    assert dsp.TRANSIENT_BANK == (transients.BANK_ADDR, transients.COUNT * transients.ENTRY_BYTES)
    stream = stock.container.find(7).unpack()
    masked = bytearray(stream)
    for at, n in dsp.bank_spans(stream):
        masked[at:at + n] = bytes(n)
    assert hashlib.sha256(bytes(masked)).hexdigest() == dsp.STOCK_SHA256_NO_BANK


def test_the_extents_do_not_overlap(stock):
    assert check_compatible([("waverider", list(waverider.extents(stock))),
                             ("transients", transients.extents(stock))]) == []


def test_both_orders_give_the_same_section_7_with_the_new_bank(stock, hits):
    sources, want = hits
    tr = lambda f: transients.apply(f, sources)               # noqa: E731
    a = _then(stock, tr, waverider.apply)[7]                  # transients, then Waverider
    b = _then(stock, waverider.apply, tr)[7]                  # Waverider, then transients
    assert a == b
    bank = bootstream.read_span(a, *dsp.TRANSIENT_BANK)
    factory = bootstream.read_span(stock.container.find(7).unpack(), *dsp.TRANSIENT_BANK)
    assert bank[:len(want)] == want
    assert bank[len(want):] == factory[len(want):]


def test_outside_the_bank_it_is_waverider_s_own_section_7(stock, hits):
    sources, _ = hits
    both = _then(stock, lambda f: transients.apply(f, sources), waverider.apply)[7]
    alone = waverider.apply(stock).payloads[7]
    assert len(both) == len(alone)
    a, b = bytearray(both), bytearray(alone)
    for at, n in dsp.bank_spans(alone):
        a[at:at + n] = b[at:at + n] = bytes(n)
    assert a == b


def test_any_other_change_in_section_7_is_still_refused(stock):
    stream = bytearray(stock.container.find(7).unpack())
    at, _ = dsp.bank_spans(bytes(stream))[0]
    stream[at - 1] ^= 0x01                                    # the byte before the bank
    with pytest.raises(dsp.DspError, match="nor stock with its transient bank replaced"):
        dsp.section7(bytes(stream))
    with pytest.raises(ModError):
        waverider.apply(cli_mods._staged(stock, {7: bytes(stream)}))
