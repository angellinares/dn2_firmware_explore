"""dnfw.waverider.poolrecord: the 512-byte pool list (docs/for-dnx-waverider-pool.md §2)."""

import struct

from dnfw.waverider import poolrecord as PR
from dnfw.waverider import store


def test_layout_and_hash():
    r = PR.Record(5, [3, PR.NONE, 0], generation=7).to_bytes()
    assert len(r) == 512
    assert r[:4] == b"WRPL"
    assert struct.unpack_from(">HHIHH", r, 4) == (1, 5, 7, 2, 0)    # version, project, gen, count, flags
    assert struct.unpack_from(">3H", r, 16) == (3, PR.NONE, 0)
    assert set(r[270:508]) == {0}
    assert struct.unpack_from(">I", r, 508)[0] == store.xxh32(r[:508])


def test_round_trip_keeps_gaps():
    rec, checks = PR.from_bytes(PR.Record(0, [3, PR.NONE, 0]).to_bytes())
    assert rec.entries == [3, PR.NONE, 0] and not rec.automatic
    assert all(checks[k] for k in ("magic", "version", "hash", "count"))


def test_automatic_record_carries_no_entries():
    rec, checks = PR.from_bytes(PR.Record(9, [], automatic=True).to_bytes())
    assert rec.automatic and rec.entries == [] and checks["count"]


def test_sectors_are_256_apart():
    assert PR.sector_a(0) == 0x600800 and PR.sector_b(0) == 0x600900
    assert PR.sector_b(128) == 0x600980
