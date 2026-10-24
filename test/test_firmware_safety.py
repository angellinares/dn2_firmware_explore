"""The safety checklist on a good image, an image it warns on, and an image it fails, for every
check, in both implementations: `dnfw.firmware.safety` (the CLI) and `site/js/safety.js` (the
website's Check page).

`scripts/js_safety_cases.mjs` builds the images once from stock 1.11. `good` is a website build
of waverider and fxmod. Every other case is the good image (or stock) changed on purpose and
signed again, as a careful tool would sign it, so only the checklist's own rules can catch it.
The flashed build batcha1 adds usbprobe, which reads stock's USB buffer: the DMA check warns.

`EXPECT` is each case's status per check. Both checklists must give it, and the same words for
everything but a failure's reason and the rebuild's (each patcher rebuilds its own way).
"""

import argparse
import contextlib
import functools
import io
import json
import pathlib
import shutil
import subprocess

import pytest

from dnfw.firmware import compare, safety
from dnfw.firmware.load import load

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
FLASHED = ROOT / "00_Resources/02_Builds/batcha1-fxmod-lfo4-waverider-usbprobe_DN2_1.11.syx"
KEYS = ("file", "stock", "layout", "recovery", "edits", "area", "ram", "dma", "dsp", "record", "rebuild")
GOOD = dict(file="pass", stock="pass", layout="pass", recovery="pass", edits="info", area="pass", ram="pass",
            dma="pass", dsp="info", record="pass", rebuild="pass")


def _after(**changes):
    """GOOD with CHANGES; a check set to None is not in the list (the list stopped before it)."""
    out = {**GOOD, **changes}
    return {k: v for k, v in out.items() if v is not None}


STOPPED = {k: None for k in KEYS}
EXPECT = {
    "good": GOOD,
    "stock": _after(area="info", ram="skip", record="skip", rebuild="skip"),
    "flashed": _after(dma="warn"),
    # file: a damaged SysEx packet. Nothing after it is read.
    "damaged": {"file": "fail"},
    # layout: the updater's load address moved in the container's table
    "moved": _after(**{**STOPPED, "file": "pass", "stock": "pass", "layout": "fail"}),
    # recovery: one byte of the bootstrap; the rebuild then differs too
    "bootstrap": _after(recovery="fail", rebuild="warn"),
    # area: bytes past MAIN OS with no loader; a directory longer than the area
    "noloader": _after(area="fail", ram=None, dma=None, edits="info", record="skip", rebuild="skip"),
    "directory": _after(area="fail", ram=None, dma=None, record="fail", rebuild="skip"),
    # ram: a CODE chunk in stock's BSS, in its DMA section, in the stack's reserve; two that overlap
    "bss": _after(ram="fail", record="fail", rebuild="skip"),
    "dmaload": _after(ram="fail", record="fail", rebuild="skip"),
    "stack": _after(ram="fail", record="fail", rebuild="skip"),
    "overlap": _after(ram="fail", record="fail", rebuild="skip"),
    # dma: new code names the eMMC bounce buffer (a warning: it may be a read)
    "dmaname": _after(dma="warn", record="fail", rebuild="skip"),
    # record: never filled; a changed byte; MAIN OS changed after it
    "unfilled": _after(record="warn", rebuild="skip"),
    "record": _after(record="fail", rebuild="skip"),
    "imageid": _after(record="fail", rebuild="skip"),
    # rebuild: a valid record that leaves fxmod out; one that lists a mod nobody knows
    "relist": _after(rebuild="warn"),
    "unknown": _after(rebuild="skip"),
}


