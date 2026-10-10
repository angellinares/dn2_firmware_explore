"""Every address above BSS a mod's bytes name is RAM the mod declares (`dnfw.mods.ramcheck`).

The platform compares declared RAM pairwise, so a declaration that misses a
range defeats it silently. On 2026-09-30 lfo4's LFO state arrays were missing
from its `ram()`, the boot screen's stamp was placed on them, and the first
flash of the three together raised V04 at 0x46700000. (lfo4's arrays have since
moved into stock's heap; `in_stock_dma` is the check for where they were.)
"""

import pathlib

import pytest

from dnfw.mods import ramcheck

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def applied(tmp_path_factory):
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.cli.mods import REGISTRY, _apply_default
    from dnfw.firmware.load import load
    fw = load(read_image(STOCK_111))
    stock = fw.container.find(3).unpack()
    tmp = tmp_path_factory.mktemp("ramcheck")
    out = {}
    for mid, mod in REGISTRY.items():
        result = _apply_default(mod, fw, tmp)
        if 3 in result.payloads:
            out[mid] = (mod, result.payloads[3])
    return stock, out


def test_every_mod_declares_the_ram_it_names(applied):
    stock, mods = applied
    bad = {}
    for mid, (mod, content) in mods.items():
        found = ramcheck.undeclared(stock, content, getattr(mod, "ram", list)(),
                                    getattr(mod, "NOT_RAM", ()))
        if found:
            bad[mid] = [f"0x{at:08x} names 0x{v:08x}" for at, v in found[:8]]
    assert not bad, bad


def test_no_mod_uses_stocks_dma_section(applied):
    """Stock's uncached DMA section (the eMMC bounce buffer is in it) holds nothing of ours."""
    stock, mods = applied
    bad = {mid: found for mid, (mod, content) in mods.items()
           if (found := ramcheck.in_stock_dma(stock, content, getattr(mod, "ram", list)(),
                                              getattr(mod, "READS_STOCK_DMA", ())))}
    assert not bad, bad


def test_it_would_have_caught_lfo4s_state_in_the_bounce_buffer():
    """lfo4 as it was until 2026-10-11: arrays at 0x46700000, declared and named."""
    import struct
    from dnfw.mods import RAM, Extent, platform
    old = [Extent(RAM, 0x46700000, 2560, "LFO state LIVE"), Extent(RAM, 0x46702000, 2560, "LFO state BACKUP")]
    stock = bytes(64)
    assert len(ramcheck.in_stock_dma(stock, stock, old)) == 1                      # LIVE; BACKUP is above it
    for value, window in ((0x46700000, ""), (0x4E6F1300, " (the uncached window)")):
        content = bytearray(stock)
        content[8:12] = struct.pack(">I", value)
        assert ramcheck.in_stock_dma(stock, bytes(content), []) == [
            f"{platform.BASE + 8:#010x} names {value:#010x}{window}"]
    content = bytearray(stock)
    content[8:12] = struct.pack(">I", 0x46702000)                                  # above the section: not its business
    assert ramcheck.in_stock_dma(stock, bytes(content), []) == []


def test_lfo4s_state_is_in_the_heaps_first_block():
    from dnfw.mods import lfo4
    assert [va for va, _, _ in lfo4.STATE_HEAP] == [0x4464ABF0, 0x4464BBF0, 0x4464CBF0]
    assert not any(x.what.startswith("LFO state") for x in lfo4.ram())
