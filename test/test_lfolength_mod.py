"""The LFO ONE/HALF fix (lfolength): four hooks into a CODE chunk and four NOP'd stop-table
stores, refused on an image that isn't stock there, sharing no byte with any mod but the one
it supersedes (lfohold), and its code is the build script's.

What it *does* is measured in the emulator (`scripts/emu_lfo_trigmodes.py --fix
--compare`, 2026-10-09): stock ONE stops at the cycle's end and HALF at its middle,
whatever the start phase; with the hooks every start phase runs one cycle / half a cycle,
tracing TRIG's waveform until the stop. `docs/lfo-trig-modes.md` has the tables.
"""

import pathlib
import struct
import sys

import pytest

from dnfw.mods import ModError, check_compatible, lfohold, lfolength, platform

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(lfolength.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(dn2_111):
    return lfolength.apply(dn2_111).payloads[lfolength.SECTION]


def test_four_hooks_each_a_jmp_into_the_chunk(stock, applied):
    original, chunks = platform.split(applied)
    assert len(original) == len(stock)
    labels = lfolength.SPEC["labels"]
    for e in [e for e in lfolength.SPEC["edits"] if "hook" in e["what"]]:
        off = e["va"] - lfolength.BASE
        assert stock[off:off + len(e["stock"]) // 2].hex() == e["stock"]
        new = original[off:off + len(e["new"]) // 2]
        assert new[:2] == bytes.fromhex("4ef9")
        assert struct.unpack(">I", new[2:6])[0] in labels.values()
        assert new[6:] == bytes.fromhex("4e71") * ((len(new) - 6) // 2)
    assert any(c[0] == platform.area.CODE for c in chunks)


def test_extents_cover_the_change(stock, applied):
    # the hooks, plus the platform loader's own installation (its start-up calls and cave)
    original, _chunks = platform.split(applied)
    changed = [i for i in range(len(stock)) if stock[i] != original[i]]
    for i in changed:
        assert any(e.start <= i < e.end for e in lfolength.extents())


def test_the_code_is_the_build_scripts(stock):
    import build_lfo_length as b
    built = b.compose(stock, log=lambda *_: None)
    assert built["blob"].hex() == lfolength.SPEC["code"]["blob"]
    assert built["labels"] == lfolength.SPEC["labels"]
    assert lfolength.CODE_VA == b.CODE_VA


def test_refuses_an_image_already_patched(dn2_111, applied):
    from dnfw.cli.mods import _staged
    staged = _staged(dn2_111, {lfolength.SECTION: applied})
    with pytest.raises(ModError, match="Start from the original 1.11 file"):
        lfolength.apply(staged)


def test_shares_no_byte_with_any_mod_but_the_platforms(dn2_111):
    # every platform mod shares the loader's extents by design; compare the hooks alone
    from dnfw.cli.mods import REGISTRY
    hooks = [e for e in lfolength.extents(dn2_111)
             if e not in platform.extents(16 + len(lfolength.BLOB))]
    for mid, mod in REGISTRY.items():
        if mid in ("transients", lfolength.ID, lfohold.ID):   # lfohold: superseded, the same stores
            continue
        assert check_compatible([(lfolength.ID, hooks), (mid, list(mod.extents(dn2_111)))]) == [], mid


def test_four_stores_nopd(stock, applied):
    original, _chunks = platform.split(applied)
    stores = [e for e in lfolength.SPEC["edits"] if e["what"].startswith("hold")]
    assert len(stores) == 4
    for e in stores:
        off = e["va"] - lfolength.BASE
        n = len(e["new"]) // 2
        assert stock[off:off + n].hex() == e["stock"]
        assert original[off:off + n] == bytes.fromhex("4e71") * (n // 2)


def test_supersedes_lfohold(dn2_111):
    # the same A stores: the two mods conflict, so they are never combined
    assert lfohold.SUPERSEDED_BY == lfolength.ID
    assert check_compatible([(lfolength.ID, list(lfolength.extents(dn2_111))),
                             (lfohold.ID, list(lfohold.extents(dn2_111)))]) != []
