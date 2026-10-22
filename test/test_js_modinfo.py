"""The browser /modinfo fill against the Python one.

`js_modinfo_check.mjs` fills Waverider's record with `site/js/modinfo.js`: a website build
must pass DNX's check (docs/for-dnx-modinfo.md), as a `dnfw mods apply` build does. Before
this fill, every website build shipped the record unfilled, with a zero hash (DNX, 2026-10-21).
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_modinfo_check.mjs"
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the browser fill cannot be checked")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    from dnfw.mods import waverider
    main = waverider.apply(load(read_image(STOCK_111))).payloads[3]
    tmp = tmp_path_factory.mktemp("js_modinfo")
    (tmp / "main.bin").write_bytes(main)
    done = subprocess.run([node, str(HARNESS), "--main", str(tmp / "main.bin"), "--out", str(tmp)],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stderr
    return {"main": main, **{k: (tmp / f"{k}.bin").read_bytes() for k in ("once", "twice", "stock")},
            "xxh32": json.loads((tmp / "xxh32.json").read_text())}


def test_xxh32_matches_the_python_one(run):
    from dnfw.waverider.store import xxh32
    for n, (h0, h1) in enumerate(run["xxh32"]):
        v = bytes((k * 37 + 11) & 255 for k in range(n))
        assert (h0, h1) == (xxh32(v), xxh32(v, 0x9E3779B1)), n


def test_the_fill_is_the_python_fill_byte_for_byte(run):
    from dnfw.mods import modinfo
    want = modinfo.fill(run["main"], [("waverider", 0)], "web-waverider", "web-local", "1.11")
    assert want != run["main"]
    assert run["once"] == want


def test_the_filled_record_passes_dnx_s_check(run):
    from dnfw.mods import modinfo
    from dnfw.waverider.store import xxh32
    at = run["once"].find(modinfo.MAGIC + bytes([0, 1, 1, 0]))
    rec = run["once"][at:at + modinfo.BYTES]
    assert int.from_bytes(rec[252:256], "big") == xxh32(rec[:252])      # DNX's rule
    info = modinfo.parse(rec)
    assert info["ok"] and info["filled"], info
    zeroed = bytearray(run["once"])
    zeroed[at + 20:at + 24] = bytes(4)
    zeroed[at + 252:at + 256] = bytes(4)
    assert info["image_id"] == xxh32(bytes(zeroed))


def test_a_second_mod_keeps_the_list_and_refills(run):
    from dnfw.mods import modinfo
    at = run["twice"].find(modinfo.MAGIC + bytes([0, 1, 1, 0]))
    info = modinfo.parse(run["twice"][at:at + modinfo.BYTES])
    assert info["ok"], info
    assert [m for m, _ in info["mods"]] == ["waverider", "fxmod"]
    assert info["tag"] == "web-waverider-fxmod"


def test_an_image_without_the_record_is_unchanged(run):
    assert run["stock"] == run["main"][:65536]


def test_the_deploy_can_stamp_the_site_s_commit():
    # .github/workflows/pages.yml replaces this exact line with the commit, and fails without it
    build = (ROOT / "site/js/build.js").read_text(encoding="utf-8")
    assert 'export const SITE_COMMIT = "local";' in build.splitlines()
    assert "s/^export const SITE_COMMIT = \\\"local\\\";$/" in (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
