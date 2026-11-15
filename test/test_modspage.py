"""The MODS page (SETTINGS > SYSTEM > MODS). The builds read the user's own stock images and skip
without them."""

import pathlib
import struct

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import ModError, history, modspage, platform, ramcheck

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCKS = {"1.11": resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.11_dist.zip",
          "1.12": resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"}
ROWS = [("OS", "1.11"), ("A BUILD NAME", ""), ("COMMIT 780CA6F", ""), ("LFO WAVES", "1.0.1")]


def firmware(os):
    if not STOCKS[os].exists():
        pytest.skip(f"no stock {os} image")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCKS[os]))


def test_the_table_is_a_count_and_32_bytes_a_row():
    t = modspage.table(ROWS)
    assert struct.unpack(">I", t[:4]) == (4,) and len(t) == 4 + 32 * 4
    assert t[4:24] == b"OS".ljust(20, b"\0") and t[24:36] == b"1.11".ljust(12, b"\0")
    assert t[4 + 32:4 + 52] == b"A BUILD NAME".ljust(20, b"\0") and t[4 + 52:4 + 64] == bytes(12)


@pytest.mark.parametrize("row", [("A" * 20, ""), ("NAME", "1" * 12), ("100%", ""), ("NAME", "%s")])
def test_the_table_refuses_a_row_it_cannot_show(row):
    """A name of 20, a value of 12 (no room for the NUL), and `%`: the value's text is its format"""
    with pytest.raises(ModError):
        modspage.table([row])


def test_the_rows_are_the_os_the_build_and_the_commit_then_the_mods():
    rows = modspage.rows(["lfowaves", "degreetranspose", "usbprobe"], "1.12", "my-build_name%", "780ca6f5b6+")
    assert rows == [("OS", "1.12"), ("MY-BUILD_NAME", ""), ("COMMIT 780CA6F+", ""),
                    ("LFO WAVES", history.version("lfowaves")),
                    ("DEGREE TRANS", history.version("degreetranspose")),
                    ("USB PROBE", history.version("usbprobe"))]
    modspage.table(rows)


def test_every_listed_mod_has_a_name_that_clears_the_value_column():
    from dnfw.cli.mods import REGISTRY
    assert set(REGISTRY) <= set(modspage.MENU_NAMES), "a mod with no row name shows its id"
    assert all(len(n) <= modspage.NAME_MAX and n == modspage.text(n, 99) for n in modspage.MENU_NAMES.values())


def test_a_mod_with_no_name_or_version_shows_its_id():
    assert modspage.rows(["somethingunknown"], "1.11", "", "") == [("OS", "1.11"), ("NO NAME", ""), ("COMMIT UNKNOWN", ""),
                                                                   ("SOMETHINGUNK", "")]


@pytest.mark.parametrize("os", ["1.11", "1.12"])
def test_applies_to_stock_inside_its_extents_and_its_ram(os):
    fw = firmware(os)
    base = fw.container.find(modspage.SECTION).unpack()
    result = modspage.apply(fw, ROWS)
    content = result.payloads[modspage.SECTION]
    spec = modspage.SPECS[os]
    # the one hook, at the end of the SYSTEM menu's constructor
    (edit,) = spec["edits"]
    assert edit["va"] == osport.addr(os, 0x4010BDE4) if os != "1.11" else edit["va"] == 0x4010BDE4
    at = edit["va"] - modspage.BASE
    assert content[at:at + 6] == bytes.fromhex("4ef9") + struct.pack(">I", spec["code"]["va"])
    # the chunk: the code, then the rows
    original, chunks = platform.split(content)
    (code,) = [platform.area.CodeChunk.unpack(d) for c, d in chunks if c == platform.area.CODE]
    assert code.load == spec["code"]["va"]
    assert code.image == bytes.fromhex(spec["code"]["blob"]) + modspage.table(ROWS)
    assert spec["labels"]["table"] == code.load + len(spec["code"]["blob"]) // 2
    # nothing outside what it declares
    ram = modspage.ram(os, len(ROWS))
    assert ram[0].length == len(code.image)
    assert ramcheck.in_stock_dma(base, content, ram) == []
    assert ramcheck.undeclared(base, content, ram, ()) == []
    declared = [(e.start, e.start + e.length) for e in result.extents if e.section == modspage.SECTION]
    stray = [i for i in range(len(base)) if base[i] != content[i] and not any(a <= i < b for a, b in declared)]
    assert stray == []


def test_the_1_12_code_names_only_moved_addresses():
    blob11, blob12 = (bytes.fromhex(modspage.SPECS[os]["code"]["blob"]) for os in ("1.11", "1.12"))
    assert len(blob11) == len(blob12)
    for va in (0x401170D8, 0x40117224, 0x4011690E, 0x4011B600, 0x4011BC26, 0x40115668, 0x446447EC, 0x446464EC):
        assert struct.pack(">I", va) in blob11
        assert struct.pack(">I", osport.addr("1.12", va)) in blob12, hex(va)
        assert osport.addr("1.12", va) == va or struct.pack(">I", va) not in blob12, hex(va)


def test_parse_reads_a_table_back():
    assert modspage.parse(modspage.table(ROWS)) == ROWS


def test_merge_keeps_the_old_mods_adds_the_new_and_takes_the_new_build_rows():
    old = [("OS", "1.11"), ("OLD BUILD", ""), ("COMMIT 1111111", ""), ("LFO WAVES", "1.0.0"), ("FX MOD", "1.0.2")]
    new = [("OS", "1.11"), ("NEW BUILD", ""), ("COMMIT 2222222", ""), ("LFO 4", "1.0.7"), ("LFO WAVES", "1.0.1")]
    assert modspage.merge(old, new) == [("OS", "1.11"), ("NEW BUILD", ""), ("COMMIT 2222222", ""),
                                        ("LFO WAVES", "1.0.1"), ("FX MOD", "1.0.2"), ("LFO 4", "1.0.7")]
    assert modspage.merge([], new) == new


def test_merge_refuses_more_rows_than_the_page_holds():
    top = [("OS", "1.11"), ("A BUILD", ""), ("COMMIT 1111111", "")]
    many = top + [(f"MOD {k}", "1.0.0") for k in range(modspage.ROWS_MAX - 3)]
    with pytest.raises(ModError):
        modspage.merge(many, top + [("ONE MORE", "1.0.0")])


def test_an_image_that_has_the_page_keeps_its_hook_and_gets_the_new_rows():
    """`dnfw mods apply` on an image an earlier `mods apply` made, as the website's pages do"""
    from dnfw.cli.mods import _staged
    fw = firmware("1.11")
    assert modspage.existing(fw) == []
    first = modspage.apply(fw, ROWS)
    built = _staged(fw, first.payloads)
    assert modspage.existing(built) == ROWS
    rows = modspage.merge(ROWS, modspage.rows(["fxmod"], "1.11", "second", "abcdef0"))
    second = modspage.apply(built, rows).payloads[modspage.SECTION]
    _, chunks = platform.split(second)
    mine = [platform.area.CodeChunk.unpack(d) for c, d in chunks if c == platform.area.CODE]
    assert len(mine) == 1 and modspage.parse(mine[0].image[len(modspage.SPEC["code"]["blob"]) // 2:]) == rows
    assert rows == [("OS", "1.11"), ("SECOND", ""), ("COMMIT ABCDEF0", ""),
                    ("LFO WAVES", "1.0.1"), ("FX MOD", history.version("fxmod"))]
    stock = fw.container.find(modspage.SECTION).unpack()
    assert second[:len(stock)] == first.payloads[modspage.SECTION][:len(stock)], "the hook is written once"
