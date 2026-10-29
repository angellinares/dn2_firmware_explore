"""The Waverider page's Technical tab: its figures and tables are current with the models.

`scripts/gen_waverider_tech.py` computes them from the code that ships; a change to the reader,
the glide, the de-click or the noise that leaves the page stale fails here.
"""

import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
PAGE = ROOT / "site/waverider.html"
DNX = pathlib.Path("D:/01_Code/Z_Personal/DNX")


def test_every_region_is_filled():
    import gen_waverider_tech as gen
    text = PAGE.read_text(encoding="utf-8")
    found = {m.group(2): m.group(0) for m in gen.TECH.finditer(text)}
    assert len(found) == 33                 # 17, page 5: foldcurve, foldwave, shaper, warpcurve, warpwave, fmwave, the high range: hrlevels, hrcliff, hrtable, hrsteps, and MIDI: midimap, and the sub's polyBLEP: subblepedge, subblepsqr, subbleppls, subbleptable, subblepspec
    assert all(len(block) > 200 for block in found.values()), [k for k, v in found.items() if len(v) <= 200]
    for name in ("sub_blep_without", "sub_blep_with", "sub_blep_unit"):     # the spectrograms the polyBLEP section shows
        assert (ROOT / f"site/art/waverider/{name}.png").is_file(), name


def test_the_page_is_current():
    if not (DNX / "web/dist/packages/core/src/waverider/fit.js").exists() or not shutil.which("node"):
        pytest.skip("DNX's built fit.js and node are needed for the import table")
    import gen_waverider_tech as gen
    text = PAGE.read_text(encoding="utf-8")
    assert gen.rewrite(text, gen.figures(DNX)) == text, "run scripts/gen_waverider_tech.py"
