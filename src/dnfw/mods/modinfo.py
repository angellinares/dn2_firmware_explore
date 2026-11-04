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
| 18 | 1 | a name's characters the pool keeps (15) |
| 19 | 1 | a name's characters TBL's header shows (14; longer: 12, then "..") |
| 20 | 4 | image id: xxHash32 of the MAIN OS payload with this field and the hash zeroed |
| 24 | 8 | OS the image was built from, e.g. `1.11` (information only: never gate on it) |
| 32 | 24 | build tag, e.g. `wr-tblname` |
| 56 | 12 | commit, e.g. `a97b3ca1d2` (`+` at the end: uncommitted changes) |
| 68 | 1 | mod count, then 3 zero bytes |
| 72 | 16 each | the first 11 mods: id (12, NUL-padded), xxHash32 of its code (4; 0 for none) |
| 248 | 1 | the most waves a table the pool plays has (64), when caps has `playable` |
| 249 | 1 | log2 of the fewest points (6: 64) |
| 250 | 1 | log2 of the most points (12: 4096) |
| 251 | 1 | flags: 1 the points must be a power of two |
| 252 | 4 | in a 512-byte record: zero (in a 256-byte record, the hash) |
| 256 | 16 each | in a 512-byte record: mods 12 to 26, as at 72 |
| bytes - 4 | 4 | xxHash32 of everything before it (252 or 508) |

A reader takes the hash from `bytes - 4`, accepts a `bytes` larger than it knows, and
reads only the fields it knows: the record grows by appending. Builds up to Waverider 0.3.7
carry 256 bytes (11 mods). Later builds carry 512 (26 mods). A reader that knows only 256
reads the first 11 mods of a 512-byte record, and the count at 68 stays right.
"""

from __future__ import annotations

import struct

from ..waverider.store import xxh32

MAGIC = b"DNMI"
VERSION = 1
BYTES = 256                            # the smallest record (SIZES)
MARKER = b"MODINFO-UNFILLED"      # at 24 until the build writes the record
MARKER_AT = 24
SIZES = (256, 512)                     # the lengths a record has: up to Waverider 0.3.7, then
MOD_AT, MOD_BYTES, MOD_END = 72, 16, 248
MORE_AT = 256                          # a 512-byte record's mods 12 and up


def mod_slots(size: int) -> list[int]:
    """-> where each mod sits in a record of SIZE bytes: 11 at 72, then 15 at 256 (512 only)."""
    first = [MOD_AT + MOD_BYTES * k for k in range((MOD_END - MOD_AT) // MOD_BYTES)]
    return first + [MORE_AT + MOD_BYTES * k for k in range(max(0, size - 4 - MORE_AT) // MOD_BYTES)]


MAX_MODS = len(mod_slots(SIZES[-1]))   # 26, in a record this code's chunk builds
CAPS = {0x01: "store", 0x02: "pool", 0x04: "rename", 0x10: "pool_cas", 0x20: "page",
        0x40: "playable", 0x80: "erase", 0x100: "pool_only"}   # 0x08 unused


class ModInfoError(Exception):
    pass


def _text(s: str, n: int) -> bytes:
    b = s.encode("ascii", "replace")[:n - 1]
    return b + bytes(n - len(b))


def size_at(payload: bytes, start: int) -> int:
    """-> the length the record at START says it has (byte 6)."""
    size = struct.unpack_from(">H", payload, start + 6)[0]
    if size not in SIZES:
        raise ModInfoError(f"the /modinfo record says it is {size} bytes, not {' or '.join(map(str, SIZES))}")
    return size


def record(payload: bytes, start: int) -> bytes:
    """-> the record at START, at its own length."""
    return bytes(payload[start:start + size_at(payload, start)])


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


def find(payload: bytes) -> int | None:
    """-> where a record starts in PAYLOAD by its header (filled or not), None if there is none.
    The site's `locate` (site/js/modinfo.js) finds it the same way."""
    heads = [MAGIC + struct.pack(">HH", VERSION, size) for size in SIZES]
    found = [at for head in heads for at in _all(payload, head)]
    if not found:
        return None
    if len(found) > 1:
        raise ModInfoError("the /modinfo record appears twice")
    return found[0]


