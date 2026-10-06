"""The /modinfo record: what an image is modded with (docs/for-dnx-modinfo.md).

Waverider's +Drive chunk carries the 256-byte record (csrc/wrstore/modinfo.c) and fills
what it knows itself: the capabilities, the pool's size and record version, the store's
slots. The rest is written here, into the MAIN OS payload, after every mod is applied:
the mods, the build tag, the commit, the image's id and the record's hash. An image
without Waverider has no record and no route; `fill` then changes nothing.

Layout, big-endian:

| at | bytes | field |
|---|---|---|
| 0 | 4 | magic `DNMI` |
| 4 | 2 | record version, 1 |
| 6 | 2 | record bytes, 256 |
| 8 | 4 | capabilities (CAPS); unknown bits are ignored by readers |
| 12 | 2 | pool slots |
| 14 | 2 | pool record version |
| 16 | 2 | store slots |
| 18 | 2 | zero |
| 20 | 4 | image id: xxHash32 of the MAIN OS payload with this field and the hash zeroed |
| 24 | 8 | OS the image was built from, e.g. `1.11` (information only: never gate on it) |
| 32 | 24 | build tag, e.g. `wr-tblname` |
| 56 | 12 | commit, e.g. `a97b3ca1d2` (`+` at the end: uncommitted changes) |
| 68 | 1 | mod count, then 3 zero bytes |
| 72 | 16 each | a mod: id (12, NUL-padded), xxHash32 of its code (4; 0 for none) |
| 248 | 4 | zero |
| 252 | 4 | xxHash32 of bytes 0..251 |
"""

from __future__ import annotations

import struct

from ..waverider.store import xxh32

MAGIC = b"DNMI"
VERSION = 1
BYTES = 256
MARKER = b"MODINFO-UNFILLED"      # at 24 until the build writes the record
MARKER_AT = 24
MOD_AT, MOD_BYTES, MAX_MODS = 72, 16, 11
CAPS = {0x01: "store", 0x02: "pool", 0x04: "rename", 0x08: "delete", 0x10: "pool_cas", 0x20: "page"}


class ModInfoError(Exception):
    pass


def _text(s: str, n: int) -> bytes:
    b = s.encode("ascii", "replace")[:n - 1]
    return b + bytes(n - len(b))


def locate(payload: bytes) -> int | None:
    """-> where the record starts in PAYLOAD, None if there is none (no Waverider)."""
    at = payload.find(MARKER)
    if at < 0:
        return None
    if payload.find(MARKER, at + 1) >= 0:
        raise ModInfoError("the /modinfo marker appears twice")
    start = at - MARKER_AT
    if payload[start:start + 4] != MAGIC:
        raise ModInfoError(f"the /modinfo marker at {at:#x} has no record in front of it")
    return start


def fill(payload: bytes, mods: list[tuple[str, int]], tag: str, commit: str, os: str) -> bytes:
    """PAYLOAD (MAIN OS, every mod applied) with its /modinfo record written; unchanged
    when it carries none."""
    start = locate(payload)
    if start is None:
        return payload
    if len(mods) > MAX_MODS:
        raise ModInfoError(f"{len(mods)} mods; the record holds {MAX_MODS}")
    rec = bytearray(payload[start:start + BYTES])
    rec[20:24] = bytes(4)
    rec[24:32] = _text(os, 8)
    rec[32:56] = _text(tag, 24)
    rec[56:68] = _text(commit, 12)
    rec[68:72] = bytes([len(mods), 0, 0, 0])
    rec[MOD_AT:248] = bytes(248 - MOD_AT)
    for k, (mid, code) in enumerate(mods):
        at = MOD_AT + MOD_BYTES * k
        rec[at:at + MOD_BYTES] = _text(mid, 12) + struct.pack(">I", code)
    rec[248:256] = bytes(8)
    out = bytearray(payload[:start] + bytes(rec) + payload[start + BYTES:])
    image_id = xxh32(bytes(out))                      # the id and the hash still zero
    struct.pack_into(">I", out, start + 20, image_id)
    struct.pack_into(">I", out, start + 252, xxh32(bytes(out[start:start + 252])))
    return bytes(out)


def parse(rec: bytes) -> dict:
    """A /modinfo record -> its fields, and whether it checks out (magic, version, hash)."""
    if len(rec) < BYTES:
        raise ModInfoError(f"{len(rec)} bytes; a record is {BYTES}")
    magic, version, size, caps, pool_slots, pool_version, store_slots = struct.unpack_from(">4sHHIHHH", rec)
    count = rec[68]
    mods = []
    for k in range(min(count, MAX_MODS)):
        at = MOD_AT + MOD_BYTES * k
        mods.append((rec[at:at + 12].split(b"\0")[0].decode("ascii"), struct.unpack_from(">I", rec, at + 12)[0]))

    def text(a, b):
        return rec[a:b].split(b"\0")[0].decode("ascii", "replace")
    return {"ok": magic == MAGIC and version == VERSION and size == BYTES
                  and struct.unpack_from(">I", rec, 252)[0] == xxh32(rec[:252]),
            "version": version, "caps": caps,
            "capabilities": [name for bit, name in CAPS.items() if caps & bit],
            "pool_slots": pool_slots, "pool_version": pool_version, "store_slots": store_slots,
            "image_id": struct.unpack_from(">I", rec, 20)[0],
            "os": text(24, 32), "tag": text(32, 56), "commit": text(56, 68), "mods": mods,
            "filled": rec[MARKER_AT:MARKER_AT + len(MARKER)] != MARKER}
