"""The transients mod and the DSP's transient table (owner, 2026-10-24).

The DSP plays the bank through a table of 32 (start, length) entries, one per TRAN step. The
factory entries are 50, 100 or 150 ms, end to end. On the unit, identical beeps written every
4,800 samples played half beeps and double beeps below TRAN 52. So slot k is now table entry k,
in one of two layouts: the factory sizes (the table stays), or equal slots (the table is
rewritten to 32 entries of EQUAL_SAMPLES).

Here: stock's table is what STOCK_LENGTHS says; the equal layout fits 32 entries in the bank's
data pieces and no longer ones; the factory sizes give a byte-identical round trip; each layout
writes its table and every slot; a second apply keeps the first one's samples; and an unknown
table is refused.
"""

import math
import pathlib
import struct
import wave

import pytest

from dnfw.cli import mods as cli_mods
from dnfw.image import bootstream
from dnfw.mods import ModError, transients as T

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
STOCK_110E = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip"


@pytest.fixture(scope="module")
def stock():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


def _wav(path, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(T.RATE)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def _tone(hz, n):
    return [int(12000 * math.sin(2 * math.pi * hz * i / T.RATE)) for i in range(n)]


def _pcm(samples):
    return struct.pack(f"<{len(samples)}h", *samples)


def _firmware(stock, section7):
    return cli_mods._staged(stock, {7: section7})


def test_stock_s_table_is_stock_lengths_end_to_end(stock):
    data = stock.container.find(7).unpack()
    assert bootstream.read_span(data, T.TABLE_ADDR, T.TABLE_BYTES) == T.stock_table()
    entries = T.table(data)
    assert entries[0][0] == T.SAMPLES_START
    assert entries[-1][0] + 2 * entries[-1][1] == T.SAMPLES_END
    assert [n for _, n in entries] == T.lengths(equal=False)


def test_the_equal_layout_fits_32_entries_and_no_longer(stock, monkeypatch):
    data = stock.container.find(7).unpack()
    starts = T.layout(data)
    assert len(starts) == T.COUNT
    assert all(a % T.ALIGN == 0 for a in starts)
    assert all(b - a >= T.EQUAL_BYTES for a, b in zip(starts, starts[1:]))
    assert T.SAMPLES_START <= starts[0] and starts[-1] + T.EQUAL_BYTES <= T.SAMPLES_END
    for a in starts:                                         # no slot touches the fill block
        assert all(at is not None for at, _ in bootstream.spans(data, a, T.EQUAL_BYTES))
    monkeypatch.setattr(T, "EQUAL_SAMPLES", T.EQUAL_SAMPLES + 4)
    monkeypatch.setattr(T, "EQUAL_BYTES", T.EQUAL_BYTES + 8)
    with pytest.raises(ModError, match="31 entries"):
        T.layout(data)


def test_factory_sizes_round_trip_byte_for_byte(stock, tmp_path):
    factory = T.extract(stock)
    sources = [_wav(tmp_path / f"{k:02d}.wav", struct.unpack(f"<{len(p) // 2}h", p)) for k, p in enumerate(factory)]
    assert T.apply(stock, sources).payloads[7] == stock.container.find(7).unpack()


def test_factory_sizes_fit_each_sample_to_its_slot(stock, tmp_path):
    sizes = T.lengths(equal=False)                           # slot 0 is 2,400 samples, slot 1 is 7,200
    sources = [_wav(tmp_path / "00.wav", _tone(1000, 4000)), _wav(tmp_path / "01.wav", _tone(1500, 4000))]
    data = T.apply(stock, sources).payloads[7]
    assert bootstream.read_span(data, T.TABLE_ADDR, T.TABLE_BYTES) == T.stock_table()
    got = T.extract(_firmware(stock, data))
    assert got[0] == _pcm(_tone(1000, sizes[0]))             # cut
    assert got[1] == _pcm(_tone(1500, 4000)) + bytes(2 * (sizes[1] - 4000))   # padded
    assert got[2:] == T.extract(stock)[2:]


def test_equal_slots_write_the_table_and_every_slot(stock, tmp_path):
    n = T.EQUAL_SAMPLES
    sources = [_wav(tmp_path / "00.wav", _tone(1000, n)), _wav(tmp_path / "01.wav", _tone(1500, 9000))]
    data = T.apply(stock, sources, equal=True).payloads[7]
    assert T.table(data) == [(a, n) for a in T.layout(data)]
    got = T.extract(_firmware(stock, data))
    assert got[0] == _pcm(_tone(1000, n))
    assert got[1] == _pcm(_tone(1500, n))                    # cut to the slot
    assert got[2:] == [T.fit(pcm, n) for pcm in T.extract(stock)[2:]]


def test_fit_cuts_with_a_fade_and_pads_with_silence():
    n = 4800
    cut = struct.unpack(f"<{n}h", T.fit(_pcm([1000] * (n + 100)), n))
    assert cut[0] == 1000 and cut[-1] == 0 and cut[-T.RATE // 500 - 1] == 1000
    assert T.fit(b"\x01\x02", n) == b"\x01\x02" + bytes(2 * n - 2)


def test_a_second_apply_keeps_the_first_one_s_samples(stock, tmp_path):
    for equal in (False, True):
        first = T.apply(stock, [_wav(tmp_path / "a.wav", _tone(700, 2400))], equal=equal).payloads[7]
        again = T.apply(_firmware(stock, first), [_wav(tmp_path / "b.wav", _tone(900, 2400))],
                        equal=equal).payloads[7]
        one, two = T.extract(_firmware(stock, first)), T.extract(_firmware(stock, again))
        assert two[0][:4800] == _pcm(_tone(900, 2400))
        assert two[1:] == one[1:]


def test_slot_5_keeps_the_fill_block_silent_as_on_stock(stock, tmp_path):
    sources = [_wav(tmp_path / f"{k:02d}.wav", [8000] * 4800) for k in range(6)]
    result = T.apply(stock, sources)
    assert any(note.startswith("05: 18 samples") for note in result.notes)
    got = T.extract(_firmware(stock, result.payloads[7]))[5]
    zeros = [i for i, v in enumerate(struct.unpack("<4800h", got)) if v == 0]
    assert zeros == list(range(4516, 4534))


def test_an_unknown_table_is_refused(stock):
    data = bytearray(stock.container.find(7).unpack())
    raw = bytearray(T.stock_table())
    raw[4] ^= 0x01                                           # entry 0's length
    bootstream.write_span(data, T.TABLE_ADDR, bytes(raw))
    with pytest.raises(ModError, match="neither the factory one"):
        T.extract(_firmware(stock, bytes(data)))


def test_the_extents_include_the_table(stock):
    data = stock.container.find(7).unpack()
    table_at = bootstream.spans(data, T.TABLE_ADDR, T.TABLE_BYTES)[0][0]
    assert any(e.start == table_at and e.length == T.TABLE_BYTES for e in T.extents(stock))


def test_1_10e_s_bank_starts_32_bytes_lower_and_both_layouts_work(tmp_path):
    """1.10E has the same table with its samples at 0x8045b0a8: the start comes from the table."""
    if not STOCK_110E.exists():
        pytest.skip("Digitone II 1.10E is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    old = load(read_image(STOCK_110E))
    data = old.container.find(7).unpack()
    assert T.bank_start(data) == T.SAMPLES_START - 32
    factory = T.extract(old)
    sources = [_wav(tmp_path / f"{k:02d}.wav", struct.unpack(f"<{len(p) // 2}h", p)) for k, p in enumerate(factory)]
    assert T.apply(old, sources).payloads[7] == data
    laid = T.apply(old, sources[:1], equal=True).payloads[7]
    got = T.extract(_firmware(old, laid))
    assert [len(g) // 2 for g in got] == T.lengths(equal=True)
    assert got[1:] == [T.fit(pcm, T.EQUAL_SAMPLES) for pcm in factory[1:]]
