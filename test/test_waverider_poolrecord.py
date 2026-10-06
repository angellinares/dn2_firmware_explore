"""dnfw.waverider.poolrecord: the 512-byte pool list (docs/for-dnx-waverider-pool.md §2, rev 4)."""

import struct

from dnfw.waverider import poolrecord as PR
from dnfw.waverider import store


def test_v2_layout_and_hash():
    r = PR.Record(5, [3, PR.NONE, 0], generation=7).to_bytes()
    assert len(r) == 512
    assert r[:4] == b"WRPL"
    assert struct.unpack_from(">HHIHH", r, 4) == (2, 5, 7, 2, 0)    # version, project, gen, count, flags
    assert struct.unpack_from(">3H", r, 16) == (3, PR.NONE, 0)
    assert struct.unpack_from(">H", r, 16 + 2 * 127)[0] == PR.NONE   # the 128th entry
    assert set(r[272:508]) == {0}
    assert struct.unpack_from(">I", r, 508)[0] == store.xxh32(r[:508])


def test_a_full_v2_pool_holds_128():
    rec, checks = PR.from_bytes(PR.Record(0, list(range(128))).to_bytes())
    assert len(rec.entries) == 128 and checks["count"] and checks["reserved"]


def test_v1_reads_as_127_entries():
    v1 = PR.Record(0, [3, PR.NONE, 0]).to_bytes(version=1)
    assert struct.unpack_from(">H", v1, 4)[0] == 1 and set(v1[270:508]) == {0}
    rec, checks = PR.from_bytes(v1)
    assert rec.entries == [3, PR.NONE, 0] and checks["version"] == 1 and checks["known"]
    assert checks["reserved"] and checks["hash"]


def test_round_trip_keeps_gaps():
    rec, checks = PR.from_bytes(PR.Record(0, [3, PR.NONE, 0]).to_bytes())
    assert rec.entries == [3, PR.NONE, 0] and not rec.automatic
    assert all(checks[k] for k in ("magic", "known", "hash", "count"))


def test_automatic_record_carries_no_entries():
    rec, checks = PR.from_bytes(PR.Record(9, [], automatic=True).to_bytes())
    assert rec.automatic and rec.entries == [] and checks["count"]


def test_sectors_are_256_apart():
    assert PR.sector_a(0) == 0x600800 and PR.sector_b(0) == 0x600900
    assert PR.sector_b(128) == 0x600980
