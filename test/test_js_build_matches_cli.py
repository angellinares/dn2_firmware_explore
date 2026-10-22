"""A website build is the CLI's build: the same mods give the same image.

`js_build_check.mjs` builds each mod set the way the website's pages do, page after page.
`dnfw mods apply` builds the same set. Every section must depack to the same bytes. The one
allowed difference is the /modinfo record's build part (tag, commit, the mods list and its code
hashes, the image id, the hash), and both records must pass DNX's check.

The platform area is compared as its set of chunks. The CLI applies lfo4 last whatever the
order given (APPLY_LAST); a website user can apply it first. Then the same chunks sit in another
order, which nothing at run time reads: a data chunk is found by its id and a CODE chunk runs at
its own load address (dnfw.mods.platform, "Order"; bus handlers by their `order` field).

Why: on 2026-10-21 a user's website build failed DNX's /modinfo check. The website never ran
the fill that `dnfw mods apply` runs after the mods. The per-mod tests compared the mods' own
payloads, before that step, so nothing saw it. A new mod or a new build step goes in ORDERS.
"""

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_build_check.mjs"
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"

# every website mod that needs no input file, alone, and the sets the hook bus combines
ORDERS = [
    ["arpmodes"], ["fxmod"], ["layermidi"], ["lfo4"], ["lfolength"], ["midiarp"], ["moddest"],
    ["reloadconfirm"], ["waverider"],
    ["fxmod", "waverider"], ["waverider", "fxmod"], ["lfo4", "waverider"], ["waverider", "lfo4"],
    ["waverider", "lfolength"], ["fxmod", "waverider", "lfo4"],
]
NAME = "-".join


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the website build cannot be checked")
    tmp = tmp_path_factory.mktemp("js_build")
    (tmp / "web").mkdir()
    done = subprocess.run([node, str(HARNESS), "--syx", str(_stock_syx(tmp)), "--out", str(tmp / "web"),
                           *[a for o in ORDERS for a in ("--order", ",".join(o))]],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stderr
    for order in ORDERS:
        cli = subprocess.run([sys.executable, "-c", "import sys; from dnfw.cli.main import main; sys.exit(main(sys.argv[1:]))", "mods", "apply",
                              *[a for m in order for a in ("--mod", m)], str(STOCK_111),
                              "-o", str(tmp / f"{NAME(order)}_DN2_1.11.syx")],
                             capture_output=True, text=True, cwd=ROOT)
        assert cli.returncode == 0, f"{order}: {cli.stdout[-800:]}{cli.stderr[-800:]}"
    return tmp


def _stock_syx(tmp: pathlib.Path) -> pathlib.Path:
    from dnfw.cli.files import read_image
    out = tmp / "stock.syx"
    out.write_bytes(read_image(STOCK_111))
    return out


def _sections(path: pathlib.Path) -> dict[int, bytes]:
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    container = load(read_image(path)).container
    return {s.id: s.unpack() or s.raw_payload for s in container.sections}


def _record_ok(main: bytes):
    """-> None without a /modinfo record, else whether it passes DNX's check."""
    from dnfw.mods import modinfo
    at = main.find(modinfo.MAGIC + bytes([0, 1, 1, 0]))
    return None if at < 0 else modinfo.parse(main[at:at + modinfo.BYTES])["ok"]


def _canonical(main: bytes):
    """MAIN OS as (the stock part, the area's chunks sorted), the record's build part blanked."""
    from dnfw.mods import modinfo, platform
    from dnfw.patch import area
    if not main[platform.STOCK_LENGTH:]:
        return main, []                                   # a mod with no area: the whole image
    out = []
    for cid, data in area.parse(main[platform.STOCK_LENGTH:]):
        data = bytearray(data)
        at = data.find(modinfo.MAGIC + bytes([0, 1, 1, 0]))
        if at >= 0:
            data[at + 20:at + 248] = bytes(228)
            data[at + 252:at + 256] = bytes(4)
        out.append((cid, bytes(data)))
    return main[:platform.STOCK_LENGTH], sorted(out)


@pytest.mark.parametrize("order", ORDERS, ids=NAME)
def test_the_website_build_is_the_cli_build(built, order):
    web = _sections(built / "web" / f"{NAME(order)}.syx")
    cli = _sections(built / f"{NAME(order)}_DN2_1.11.syx")
    assert sorted(web) == sorted(cli)
    want = True if "waverider" in order else None
    assert _record_ok(web[3]) is want and _record_ok(cli[3]) is want, "a missing record, or one that fails DNX's check"
    stock_web, chunks_web = _canonical(web[3])
    stock_cli, chunks_cli = _canonical(cli[3])
    assert stock_web == stock_cli, "MAIN OS: the website and the CLI differ outside the area"
    assert chunks_web == chunks_cli, "MAIN OS: the area's chunks differ"
    for sid in set(cli) - {3}:
        assert web[sid] == cli[sid], f"section {sid}: the website and the CLI differ"
