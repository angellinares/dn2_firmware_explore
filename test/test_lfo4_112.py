"""lfo4 on OS 1.12 (issue #382). Reads the user's own stock images and skips without them.

The 1.12 build is the 1.11 build with its addresses moved, and nothing else:

- every byte that differs is inside an address word that moves by its OS shift (`osport.addr`,
  the stub cave's own move, or the shift of the nearest mapped address for a return into the
  middle of stock code), or one of three header constants with an offset folded in (`FOLDED`);
- no word that is the same in both builds is a 1.11 address of the image that moves on 1.12.
  This is the check that found `valuehooks.S` still including dn2_111.h: its return jump was
  1.11's in both builds, so the first check alone passed it.

The emulator runs (2026-11-13, digikit-main boot_gate and panel_drive) are in the PR."""

import functools
import json
import pathlib
import re
import struct
import subprocess
import sys

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import lfo4, ramcheck

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES = resources_dir(ROOT) / "00_Firmware"
STOCKS = {"1.11": RES / "Digitone_II_OS1.11_dist.zip", "1.12": RES / "Digitone_II_OS1.12.syx"}
BASE = 0x40000400
IMAGE_END = 0x4030B980                          # 1.11 MAIN OS: code and constants below it
CAVE, CAVE_BYTES = 0x402DFA1C, 896              # the engine's stub cave (build_lfo4_tick.CAVE)
FOLDED = {                                      # 1.11 word -> 1.12 word, a header constant plus an offset
    0x401F95D0: 0x401F99E0,                     # DN2_PARAM_TABLE + 94 x 60, LFO3's first record
    0x42432D34: 0x42433D34,                     # PAGE_TABLE + 0x134
    0x4242F654: 0x42430654,                     # DN2_COMPANION less the index offset widget.c folds in
}

pytestmark = pytest.mark.skipif(not all(p.exists() for p in STOCKS.values()), reason="no stock 1.11 or 1.12 image")


@functools.cache
def stock(os):
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCKS[os])).container.find(3).unpack()


@functools.cache
def _near_shift(word):
    """The shift of the nearest mapped address within 64 bytes: a return into the middle of code"""
    for d in range(2, 66, 2):
        for c in (word - d, word + d):
            try:
                return osport.addr("1.12", c) - c
            except osport.NotPorted:
                pass
    return None


def moved_to(word):
    """WORD (1.11) on 1.12, or None when nothing says how it moves"""
    if word in FOLDED:
        return FOLDED[word]
    if CAVE <= word < CAVE + CAVE_BYTES:
        return word + osport.addr("1.12", CAVE) - CAVE
    try:
        return osport.addr("1.12", word)
    except osport.NotPorted:
        pass
    if BASE <= word < IMAGE_END and _near_shift(word) is not None:
        return word + _near_shift(word)
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
    out = []
    for i in range(0, len(old) - 3, 2):
        w = int.from_bytes(old[i:i + 4], "big")
        if old[i:i + 4] == new[i:i + 4] and BASE <= w < IMAGE_END and moved_to(w) not in (None, w):
            out.append(i)
    return out


def patched(os):
    spec = lfo4.SPECS[os]
    out = bytearray(stock(os))
    for e in spec["edits"]:
        new = bytes.fromhex(e["new"])
        out[e["va"] - BASE:e["va"] - BASE + len(new)] = new
    return out


def test_the_spec_is_1_12_s():
    spec = lfo4.SPECS["1.12"]
    assert spec["os"] == "Digitone II 1.12"
    assert spec["stock_length"] == len(stock("1.12"))
    assert spec["area_va"] == BASE + len(stock("1.12"))
    assert spec["table_va"] == lfo4.SPECS["1.11"]["table_va"]             # mod RAM does not move


def test_every_edit_is_1_11_s_with_its_addresses_moved():
    old, new = lfo4.SPECS["1.11"], lfo4.SPECS["1.12"]
    a, b = patched("1.11"), patched("1.12")
    for e in old["edits"]:
        va, n = e["va"], len(e["new"]) // 2
        nb = moved_to(va)
        lo = [i - 3 for i in unexplained(bytes(a[va - BASE - 3:va - BASE + n + 3]),
                                         bytes(b[nb - BASE - 3:nb - BASE + n + 3]))]
        assert [i for i in lo if 0 <= i < n] == [], hex(va)
        assert stale(bytes(a[va - BASE:va - BASE + n]), bytes(b[nb - BASE:nb - BASE + n])) == [], hex(va)
    assert len(new["edits"]) == len(old["edits"])


def test_the_cave_and_the_code_are_1_11_s_with_their_addresses_moved():
    a, b = patched("1.11"), patched("1.12")
    to = moved_to(CAVE)
    ca, cb = bytes(a[CAVE - BASE:CAVE - BASE + CAVE_BYTES]), bytes(b[to - BASE:to - BASE + CAVE_BYTES])
    assert unexplained(ca, cb) == [] and stale(ca, cb) == []
    xa, xb = (bytes.fromhex(lfo4.SPECS[os]["blob"]) for os in ("1.11", "1.12"))
    assert len(xa) == len(xb)
    assert unexplained(xa, xb) == [] and stale(xa, xb) == []


def test_a_1_11_address_left_in_the_code_is_caught():
    """The control: valuehooks.S's return as it was before the fix, written into 1.12's code"""
    xa, xb = (bytearray.fromhex(lfo4.SPECS[os]["blob"]) for os in ("1.11", "1.12"))
    at = 0x100
    xa[at:at + 4] = xb[at:at + 4] = struct.pack(">I", 0x400C2422)       # 1.11's companion accessor + 10
    assert stale(bytes(xa), bytes(xb)) == [at]


def test_every_lfo4_source_builds_for_either_os():
    for f in sorted((ROOT / "csrc/lfo4").iterdir()):
        if f.suffix in (".c", ".h", ".S") and not f.name.startswith("stock_"):
            assert '"dn2_111.h"' not in f.read_text(encoding="utf-8"), f.name
    r = subprocess.run([sys.executable, str(ROOT / "scripts/gen_dn2_header.py"), "--os", "1.12",
                        "--inc", "csrc/lfo4/stock_111.h", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_hand_read_addresses_are_unique_at_their_place():
    """by_hand_1.12.json: 32 bytes of 1.11 around each occur once in 1.12, at the new address,
    or differ there only in address words the map moves"""
    data = json.loads((ROOT / "src/dnfw/osport/by_hand_1.12.json").read_text(encoding="utf-8"))
    a, b = stock("1.11"), stock("1.12")
    for k, row in data["addresses"].items():
        va, new = int(k, 16), int(row["new"], 16)
        window = a[va - BASE - 16:va - BASE + 16]
        hits = [m.start() for m in re.finditer(re.escape(window), b)]
        assert hits in ([new - BASE - 16], []), k
        if not hits:
            assert unexplained(window, b[new - BASE - 16:new - BASE + 16]) == [], k


def test_applies_to_stock_1_12_inside_its_ram():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    firmware = load(read_image(STOCKS["1.12"]))
    content = lfo4.apply(firmware).payloads[lfo4.SECTION]
    base = stock("1.12")
    ram = lfo4.ram()
    assert ramcheck.in_stock_dma(base, content, ram) == []
    assert ramcheck.undeclared(base, content, ram, lfo4.NOT_RAM) == []
    assert [va for va, _, _ in lfo4.state_heap("1.12")] == [0x4464BBF0, 0x4464CBF0, 0x4464DBF0]