def _all(payload: bytes, head: bytes) -> list[int]:
    out, at = [], payload.find(head)
    while at >= 0:
        out.append(at)
        at = payload.find(head, at + 1)
    return out


def fill(payload: bytes, mods: list[tuple[str, int]], tag: str, commit: str, os: str) -> bytes:
    """PAYLOAD (MAIN OS, every mod applied) with its /modinfo record written; unchanged
    when it carries none."""
    start = locate(payload)
    if start is None:
        return payload
    size = size_at(payload, start)
    slots = mod_slots(size)
    if len(mods) > len(slots):
        raise ModInfoError(f"{len(mods)} mods; the record holds {len(slots)}")
    rec = bytearray(payload[start:start + size])
    rec[20:24] = bytes(4)
    rec[24:32] = _text(os, 8)
    rec[32:56] = _text(tag, 24)
    rec[56:68] = _text(commit, 12)
    rec[68:72] = bytes([len(mods), 0, 0, 0])
    for at in slots:
        rec[at:at + MOD_BYTES] = bytes(MOD_BYTES)
    for at, (mid, code) in zip(slots, mods):
        rec[at:at + MOD_BYTES] = _text(mid, 12) + struct.pack(">I", code)
    rec[252:256] = bytes(4)                           # 256: the hash, 512: reserved (248..251: the playable bounds)
    rec[size - 4:size] = bytes(4)                     # the hash
    out = bytearray(payload[:start] + bytes(rec) + payload[start + size:])
    image_id = xxh32(bytes(out))                      # the id and the hash still zero
    struct.pack_into(">I", out, start + 20, image_id)
    struct.pack_into(">I", out, start + size - 4, xxh32(bytes(out[start:start + size - 4])))
    return bytes(out)


def parse(rec: bytes) -> dict:
    """A /modinfo record -> its fields, and whether it checks out (magic, version, hash)."""
    if len(rec) < BYTES:
        raise ModInfoError(f"{len(rec)} bytes; a record is {BYTES}")
    magic, version, size, caps, pool_slots, pool_version, store_slots, kept, shown =         struct.unpack_from(">4sHHIHHHBB", rec)
    if size < BYTES or size > len(rec):
        size_ok = False
        size = min(max(size, 4), len(rec))
    else:
        size_ok = True
    count = rec[68]
    mods = []
    for at in mod_slots(size if size_ok else BYTES)[:count]:
        mods.append((rec[at:at + 12].split(b"\0")[0].decode("ascii"), struct.unpack_from(">I", rec, at + 12)[0]))

    def text(a, b):
        return rec[a:b].split(b"\0")[0].decode("ascii", "replace")
    return {"ok": magic == MAGIC and version >= VERSION and size_ok
                  and struct.unpack_from(">I", rec, size - 4)[0] == xxh32(rec[:size - 4]),
            "bytes": size, "name_kept": kept, "name_shown": shown,
            "version": version, "caps": caps,
            "capabilities": [name for bit, name in CAPS.items() if caps & bit],
            "pool_slots": pool_slots, "pool_version": pool_version, "store_slots": store_slots,
            "image_id": struct.unpack_from(">I", rec, 20)[0],
            "os": text(24, 32), "tag": text(32, 56), "commit": text(56, 68), "mods": mods,
            "filled": rec[MARKER_AT:MARKER_AT + len(MARKER)] != MARKER,
            "playable": ({"max_waves": rec[248], "min_points": 1 << rec[249], "max_points": 1 << rec[250],
                          "power_of_two": bool(rec[251] & 1)} if caps & 0x40 else None)}
