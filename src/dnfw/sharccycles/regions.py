"""Which memory an ADSP-21569 address lands in.

From the datasheet (ADSP-21562/3/5/6/7/9 Rev. D): Table 2 (L1 blocks in each
address space), Table 3 (L2), Table 4 (L1 through the completer port), Table 6
(DMC, the DDR). The core MMRs are at 0x30000..0x31fff
(as digikit's runner models them), the system's on the peripheral bus at
0x30000000..0x31ffffff (Hardware Reference, Appendix A).

Each L1 block's byte range is its whole window (0x240000, 0x2c0000, 0x300000,
0x380000 onward), not only the size Table 2 lists: the firmware's stack runs at
0x2ffxxx, past block 1's listed end 0x2effff, and the instrument runs it.

A data address is classified in the space the instruction used: byte, normal
word, short word or long word. A program address (pc, short words) is
classified in the VISA instruction space.
"""

from __future__ import annotations

# (name, first, last) per space; the L1 block names are what the "same block in
# one cycle" stall compares.
_L1_DATA = (
    # byte                      normal word             short word              long word
    ("l1b0", 0x00240000, 0x002BFFFF), ("l1b0", 0x00090000, 0x0009BFFF),
    ("l1b0", 0x00120000, 0x00137FFF), ("l1b0", 0x00048000, 0x0004DFFF),
    ("l1b1", 0x002C0000, 0x002FFFFF), ("l1b1", 0x000B0000, 0x000BBFFF),
    ("l1b1", 0x00160000, 0x00177FFF), ("l1b1", 0x00058000, 0x0005DFFF),
    ("l1b2", 0x00300000, 0x0037FFFF), ("l1b2", 0x000C0000, 0x000C7FFF),
    ("l1b2", 0x00180000, 0x0018FFFF), ("l1b2", 0x00060000, 0x00063FFF),
    ("l1b3", 0x00380000, 0x0039FFFF), ("l1b3", 0x000E0000, 0x000E7FFF),
    ("l1b3", 0x001C0000, 0x001CFFFF), ("l1b3", 0x00070000, 0x00073FFF),
)
_OTHER_DATA = (
    ("l1sys", 0x28240000, 0x2839FFFF),     # L1 through the completer port (Table 4)
    ("l1sys", 0x0A090000, 0x0A0E7FFF),
    ("l2", 0x20000000, 0x2011FFFF),        # L2 RAM and boot ROM, byte (Table 3)
    ("l2", 0x08000000, 0x08045FFF),        # normal word
    ("ddr", 0x80000000, 0xBFFFFFFF),       # DMC0, byte (Table 6)
    ("ddr", 0x10000000, 0x17FFFFFF),       # normal word
    ("cmmr", 0x00030000, 0x00031FFF),      # core MMRs (digikit encoding.CORE_MMR_RANGE)
    ("smmr", 0x30000000, 0x31FFFFFF),      # the peripheral bus (HRM Appendix A)
    ("spi", 0x60000000, 0x7FFFFFFF),       # SPI2/OSPI0 memory-mapped flash (Table 5)
)
_CODE = (
    ("l1b0", 0x00120000, 0x00137FFF), ("l1b1", 0x00160000, 0x00177FFF),
    ("l1b2", 0x00180000, 0x0018FFFF), ("l1b3", 0x001C0000, 0x001CFFFF),
    ("l2", 0x00B00000, 0x00BFFFFF),        # L2 RAM and boot ROM, VISA (Table 3)
    ("ddr", 0x00800000, 0x00AFFFFF),       # DMC0, VISA (Table 6)
    ("spi", 0x00F80000, 0x00FFFFFF),
)

L1 = frozenset({"l1b0", "l1b1", "l1b2", "l1b3"})
CACHED = frozenset({"l2", "ddr", "spi"})


def _find(table, address: int) -> str:
    for name, lo, hi in table:
        if lo <= address <= hi:
            return name
    return "unmapped"


def data_region(address: int) -> str:
    """The memory a data access to ADDRESS lands in: l1b0..l1b3, l1sys, l2, ddr,
    cmmr, smmr, spi or unmapped."""
    name = _find(_L1_DATA, address)
    return name if name != "unmapped" else _find(_OTHER_DATA, address)


def code_region(pc_sw: int) -> str:
    """The memory an instruction at short-word address PC_SW is fetched from."""
    return _find(_CODE, pc_sw)
