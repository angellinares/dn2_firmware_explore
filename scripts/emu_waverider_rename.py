"""The /waverider rename in the emulator: write a table, rename it, refuse the bad renames.

    python scripts/emu_waverider_rename.py BUILD.syx [--card out/dk-dn2-card.img]

Through digikit's sysex_bridge, DNX's own frames (docs/for-dnx-waverider-pool.md §1):
1. list, then write a 16 KiB table to slot 0 named "Before";
2. rename slot 0 to "After" with a 128-byte body whose every byte but the name is junk
   (0xA5), so a pass also shows that nothing outside 32..95 is read;
3. read slot 0 back: the table must be unchanged and the entry equal to the stored one
   but for the name;
4. rename slot 5 (free): refused at the first chunk;
5. rename slot 0 with a name that has no NUL in its 64 bytes: the listing keeps "After".
Prints PASS or FAIL per check.
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

from dnfw.waverider import store as S                     # noqa: E402

BRIDGE = ROOT.parent / "digikit-rust/out/native/target-host/release/examples/sysex_bridge.exe"
ARGS = ["--call-at", "0x4002e464", "--call-fn", "0x4012166e", "--call-args", "2",
        "--capture", "0x401233f2:0:1"]
CHUNK = 32768
READ_CHUNKS = 1 + (31 + 128 + 16384 + 12 + 15) // 16   # sequence 0, then 16-byte pieces

CRC = []
for i in range(256):
    c = i
    for _ in range(8):
        c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
    CRC.append(c)


def crc0(data: bytes) -> int:
    c = 0
    for b in data:
        c = (c >> 8) ^ CRC[(c ^ b) & 0xFF]
    return c ^ 0xFFFFFFFF


def enc(payload: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(payload), 7):
        ch = payload[i:i + 7]
        hi = 0
        for j, b in enumerate(ch):
            if b & 0x80:
                hi |= 1 << (6 - j)
        out.append(hi)
        out += bytes(b & 0x7F for b in ch)
    return bytes(out)


def dec(hexline: str) -> bytes:
    b = bytes.fromhex(hexline)[6:-1]
    out = bytearray()
    for i in range(0, len(b), 8):
        g = b[i:i + 8]
        for j, x in enumerate(g[1:]):
            out.append(x | (0x80 if g[0] & (1 << (6 - j)) else 0))
    return bytes(out)


class Frames:
    def __init__(self):
        self.msgid = 1
        self.handle = 0
        self.lines: list[tuple[str, str]] = []           # (label, hex)

    def frame(self, label: str, code: int, body: bytes) -> None:
        p = bytes([(self.msgid >> 7) & 0x7F, self.msgid & 0x7F, 0, 0, code]) + body
        self.lines.append((label, (b"\xf0\x00\x20\x3c\x10\x00" + enc(p) + b"\xf7").hex().upper()))
        self.msgid += 1

    def listing(self, label: str) -> None:
        self.frame(label, 0x53, b"/waverider\0")

    def write(self, label: str, path: str, data: bytes) -> None:
        self.handle += 1
        self.frame(label + ":open", 0x57, struct.pack(">I", len(data)) + path.encode() + b"\0")
        for k, at in enumerate(range(0, len(data), CHUNK)):
            ch = data[at:at + CHUNK]
            self.frame(f"{label}:chunk{k}", 0x58, struct.pack(">IIII", self.handle, k, crc0(ch), len(ch)) + ch)
        self.frame(label + ":commit", 0x59, struct.pack(">II", self.handle, 1))

    def read(self, label: str, path: str, chunks: int) -> None:
        self.handle += 1
        self.frame(label + ":open", 0x54, path.encode() + b"\0")
        for k in range(chunks):
            self.frame(f"{label}:chunk{k}", 0x55, struct.pack(">II", self.handle, k))


def container(body: bytes, slot: int) -> bytes:
    head = (bytes.fromhex("ac11d303" "02000500" "0f") + b"0059"
            + struct.pack(">IIII", 0x57, 1, slot, len(body)) + bytes([0, 12]))
    whole = head + body
    return whole + struct.pack(">II", crc0(whole[0x1F:]), len(body)) + bytes.fromhex("aaa1daaa")


def rename_body(name: bytes) -> bytes:
    body = bytearray(b"\xa5" * 128)
    body[32:96] = name.ljust(64, b"\0")[:64]
    return bytes(body)


def names(reply_hex: str) -> dict[int, str]:
    """The used slots of a /waverider listing reply, {slot: name}."""
    d = dec(reply_hex)[5:]
    found = {}
    at = 13                                            # 01, first, next, count
    while at < len(d):
        end = d.index(0, at)
        name = d[at:end].decode("cp1252")
        at = end + 1
        kind, layout = d[at], d[at + 1]
        at += 2
        if layout == 2:
            index = struct.unpack(">I", d[at:at + 4])[0]
            used = d[at + 10]
            at += 12
            if used:
                found[index] = name
        else:
            at += 4
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--card", default=str(ROOT / "out/dk-dn2-card.img"))
    a = ap.parse_args()

    table = bytes((i * 7 + 3) & 0xFF for i in range(16384))
    th = S.xxh32(table)
    entry = S.Entry("Before", 16, 512, S.slot_start(0), len(table), th, th, len(table)).to_bytes()

    f = Frames()
    f.listing("list0")
    f.write("write0", "/waverider/0", container(entry + table, 0))
    f.listing("list1")
    f.write("rename0", "/waverider/0", container(rename_body(b"After"), 0))
    f.listing("list2")
    f.read("read0", "/waverider/0", READ_CHUNKS)
    f.write("rename5", "/waverider/5", container(rename_body(b"Nope"), 5))
    f.listing("list3")
    f.write("rename_nonul", "/waverider/0", container(rename_body(b"X" * 64), 0))
    f.listing("list4")

    proc = subprocess.run([str(BRIDGE), a.build, *ARGS, "--card-image", a.card],
                          input="\n".join(h for _, h in f.lines) + "\n",
                          capture_output=True, text=True, timeout=3600)
    out = [json.loads(x) for x in proc.stdout.splitlines() if x.startswith("{")]
    replies = {}
    for label, r in zip([lab for lab, _ in f.lines], [o for o in out if "request" in o]):
        replies[label] = r["replies"]
    if len(replies) != len(f.lines):
        print("FAIL: the bridge answered", len(replies), "of", len(f.lines), proc.stderr[-2000:])
        return 1

    def listed(label):
        return names(replies[label][0]) if replies[label] else None

    def answer(label):
        return dec(replies[label][0])[5:] if replies[label] else b""

    ok = True

    def check(what, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + what + (f"  ({detail})" if detail else ""))

    check("the write lists slot 0 as Before", listed("list1") == {0: "Before"}, listed("list1"))
    check("the rename lists slot 0 as After", listed("list2") == {0: "After"}, listed("list2"))
    # the read: sequence 0 answers the open's metadata, then each sequence carries a
    # piece of the container, after a 22-byte header (ok, handle, sequence, ...)
    raw = b"".join(answer(f"read0:chunk{k}")[22:] for k in range(1, READ_CHUNKS))
    at = raw.find(bytes.fromhex("ac11d303"))
    payload = raw[at + 31: at + 31 + 128 + len(table)] if at >= 0 else b""
    want = bytearray(entry)
    want[32:96] = b"After".ljust(64, b"\0")
    check("the entry reads back the stored one but for the name", payload[:128] == bytes(want),
          payload[:128].hex() if payload else "no container")
    check("the table is unchanged", payload[128:] == table)
    check("a rename of a free slot is refused at the first chunk",
          b"a rename needs a slot in use" in answer("rename5:chunk0"), answer("rename5:chunk0")[:80])
    check("and lists nothing new", listed("list3") == {0: "After"}, listed("list3"))
    check("a name with no NUL changes nothing", listed("list4") == {0: "After"}, listed("list4"))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
