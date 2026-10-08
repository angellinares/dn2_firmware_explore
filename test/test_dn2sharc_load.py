"""dn2sharc_load: reply word 0 -> SHARC cycles, and the benchmark's rows, with no instrument."""
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import dn2sharc_load as sl  # noqa: E402


def test_word0_as_the_coldfire_holds_it():
    # captured on the instrument 2026-09-30, silent: halves 0006 58a6
    assert sl.cycles(bytes.fromhex("000658a6")) == 0x658A6 == 415910


def test_load_from_the_idle_total():
    # a second at 1,500 frames/s is 1e9 cycles; 400 M of them idle -> 60 % load
    assert abs(sl.load_from_idle((0, 0), (400_000_000, 1500)) - 0.60) < 1e-9
    # the idle total and the frame count both wrap
    assert abs(sl.load_from_idle((0xFFFFFF00, 0xFFFFFFF0), (0xFFFFFF00 + 100_000_000 - 2 ** 32, 134))
               - (1 - 100_000_000 / (150 * sl.FRAME_CYCLES))) < 1e-9
    assert sl.load_from_idle((5, 7), (9, 7)) is None


def test_summary_and_the_cost_over_silent(tmp_path):
    s = sl.summary(list(range(100, 200)))
    assert (s["median"], s["p5"], s["p95"], s["min"], s["max"], s["n"]) == (150, 105, 195, 100, 199, 100)
    path = tmp_path / "b.csv"
    assert sl.baseline(path) is None
    sl.append(path, {"when": "t", "label": "silent", **sl.summary([416000] * 5), "over_silent": ""})
    sl.append(path, {"when": "t", "label": "waverider-1", **sl.summary([424000] * 5), "over_silent": 8000})
    assert sl.baseline(path) == 416000
    assert path.read_text(encoding="utf-8").splitlines()[0].startswith("when,label,n,median")


def test_peak_windows_timed_by_the_dsps_blocks():
    F = sl.FRAME_CYCLES
    # (idle total, blocks total): 3 blocks at 40 % idle, then 2 blocks at 10 % idle, then none
    r = [(0, 10), (int(3 * F * 0.4), 13), (int(3 * F * 0.4 + 2 * F * 0.1), 15),
         (int(3 * F * 0.4 + 2 * F * 0.1), 15)]
    w = sl.peak_windows(r)
    assert len(w) == 2                                   # the window where no block passed is dropped
    assert w[0]["frames"] == 3 and abs(w[0]["load"] - 0.6) < 1e-6
    assert w[1]["frames"] == 2 and abs(w[1]["load"] - 0.9) < 1e-6