@pytest.fixture(scope="module")
def cases(tmp_path_factory):
    if not (STOCK_111.exists() and FLASHED.exists()):
        pytest.skip("stock 1.11 or the flashed build is not in 00_Resources")
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the cases are built with the website's code")
    from dnfw.cli.files import read_image
    tmp = tmp_path_factory.mktemp("safety")
    stock = tmp / "stock.syx"
    stock.write_bytes(read_image(STOCK_111))
    done = subprocess.run([node, str(ROOT / "scripts/js_safety_cases.mjs"), "--stock", str(stock), "--out", str(tmp)],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stderr
    shutil.copy(FLASHED, tmp / "flashed.syx")
    return {"dir": tmp, "stock": stock, "node": node, "stock_fw": load(stock.read_bytes())}


@functools.cache
def _rebuild(stock_path: pathlib.Path):
    """`dnfw check`'s rebuild, one build per mods list."""
    from dnfw.cli.check import rebuilder
    inner = rebuilder(stock_path)
    memo = {}

    def rebuild(stock, mods, tag):
        key = (tuple(mods), tag)
        if key not in memo:
            memo[key] = inner(stock, mods, tag)
        return memo[key]
    return rebuild


def _python(cases, name):
    try:
        patched = load((cases["dir"] / f"{name}.syx").read_bytes())
    except ValueError as exc:
        return [safety.Item("file", "The file is intact", "fail", str(exc))]
    return safety.check(patched, cases["stock_fw"], _rebuild(cases["stock"]))


def _site(cases, name):
    done = subprocess.run([cases["node"], str(ROOT / "scripts/js_safety_check.mjs"), "--stock", str(cases["stock"]),
                           "--image", str(cases["dir"] / f"{name}.syx"), "--rebuild"],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    if isinstance(got, dict):                          # the file did not load at all
        return [safety.Item("file", "The file is intact", "fail", got["error"])]
    return [safety.Item(i["key"], i["title"], i["status"], i["detail"]) for i in got]


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_the_cli_checklist(cases, name):
    items = _python(cases, name)
    assert {i.key: i.status for i in items} == EXPECT[name], [(i.key, i.status, i.detail) for i in items]


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_the_site_checklist_is_the_cli_s(cases, name):
    site, cli = _site(cases, name), _python(cases, name)
    if name == "flashed":                              # usbprobe: the site does not publish it
        assert site[-1].key == "rebuild" and site[-1].status == "skip" and "usbprobe" in site[-1].detail
        site, cli = site[:-1], cli[:-1]
    assert [(i.key, i.title, i.status) for i in site] == [(i.key, i.title, i.status) for i in cli]
    for a, b in zip(site, cli):
        if a.status != "fail" and a.key != "rebuild":
            assert a.detail == b.detail, a.key


def test_the_good_image_s_details(cases):
    items = {i.key: i for i in _python(cases, "good")}
    assert items["recovery"].detail == "identical to stock: 2 (bootstrap), 4 (updater), 5 (meta), 8"
    assert items["record"].detail.startswith("tag web-waverider-fxmod, build web-local, mods: waverider, fxmod")
    assert "changed runs" in items["edits"].detail and "added at the end" in items["dsp"].detail


def test_the_failures_say_what_they_found(cases):
    def detail(name, key):
        return next(i for i in _python(cases, name) if i.key == key).detail
    assert "checksum" in detail("damaged", "file")
    assert "2 (bootstrap)" in detail("bootstrap", "recovery")
    assert "loader is not installed" in detail("noloader", "area")
    assert "inside stock's RAM" in detail("bss", "ram") and "inside stock's RAM" in detail("dmaload", "ram")
    assert "stack's reserve" in detail("stack", "ram") and "overlap" in detail("overlap", "ram")
    assert "0x4e6f1300" in detail("dmaname", "dma")
    assert "0x402cf854 names 0x4e6df100" in detail("flashed", "dma")
    assert "hash" in detail("record", "record") and "image id" in detail("imageid", "record")
    assert "nosuchmod" in detail("unknown", "rebuild")


def test_text_that_looks_like_an_address_is_not_one(cases):
    main = compare.content(load((cases["dir"] / "good.syx").read_bytes()).container.find(3))[0]
    assert b"Fold" in main and EXPECT["good"]["dma"] == "pass"
