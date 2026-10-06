"""The /wavepool route in the emulator: each project's pool list, read and written whole.

    python scripts/emu_waverider_wavepool.py BUILD.syx [--card out/dk-dn2-card.img]

Through digikit's sysex_bridge, DNX's own frames (docs/for-dnx-waverider-pool.md §2):
1. `/` lists `wavepool`; `/wavepool` lists 0..128, 0 named `working`, none used;
2. with tables in store slots 0 and 3, a read of project slot 0 (no record) says what
   plays: generation 0, automatic, entries [0, 3], count 2, a correct hash;
3. that read written back unchanged is refused (an automatic write carrying entries);
4. an explicit record for slot 0 is written (generation 1), then again sending the
   generation it replaces (generation 2, the other sector); each reads back as sent, with
   the generation advanced; a write sending a stale generation (1, then 77) is refused;
5. an automatic record (entries cleared) for slot 5 is stored, and reads back with
   the entries filled;
6. refusals: a bad hash, a wrong project slot inside the record, a reserved byte set,
   a table container (kind 0x57), 511 bytes, and project slot 129.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.waverider import store as S                     # noqa: E402
from emu_waverider_rename import ARGS, BRIDGE, Frames, crc0, dec   # noqa: E402

NONE = 0xFFFF
PIECES = 1 + (31 + 512 + 12 + 15) // 16


def container(body: bytes, slot: int, kind: int, version: int = 2) -> bytes:
    head = (bytes.fromhex("ac11d303" "02000500" "0f") + b"0059"
            + struct.pack(">IIII", kind, version, slot, len(body)) + bytes([0, 12]))
    whole = head + body
    return whole + struct.pack(">II", crc0(whole[0x1F:]), len(body)) + bytes.fromhex("aaa1daaa")


def record(p: int, entries: list[int], automatic=False, generation=0, count=None,
           project=None, reserved=False, bad_hash=False, version=2) -> bytes:
    n = 127 if version == 1 else 128
    e = (entries + [NONE] * n)[:n]
    used = sum(1 for s in e if s != NONE) if count is None else count
    r = bytearray(struct.pack(">IHHIHH", 0x5752504C, version, p if project is None else project,
                              generation, used, 1 if automatic else 0))
    r += struct.pack(f">{n}H", *e)
    r = r.ljust(508, b"\0")
    if reserved:
        r[300] = 1
    h = S.xxh32(bytes(r)) ^ (1 if bad_hash else 0)
    return bytes(r) + struct.pack(">I", h)


def parse_record(r: bytes) -> dict:
    magic, version, project, generation, count, flags = struct.unpack(">IHHIHH", r[:16])
    entries = list(struct.unpack(">128H", r[16:272]))
    return {"project": project, "generation": generation, "count": count, "flags": flags, "version": version,
            "entries": [s for s in entries if s != NONE], "positions": entries,
            "hash_ok": struct.unpack(">I", r[508:512])[0] == S.xxh32(r[:508]) and magic == 0x5752504C}


def listing(reply_hex: str) -> list[tuple[int, str, int]]:
    d = dec(reply_hex)[5:]
    out = []
    at = 13
    while at < len(d):
        end = d.index(0, at)
        name = d[at:end].decode("cp1252")
        at = end + 1
        layout = d[at + 1]
        at += 2
        if layout == 2:
            index = struct.unpack(">I", d[at:at + 4])[0]
            out.append((index, name, d[at + 10]))
            at += 12
        else:
            out.append((-1, name, 0))
            at += 4
    return out


def table(seed: int) -> bytes:
    return bytes((i * seed + 1) & 0xFF for i in range(16384))


def slot_file(n: int, name: str, seed: int) -> bytes:
    t = table(seed)
    th = S.xxh32(t)
    e = S.Entry(name, 16, 512, S.slot_start(n), len(t), th, th, len(t)).to_bytes()
    return container(e + t, n, 0x57, version=1)          # /waverider: store format version 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--card", default=str(ROOT / "out/dk-dn2-card.img"))
    a = ap.parse_args()

    f = Frames()
    f.frame("root", 0x53, b"/\0")
    f.frame("list0", 0x53, b"/wavepool\0")
    f.write("t0", "/waverider/0", slot_file(0, "Zero", 3))
    f.write("t3", "/waverider/3", slot_file(3, "Three", 5))
    f.read("r0", "/wavepool/0", PIECES)
    # 3 is filled in after the read; see below: an automatic record carrying entries
    f.write("auto_with_entries", "/wavepool/0",
            container(record(0, [0, 3], automatic=True), 0, 0x50))
    f.frame("list1", 0x53, b"/wavepool\0")
    f.write("explicit1", "/wavepool/0", container(record(0, [3, NONE, 0]), 0, 0x50))
    f.read("r1", "/wavepool/0", PIECES)
    f.write("explicit2", "/wavepool/0", container(record(0, [0], generation=1), 0, 0x50))
    f.read("r2", "/wavepool/0", PIECES)
    f.write("stale", "/wavepool/0", container(record(0, [9], generation=1), 0, 0x50))
    f.write("stale77", "/wavepool/0", container(record(0, [9], generation=77), 0, 0x50))
    f.read("r2b", "/wavepool/0", PIECES)
    f.write("auto5", "/wavepool/5", container(record(5, [], automatic=True), 5, 0x50))
    f.read("r5", "/wavepool/5", PIECES)
    f.write("bad_hash", "/wavepool/7", container(record(7, [1], bad_hash=True), 7, 0x50))
    f.write("bad_project", "/wavepool/7", container(record(7, [1], project=8), 7, 0x50))
    f.write("bad_reserved", "/wavepool/7", container(record(7, [1], reserved=True), 7, 0x50))
    f.write("bad_count", "/wavepool/7", container(record(7, [1, 2], count=1), 7, 0x50))
    f.write("bad_kind", "/wavepool/7", container(record(7, [1]), 7, 0x57))
    f.write("bad_length", "/wavepool/7", container(record(7, [1])[:511], 7, 0x50))
    f.write("v1", "/wavepool/9", container(record(9, [4, NONE, 2], version=1), 9, 0x50, version=1))
    f.read("r9", "/wavepool/9", PIECES)
    f.write("mixed", "/wavepool/10", container(record(10, [1], version=1), 10, 0x50, version=2))
    f.write("full", "/wavepool/11", container(record(11, [s % 256 for s in range(128)]), 11, 0x50))
    f.read("r11", "/wavepool/11", PIECES)
    f.frame("open129", 0x54, b"/wavepool/129\0")
    f.frame("list2", 0x53, b"/wavepool\0")

    proc = subprocess.run([str(BRIDGE), a.build, *ARGS, "--card-image", a.card],
                          input="\n".join(h for _, h in f.lines) + "\n",
                          capture_output=True, text=True, timeout=3600)
    out = [json.loads(x) for x in proc.stdout.splitlines() if x.startswith("{") and '"request"' in x]
    if len(out) != len(f.lines):
        print("FAIL: the bridge answered", len(out), "of", len(f.lines), proc.stderr[-2000:])
        return 1
    replies = {label: o["replies"] for (label, _), o in zip(f.lines, out)}

    def answer(label):
        return dec(replies[label][0])[5:] if replies[label] else b""

    def read_record(label):
        raw = b"".join(answer(f"{label}:chunk{k}")[22:] for k in range(1, PIECES))
        at = raw.find(bytes.fromhex("ac11d303"))
        if at < 0:
            return None, None
        return raw[at:at + 31], parse_record(raw[at + 31:at + 31 + 512])

    ok = True

    def check(what, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + what + (f"  ({detail})" if detail else ""))

    root = listing(replies["root"][0])
    check("/ lists wavepool, 5 entries", [n for _, n, _ in root][-1:] == ["wavepool"] and len(root) == 5,
          [n for _, n, _ in root])
    l0 = listing(replies["list0"][0])
    check("/wavepool lists 0..128, 0 named working, none used",
          [i for i, _, _ in l0] == list(range(129)) and l0[0][1] == "working" and l0[128][1] == "128"
          and not any(u for _, _, u in l0), l0[:3])

    head, r0 = read_record("r0")
    check("no record reads as what plays: generation 0, automatic, entries [0, 3], count 2",
          r0 and r0["generation"] == 0 and r0["flags"] == 1 and r0["entries"] == [0, 3]
          and r0["count"] == 2 and r0["hash_ok"] and r0["project"] == 0, r0 and {k: r0[k] for k in ("generation", "flags", "entries", "count", "hash_ok")})
    check("the container: kind 0x50, version 2, index 0, 512 bytes, raw",
          head and struct.unpack(">IIII", head[13:29]) == (0x50, 2, 0, 512) and head[29] == 0,
          head.hex() if head else None)
    l1 = listing(replies["list1"][0])
    check("an automatic write carrying entries is refused (still no record)", not l1[0][2], l1[0])

    _, r1 = read_record("r1")
    check("an explicit record reads back as sent, generation 1",
          r1 and r1["generation"] == 1 and r1["flags"] == 0 and r1["positions"][:3] == [3, NONE, 0]
          and r1["count"] == 2 and r1["hash_ok"], r1 and {k: r1[k] for k in ("generation", "flags", "entries", "count")})
    _, r2 = read_record("r2")
    check("written again with the current generation (1): generation 2, entries [0]",
          r2 and r2["generation"] == 2 and r2["entries"] == [0] and r2["hash_ok"], r2 and r2["generation"])
    _, r2b = read_record("r2b")
    check("a stale generation (1, then 77) is refused: still generation 2, entries [0]",
          r2b and r2b["generation"] == 2 and r2b["entries"] == [0], r2b and {k: r2b[k] for k in ("generation", "entries")})
    _, r5 = read_record("r5")
    check("a stored automatic record reads back with its own generation and the entries filled",
          r5 and r5["generation"] == 1 and r5["flags"] == 1 and r5["entries"] == [0, 3] and r5["project"] == 5,
          r5 and {k: r5[k] for k in ("generation", "flags", "entries")})
    for label, text in (("bad_kind", b"the file is not a pool list"), ("bad_length", b"a pool list is 512 bytes")):
        check(f"{label} is refused at the first chunk", text in answer(f"{label}:chunk0"), answer(f"{label}:chunk0")[:70])
    check("project slot 129 is out of range", b"out of range" in answer("open129"), answer("open129")[:70])
    l2 = listing(replies["list2"][0])
    _, r9 = read_record("r9")
    check("a version 1 write is accepted and reads back as version 2, the same entries",
          r9 and r9["version"] == 2 and r9["positions"][:3] == [4, NONE, 2] and r9["positions"][127] == NONE
          and r9["hash_ok"], r9 and {k: r9[k] for k in ("version", "entries", "generation")})
    _, r11 = read_record("r11")
    check("a full version 2 pool holds 128 entries", r11 and len(r11["entries"]) == 128 and r11["count"] == 128,
          r11 and (len(r11["entries"]), r11["count"]))
    check("used: 0, 5, 9 and 11 only (bad hash, project, reserved byte, count, mixed versions wrote nothing)",
          [i for i, _, u in l2 if u] == [0, 5, 9, 11], [i for i, _, u in l2 if u])
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
