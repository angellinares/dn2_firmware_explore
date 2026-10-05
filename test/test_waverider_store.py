"""dnfw.waverider.store against the firmware's hash and against DNX's own plan.

The plan below is DNX's first (2026-10-05): one table into an empty store, its write
hashes and the superblock and index bytes it produced. Both sides wrote their
encoder from docs/waverider-store.md, so a disagreement is a field-order or
padding difference in one of them. It predates fixed extents (its data_end is
0x21000; the doc now says 0x11000), and slot 0's start is the same either way, so
its bytes stay a cross-check of the encoder.
"""

from dnfw.waverider import store as S

PAYLOAD = bytes((i * 7) & 0xFF for i in range(16384))
ENTRY = S.Entry("RAMP7_wt512", waves=16, points=512, start=0x1000, length=0x4000,
                table_hash=0x831953BC, source_hash=0x831953BC, source_size=0x4000)
DNX_PLAN = [
    {"what": "data", "sector": 4096, "length": 16384, "hash": 0x831953BC},
    {"what": "index", "sector": 1, "length": 32768, "hash": 0x8E82B3DF},
    {"what": "superblock", "sector": 0, "length": 512, "hash": 0x95EAE26F},
]
DNX_SUPERBLOCK_64 = bytes.fromhex(        # DNX's four rows, as sent
    "57 52 54 42 00 01 00 40 00 00 00 01 00 00 00 01"
    "00 00 01 00 00 00 00 80 8E 82 B3 DF 00 00 10 00"
    "00 02 10 00 00 00 00 00 00 00 00 00 00 00 00 00"
    "00 00 00 00 00 00 00 00 00 00 00 00 A6 36 F2 7E")
DNX_ENTRY_0 = bytes.fromhex(
    "00 01 00 01 00 10 02 00 00 01 00 00 00 00 10 00"
    "00 00 40 00 83 19 53 BC 83 19 53 BC 00 00 40 00"
    "52 41 4D 50 37 5F 77 74 35 31 32 00 00 00 00 00" + "00" * 48
    + "00 01 00 00" + "00" * 28)


def test_xxh32_is_the_firmwares():
    # the DN2 1.11 routine 0x4014be0e, run on its own code in Unicorn
    assert S.xxh32(b"") == 0x02CC5D05
    assert S.xxh32(b"Nobody inspects the spammish repetition") == 0xE2293B2F
    assert S.xxh32(PAYLOAD) == 0x831953BC


def test_dnx_plan_replays():
    plan = S.plan_writes("A", 1, {0: ENTRY}, {0: PAYLOAD}, data_end=0x21000)
    assert plan == DNX_PLAN


def test_superblock_bytes_match_dnx():
    sb = S.superblock(1, 1, S.index_bytes({0: ENTRY}), data_end=0x21000)
    assert sb[:64] == DNX_SUPERBLOCK_64
    assert sb[64:] == bytes(512 - 64)


def test_entry_round_trips_and_free_slots_are_zero():
    index = S.index_bytes({0: ENTRY})
    assert index[:128] == DNX_ENTRY_0
    assert S.Entry.from_bytes(index[:128]) == ENTRY
    assert S.Entry.from_bytes(index[128:256]) is None
    assert index[128:] == bytes(len(index) - 128)


def test_fixed_extents():
    assert S.slot_start(0) == 0x1000 and S.slot_start(255) == 0x40C00
    assert S.DATA_END == 0x41000
    moved = S.Entry("X", 16, 512, 0x1400, 0x4000, 0, 0, 0)       # slot 1's place, as slot 0
    import pytest
    with pytest.raises(ValueError, match="not its own"):
        S.plan_writes("A", 1, {0: moved}, {0: PAYLOAD}, data_end=S.DATA_END)


def test_current_group_rules():
    index = S.index_bytes({0: ENTRY})
    a = (S.superblock(1, 1, index, 0x21000), index)
    b = (S.superblock(2, 1, index, 0x21000), index)
    empty = (bytes(512), bytes(S.INDEX_BYTES))
    assert S.current_group({"A": empty, "B": empty}) is None
    assert S.current_group({"A": a, "B": empty}) == "A"
    assert S.current_group({"A": a, "B": b}) == "B"                 # higher generation
    assert S.current_group({"A": a, "B": a}) == "A"                 # a tie goes to A
    torn = (b[0], bytes(S.INDEX_BYTES))                             # index does not match
    assert S.current_group({"A": a, "B": torn}) == "A"
    bad = (bytearray(b[0]), index)
    bad[0][20] ^= 1                                                  # superblock hash fails
    assert S.current_group({"A": a, "B": (bytes(bad[0]), index)}) == "A"


# DNX's plan after fixed extents, with 128 KiB slots (2026-10-05): the same table,
# data_end 0x11000. Only the superblock moved. The slots are now 512 KiB (data_end
# 0x41000), so this vector checks the encoder at that data_end.
DNX_PLAN_FIXED_SUPERBLOCK_HASH = 0x22136DE2
DNX_SUPERBLOCK_FIXED_64 = bytes.fromhex(
    "57 52 54 42 00 01 00 40 00 00 00 01 00 00 00 01"
    "00 00 01 00 00 00 00 80 8E 82 B3 DF 00 00 10 00"
    "00 01 10 00 00 00 00 00 00 00 00 00 00 00 00 00"
    "00 00 00 00 00 00 00 00 00 00 00 00 ED 48 D8 83")


def test_dnx_fixed_extent_plan_replays():
    plan = S.plan_writes("A", 1, {0: ENTRY}, {0: PAYLOAD}, data_end=0x11000)
    assert plan[:2] == DNX_PLAN[:2]                                  # data and index unchanged
    assert plan[2] == {"what": "superblock", "sector": 0, "length": 512,
                       "hash": DNX_PLAN_FIXED_SUPERBLOCK_HASH}
    sb = S.superblock(1, 1, S.index_bytes({0: ENTRY}), data_end=0x11000)
    assert sb[:64] == DNX_SUPERBLOCK_FIXED_64


# DNX's plan at 512 KiB slots (2026-10-05): data_end 0x41000. Data and index unchanged.
DNX_SUPERBLOCK_512K_64 = bytes.fromhex(
    "57 52 54 42 00 01 00 40 00 00 00 01 00 00 00 01"
    "00 00 01 00 00 00 00 80 8E 82 B3 DF 00 00 10 00"
    "00 04 10 00 00 00 00 00 00 00 00 00 00 00 00 00"
    "00 00 00 00 00 00 00 00 00 00 00 00 A3 07 CB C7")


def test_dnx_512k_plan_replays():
    plan = S.plan_writes("A", 1, {0: ENTRY}, {0: PAYLOAD}, data_end=S.DATA_END)
    assert plan[:2] == DNX_PLAN[:2]
    assert plan[2]["hash"] == 0x80C77E1C
    assert S.superblock(1, 1, S.index_bytes({0: ENTRY}), data_end=S.DATA_END)[:64] == DNX_SUPERBLOCK_512K_64


def test_a_slot_is_exactly_tonverks_largest_table():
    # the reason for 512 KiB: 64 waves x 4,096 points of int16, with nothing spare
    assert 64 * 4096 * 2 == S.SLOT_SECTORS * S.SECTOR
