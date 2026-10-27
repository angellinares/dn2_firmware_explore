"""Run the stock parameter-table readers on a build and on stock, for every entry.

    python scripts/emu_param_readers.py BUILD.syx [--stock STOCK.syx] [--cf-call EXE]

The readers are stock's leaf accessors that take an entry and bound it first
(`move.l 4(%sp),%d0 ; cmpi.l #321 or #320,%d0`), found in the stock image. Each runs
in digikit's emulator (its `cf_call` example) for entries 0..331 on both images:

1. entries 0..320 give stock's answer on the build: the copy of the table is exact;
2. entries 321..330 (LFO4's records) read LFO4's records: with each one overwritten by a
   copy of a stock entry's record (cf_call's pokes), every reader gives stock's answer for
   that entry. A bound left at 320 clamps to entry 0 instead. The stock entries are picked
   so that each reader has one whose answer differs from entry 0's; a reader that answers
   the same for every entry cannot show a clamp and is listed as such.

`0x400c2418` reads the 68-byte companion table, which keeps its bound on purpose
(`dnfw.patch.paramtable.NOT_THIS_TIME`), so rule 2 does not apply to it. elekloader's
machines-dn2 tests run the same kind of check on 1.12 (tests/test_dn2_machines.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                    # noqa: E402
from dnfw.firmware.load import load                      # noqa: E402
from dnfw.patch import paramtable                        # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
CF_CALL = pathlib.Path("D:/01_Code/Z_Personal/digikit-wt-flushchk/out/target/release/examples/cf_call.exe")
BASE = 0x40000400
LFO4_ENTRY0, ADDED = paramtable.COUNT + 1, 10
KEPT = {0x400C2418}                    # the companion table's reader keeps its bound


def readers(stock: bytes) -> list[int]:
    out = []
    for last in (0x41, 0x40):
        pat = bytes.fromhex("202f00040c80000001") + bytes([last])
        i = 0
        while (i := stock.find(pat, i, paramtable.STOCK_END - BASE)) >= 0:
            if i % 2 == 0:
                out.append(BASE + i)
            i += 1
    return sorted(out)


def record_span(table: int, entry: int) -> int:
    """The firmware's record for ENTRY: dnfw's record entry - 1, from +8, 60 bytes."""
    return table + paramtable.RECORD * (entry - 1) + 8


def table_of(main: bytes) -> int:
    """The table the first reader's base names (paramtable's biased base, + 60 - 8)."""
    at = 0x400DBF5A - BASE                  # lea <table - 52>,%a0 in 0x400dbf4e
    assert main[at:at + 2] == bytes.fromhex("41f9")
    return int.from_bytes(main[at + 2:at + 6], "big") + paramtable.RECORD - 8


def call_all(exe, syx: bytes, base_sha, pcs, tmp: pathlib.Path, pokes=()) -> dict:
    image = tmp / f"{hashlib.sha256(syx).hexdigest()[:12]}.syx"
    image.write_bytes(syx)
    calls = [(pc, e) for pc in pcs for e in range(LFO4_ENTRY0 + ADDED)]
    req = tmp / "request.json"
    req.write_text(json.dumps({"pokes": [{"addr": hex(a), "hex": h.hex()} for a, h in pokes],
                               "calls": [{"pc": hex(pc), "args": [str(e)]} for pc, e in calls]}))
    cmd = [str(exe), str(image), str(req)] + (["--base-sha", base_sha] if base_sha else [])
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    rows = [json.loads(x) for x in done.stdout.splitlines() if x.startswith("{")]
    if done.returncode or len(rows) != len(calls):
        raise SystemExit(f"cf_call: rc {done.returncode}, {len(rows)} of {len(calls)} rows: {done.stderr[-800:]}")
    bad = [(hex(pc), e, r.get("error")) for (pc, e), r in zip(calls, rows) if not r["ok"]]
    if bad:
        raise SystemExit(f"cf_call: {len(bad)} calls did not return, first {bad[:3]}")
    return {(pc, e): r["d"][0] for (pc, e), r in zip(calls, rows)}


def pick_sources(want: dict, pcs: list[int]) -> dict[int, int]:
    """Per reader, a stock entry whose answer differs from entry 0's, from as few entries as
    covers them all (greedy)."""
    left = {pc for pc in pcs if pc not in KEPT
            and any(want[pc, e] != want[pc, 0] for e in range(1, LFO4_ENTRY0))}
    out = {}
    while left:
        best = max(range(1, LFO4_ENTRY0), key=lambda e: sum(want[pc, e] != want[pc, 0] for pc in left))
        for pc in [pc for pc in left if want[pc, best] != want[pc, 0]]:
            out[pc] = best
            left.discard(pc)
    return out


def check(build: bytes, stock: bytes, exe: pathlib.Path) -> list[str]:
    s3 = load(stock).container.find(3).unpack()
    b3 = load(build).container.find(3).unpack()
    pcs = readers(s3)
    table = table_of(b3)
    sha = hashlib.sha256(stock).hexdigest()
    with tempfile.TemporaryDirectory() as t:
        tmp = pathlib.Path(t)
        want = call_all(exe, stock, None, pcs, tmp)
        got = call_all(exe, build, sha, pcs, tmp)
        sources = pick_sources(want, pcs)
        poked = {}
        for src in sorted(set(sources.values())):
            at = record_span(paramtable.TABLE, src) - BASE
            copy = s3[at:at + paramtable.RECORD]
            pokes = [(record_span(table, LFO4_ENTRY0 + k), copy) for k in range(ADDED)]
            poked[src] = call_all(exe, build, sha, pcs, tmp, pokes)
    problems = []
    for pc in pcs:
        for e in range(LFO4_ENTRY0):
            if got[pc, e] != want[pc, e]:
                problems.append(f"{pc:#x} entry {e}: {got[pc, e]:#x}, stock {want[pc, e]:#x}")
        if pc in KEPT:
            continue
        src = sources.get(pc)
        if src is None:
            continue                        # the same answer for every entry: no signal
        for k in range(ADDED):
            e = LFO4_ENTRY0 + k
            if poked[src][pc, e] != want[pc, src]:
                problems.append(f"{pc:#x} entry {e} over a copy of entry {src}: {poked[src][pc, e]:#x}, "
                                f"stock's entry {src} {want[pc, src]:#x}, entry 0 {want[pc, 0]:#x}")
    blind = [pc for pc in pcs if pc not in KEPT and pc not in sources]
    return pcs, problems, sorted(set(sources.values())), blind


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("build", type=pathlib.Path)
    ap.add_argument("--stock", type=pathlib.Path, default=STOCK)
    ap.add_argument("--cf-call", type=pathlib.Path, default=CF_CALL)
    a = ap.parse_args()
    pcs, problems, sources, blind = check(read_image(a.build), read_image(a.stock), a.cf_call)
    print(f"{len(pcs)} readers, entries 0..{LFO4_ENTRY0 + ADDED - 1}, copies of entries {sources}")
    if blind:
        print("the same answer for every entry, so no clamp can show:", " ".join(f"{pc:#x}" for pc in blind))
    for p in problems:
        print("FAIL", p)
    print("PASS" if not problems else f"FAIL: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
