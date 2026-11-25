"""pslide on OS 1.12 (issue #382). Reads the user's own stock images and skips without them.
The 1.11 build is test_pslide_mod.py's.

The 1.12 build is the 1.11 build with its addresses moved, and nothing else: every word of the
code and of the edits that differs is a 1.11 address that moves to it (`osport.addr`, or a hook's
return, its site plus the bytes it displaces), and no word the two share is a 1.11 address of
the image that moves on 1.12. Every site is the survey's (`map_1.12.json`)."""

import functools
import pathlib
import sys

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import pslide, ramcheck

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = resources_dir(ROOT) / "00_Firmware"
STOCKS = {"1.11": RES / "Digitone_II_OS1.11_dist.zip", "1.12": RES / "Digitone_II_OS1.12.syx"}
BASE = pslide.BASE
IMAGE_END = 0x4030B980                          # 1.11 MAIN OS: code and constants below it
OLD, NEW = pslide.SPECS["1.11"], pslide.SPECS["1.12"]

pytestmark = pytest.mark.skipif(not all(p.exists() for p in STOCKS.values()), reason="no stock 1.11 or 1.12 image")


@functools.cache
def firmware(os):
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCKS[os]))


def stock(os):
    return firmware(os).container.find(pslide.SECTION).unpack()


# a jmp hook's return: its 1.11 site plus the bytes it displaces -> the same past its 1.12 site
BACKS = {e["va"] + len(e["stock"]) // 2: f["va"] + len(f["stock"]) // 2 for e, f in zip(OLD["edits"], NEW["edits"])}


def moved_to(word):
    """WORD (1.11) on 1.12, or None when nothing says how it moves"""
    if word in BACKS:
        return BACKS[word]
    try:
        return osport.addr("1.12", word)
    except osport.NotPorted:
        return None


def unexplained(old, new):
    """Offsets where OLD and NEW differ outside an address word that moves from OLD's to NEW's"""
    bad, i = [], 0
    while i < len(old):
        if old[i] == new[i]:
            i += 1
            continue
        for s in range(max(0, i - 3), min(i, len(old) - 4) + 1):
            if moved_to(int.from_bytes(old[s:s + 4], "big")) == int.from_bytes(new[s:s + 4], "big"):
                i = s + 4
                break
        else:
            bad.append(i)
            i += 1
    return bad


def stale(old, new):
    """Offsets of words equal in OLD and NEW that are 1.11 image addresses moving on 1.12"""
    return [i for i in range(0, len(old) - 3, 2)
            if old[i:i + 4] == new[i:i + 4] and BASE <= (w := int.from_bytes(old[i:i + 4], "big")) < IMAGE_END
            and moved_to(w) not in (None, w)]


def test_the_code_is_1_11_s_with_its_addresses_moved():
    """The routines and the eligibility tables after them: the tables read from 1.12's own parameter
    records are 1.11's"""
    a, b = (bytes.fromhex(spec["code"]["blob"]) for spec in (OLD, NEW))
    assert len(a) == len(b) and OLD["labels"] == NEW["labels"] and OLD["code"]["bss"] == NEW["code"]["bss"]
    assert unexplained(a, b) == [] and stale(a, b) == []


def test_a_1_11_address_left_in_the_code_is_caught():
    """The control: 1.11's applier, written into both builds' code"""
    a, b = (bytearray.fromhex(spec["code"]["blob"]) for spec in (OLD, NEW))
    at = 0x100
    a[at:at + 4] = b[at:at + 4] = (0x400DB092).to_bytes(4, "big")
    assert stale(bytes(a), bytes(b)) == [at]


def test_every_edit_is_1_11_s_at_its_1_12_site():
    """The same hooks into the same labels, and the clear mask's operand, where 1.12 has 1.11's bytes"""
    assert len(NEW["edits"]) == len(OLD["edits"])
    for e, f in zip(OLD["edits"], NEW["edits"]):
        assert moved_to(e["va"]) == f["va"], hex(e["va"])
        assert unexplained(bytes.fromhex(e["stock"]), bytes.fromhex(f["stock"])) == [], hex(e["va"])
        assert e["new"] == f["new"], hex(e["va"])
    assert [moved_to(g["va"]) for g in OLD["guards"]] == [g["va"] for g in NEW["guards"]]


def test_applies_to_stock_1_12_inside_its_ram():
    base = stock("1.12")
    content = pslide.apply(firmware("1.12")).payloads[pslide.SECTION]
    ram = pslide.ram("1.12")
    assert ramcheck.in_stock_dma(base, content, ram) == []
    assert ramcheck.undeclared(base, content, ram, pslide.NOT_RAM) == []


def test_the_json_reproduces_the_compose():
    from dnfw.patch.assemble import available
    if not available():
        pytest.skip("no m68k assembler")
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_pslide
    built = build_pslide.compose(stock("1.12"), log=lambda *_: None, os="1.12")
    assert built["blob"].hex() == NEW["code"]["blob"]
    content = bytearray(stock("1.12"))
    for e in NEW["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new
    assert bytes(content) == built["content"]
