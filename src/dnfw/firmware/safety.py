"""The safety checklist of a patched Digitone II image, against the stock image it came from.

One subject: producing the checklist. `cli.check` prints it and `site/js/safety.js` is its
twin for the website's Check page (`test/test_js_safety_matches_cli.py` holds the two
together). Each item is pass, warn, fail, info or skip. A check that cannot read its part
of the image fails; it never stops the list. A checklist never calls an image
safe: it says what it found, and what it does not check (`NOT_CHECKED`).

The items, in order:

- **file**: every integrity field of the patched file (`verify`): what the instrument checks
  before it writes anything. A file that fails here stops the list: its sections cannot be
  read reliably. So does a stock file that is not a known one, or a different layout.
- **stock**: the stock file is Elektron's Digitone II OS 1.11, by the SHA-256 of each section's
  content (`KNOWN`). Hashes only: no Elektron bytes are kept here.
- **layout**: the patched file has the stock file's version, sections and load addresses.
- **recovery**: every section other than MAIN OS (3) and the DSP image (7) is the stock one,
  byte for byte. The bootstrap (2) holds the Early Start-up Menu's receiver, so a unit can
  always take the stock OS again.
- **edits**: the changed runs inside stock's MAIN OS, listed by address (info). A mod's hook
  must change some stock bytes.
- **area**: bytes past stock's MAIN OS must be a DNFW area that parses, with the platform
  loader installed.
- **ram**: where the loader puts each part of the area at run time. Every range must lie
  above stock's RAM (its image, BSS and uncached DMA section, to `STOCK_RAM_END`) and below
  the stack's reserve, and no two may overlap.
- **dma**: the addresses in stock's DMA section that the new bytes name, under either
  address (as `mods.ramcheck` scans them). Writing there damages saved projects (docs/lfo4-state-memory.md).
  A mod may read stock's buffer on purpose, so this warns and does not fail. A word of four
  printable ASCII characters is text, not an address, and is left out.
- **dsp**: the changed runs of the DSP image (info): nothing here checks the DSP's memory.
- **record**: the /modinfo record, when there is one: its hash, and its image id against
  MAIN OS.
- **rebuild**: the record's mods applied to the stock file give this image, byte for byte,
  but for the record itself and the order of the area's chunks (`_canonical`). The caller passes the rebuild (`rebuild`): the CLI and the
  site each apply mods their own way.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from ..container import ele3
from ..mods import modinfo, platform, ramcheck
from ..patch import area
from . import compare
from .model import Firmware
from .verify import verify

MAIN_OS, DSP = 3, 7
KNOWN = {
    "1.11": {
        2: "038aa5d188af120f3ca2ce4299147952c505f6bc2e8d24c2d1f16db8c21a9d62",
        3: "57b06a7960b7c3dc9803bde6b31896b89a2fbdcc404a932ff503f3856d4d7a61",
        4: "951ced17c9e9d9421c6d910eb1201726d13498c2cc64f33e7d4767a4771419fa",
        5: "becc493e90833ee87cde7a942db1faad859b2cf3c662eb225e1070f199125fab",
        7: "336e340aa0cdcd34e314cfa44849f709a3134f6bd4cd57dfc7e15702c83115e2",
        8: "6943b2f27773f40f1e7857ea6fa7a121269e930bd403098e6b6c00002327dc20",
    },
}
STOCK_RAM_END = ramcheck.STOCK_DMA[1]                    # stock's image, BSS and DMA section end here
STACK_FLOOR = ramcheck.STACK_TOP - ramcheck.STACK_RESERVE
NOT_CHECKED = (
    "RAM that a mod uses without an area chunk: the image does not declare it.",
    "Whether the new code reads or writes the addresses it names.",
    "The DSP's memory: which parts of it the stock DSP code uses.",
    "Whether the new code runs correctly: only the emulator and the instrument can show that.",
)
SHOWN = 8                                                # runs listed by address; the rest are counted


@dataclass(frozen=True)
class Item:
    key: str
    title: str
    status: str            # pass, warn, fail, info, skip
    detail: str


def check(patched: Firmware, stock: Firmware, rebuild=None) -> list[Item]:
    """The checklist of PATCHED against STOCK. REBUILD(stock, mods, tag) -> every section's
    content ({id: bytes}), or a string that says why it cannot rebuild."""
    items = [_guard("file", "The file is intact", _file, patched)]
    if items[0].status != "pass":
        return items                                  # its sections cannot be trusted to read
    version = _guard("stock", "The stock file is a known Digitone II OS", _stock, stock)
    items.append(version)
    if version.status != "pass":
        return items
    layout = _guard("layout", "The same OS version and sections", _layout, patched, stock)
    items.append(layout)
    if layout.status != "pass":
        return items
    ours, theirs = _contents(patched), _contents(stock)
    main, base = ours[MAIN_OS], theirs[MAIN_OS]
    items.append(_guard("recovery", "The bootstrap and the other recovery sections are stock",
                        _recovery, ours, theirs))
    items.append(_runs("edits", "Changes inside stock's MAIN OS", base, main[:len(base)], platform.BASE))
    items += _guard("area", "The added code is a DNFW area", _area, main, base)
    items.append(_runs("dsp", "Changes in the DSP image", theirs[DSP], ours[DSP][:len(theirs[DSP])], 0,
                       len(ours[DSP]) - len(theirs[DSP])))
    try:
        record, mods, tag = _record(main)
    except Exception as exc:                                    # noqa: BLE001
        record, mods, tag = Item("record", "The /modinfo record checks out", "fail", f"unreadable: {exc}"), [], ""
    items.append(record)
    items.append(_guard("rebuild", "The record's mods rebuild this image exactly",
                        _rebuild, ours, stock, mods, tag, rebuild))
    return items


def _guard(key: str, title: str, fn, *args):
    """FN(*ARGS), or a fail when the image is too malformed for it to read: never a crash."""
    try:
        return fn(*args)
    except Exception as exc:                                    # noqa: BLE001
        item = Item(key, title, "fail", f"this part of the image could not be read: {exc}")
        return [item] if key == "area" else item


def _contents(firmware: Firmware) -> dict[int, bytes]:
    return {s.id: compare.content(s)[0] for s in firmware.container.sections}


def _file(patched: Firmware) -> Item:
    bad = [c for c in verify(patched).checks if not c.ok]
    if bad:
        return Item("file", "The file is intact", "fail", "; ".join(f"{c.name}: {c.detail}" for c in bad))
    if not patched.signed:
        return Item("file", "The file is intact", "fail", "it is not signed, so it is not a Digitone II OS file")
    return Item("file", "The file is intact", "pass", "every checksum and the signature verify")


def _stock(stock: Firmware) -> Item:
    title = "The stock file is a known Digitone II OS"
    have = {s.id: hashlib.sha256(compare.content(s)[0]).hexdigest() for s in stock.container.sections}
    for version, want in KNOWN.items():
        if have == want:
            return Item("stock", title, "pass", f"Digitone II OS {version}, every section as Elektron ships it")
    return Item("stock", title, "fail",
                f"its sections match no known stock OS ({', '.join(KNOWN)}): only these are supported")


def _layout(patched: Firmware, stock: Firmware) -> Item:
    title = "The same OS version and sections"
    a, b = patched.container, stock.container
    if a.version != b.version or a.build != b.build:
        return Item("layout", title, "fail", f"version {a.version} build {a.build}, stock {b.version} build {b.build}")
    ids = lambda c: [(s.id, s.dest) for s in c.sections]       # noqa: E731
    if ids(a) != ids(b):
        return Item("layout", title, "fail", "the sections or their load addresses differ from stock's")
    return Item("layout", title, "pass", f"version {a.version}, {len(a.sections)} sections at stock's addresses")


def _recovery(ours: dict[int, bytes], theirs: dict[int, bytes]) -> Item:
    title = "The bootstrap and the other recovery sections are stock"
    other = sorted(k for k in theirs if k not in (MAIN_OS, DSP))
    changed = [k for k in other if ours[k] != theirs[k]]
    names = lambda ks: ", ".join(f"{k} ({ele3.name(k)})" if ele3.name(k) != "?" else str(k)   # noqa: E731
                                 for k in ks)
    if changed:
        return Item("recovery", title, "fail", f"changed: {names(changed)}")
    return Item("recovery", title, "pass", f"identical to stock: {names(other)}")


def _runs(key: str, title: str, base: bytes, new: bytes, va: int, grown: int = 0) -> Item:
    runs = []
    i, n = 0, min(len(base), len(new))
    while i < n:
        if base[i] == new[i]:
            i += 1
            continue
        j = i
        while j < n and base[j] != new[j]:
            j += 1
        runs.append((i, j))
        i = j
    if not runs and grown <= 0:
        return Item(key, title, "info", "none")
    total = sum(j - i for i, j in runs)
    shown = ", ".join(f"{va + i:#010x} ({j - i} B)" for i, j in runs[:SHOWN])
    more = f", and {len(runs) - SHOWN} more" if len(runs) > SHOWN else ""
    detail = f"{len(runs)} changed runs, {total:,} bytes" + (f": {shown}{more}" if runs else "")
    if grown > 0:
        detail += f"; {grown:,} bytes added at the end"
    return Item(key, title, "info", detail)


def _area(main: bytes, base: bytes) -> list[Item]:
    title = "The added code is a DNFW area"
    if len(main) == len(base):
        return [Item("area", title, "info", "nothing is added past stock's MAIN OS"),
                Item("ram", "Run-time RAM stays out of stock's", "skip", "no area"),
                _dma(main, base, [])]
    if len(main) < len(base):
        return [Item("area", title, "fail", "MAIN OS is shorter than stock's")]
    if not platform.installed(main):
        return [Item("area", title, "fail", "bytes are added past MAIN OS, but the platform loader is not installed")]
    blob = bytes(main[len(base):])
    try:
        chunks = area.parse(blob)
    except area.AreaError as exc:
        return [Item("area", title, "fail", str(exc))]
    kinds = ", ".join(sorted({c.decode("ascii", "replace") for c, _ in chunks}))
    items = [Item("area", title, "pass", f"{len(chunks)} chunks ({kinds}), {len(blob):,} bytes")]
    ranges = _ranges(blob)
    items.append(_ram(ranges))
    items.append(_dma(main, base, chunks))
    return items


def _ranges(blob: bytes) -> list[tuple[int, int, str]]:
    """Where the loader puts the area: the header and data chunks at RUNTIME_VA + their offset,
    each CODE chunk's image and BSS at its own load address."""
    count = struct.unpack_from(">I", blob, 8)[0]
    out = [(area.RUNTIME_VA, area.RUNTIME_VA + 12 + 12 * count, "the area's header")]
    for k in range(count):
        cid, offset, length = struct.unpack_from(">4sII", blob, 12 + 12 * k)
        if cid == area.CODE:
            code = area.CodeChunk.unpack(blob[offset:offset + length])
            out.append((code.load, code.load + len(code.image) + code.bss, f"CODE at {code.load:#010x}"))
        else:
            name = cid.decode("ascii", "replace")
            out.append((area.RUNTIME_VA + offset, area.RUNTIME_VA + offset + length, f"{name} data"))
    return out


def _cached(a: int) -> int:
    return a - ramcheck.WINDOW if ramcheck.STACK_TOP <= a < ramcheck.STACK_TOP + ramcheck.WINDOW else a


def _ram(ranges: list[tuple[int, int, str]]) -> Item:
    title = "Run-time RAM stays out of stock's"
    bad = []
    for lo, hi, what in ranges:
        lo, hi = _cached(lo), _cached(hi)
        if lo < STOCK_RAM_END:
            bad.append(f"{what} ({lo:#010x}..{hi:#010x}) is inside stock's RAM, which ends at {STOCK_RAM_END:#010x}")
        elif hi > STACK_FLOOR:
            bad.append(f"{what} ({lo:#010x}..{hi:#010x}) reaches the stack's reserve at {STACK_FLOOR:#010x}")
    spans = sorted((_cached(lo), _cached(hi), w) for lo, hi, w in ranges if hi > lo)
    for (a_lo, a_hi, a), (b_lo, b_hi, b) in zip(spans, spans[1:]):
        if b_lo < a_hi:
            bad.append(f"{a} and {b} overlap at {b_lo:#010x}")
    if bad:
        return Item("ram", title, "fail", "; ".join(bad))
    lo, hi = min(r[0] for r in spans), max(r[1] for r in spans)
    return Item("ram", title, "pass", f"{len(spans)} ranges, all in {lo:#010x}..{hi:#010x}, none overlapping")


def _text(v: int) -> bool:
    return all(0x20 <= b <= 0x7E for b in v.to_bytes(4, "big"))


def _named(base: bytes, main: bytes, chunks, lo: int, hi: int) -> list[tuple[int, int]]:
    """(where, value) for each word in LO..HI that the new bytes name and stock's do not: in the
    changed runs of stock's MAIN OS (a word may straddle a run) and in every CODE chunk's image.
    `mods.ramcheck.named` reads the area through the platform, which refuses a malformed one;
    a checklist must report it instead."""
    found = []
    n = len(base)
    i = 0
    while i < n:
        if base[i] == main[i]:
            i += 1
            continue
        j = i
        while j < n and base[j] != main[j]:
            j += 1
        for at in range(max(0, i - 3) & ~1, min(n, j + 3) - 3, 2):
            v = struct.unpack_from(">I", main, at)[0]
            if lo <= v < hi and not lo <= struct.unpack_from(">I", base, at)[0] < hi:
                found.append((platform.BASE + at, v))
        i = j
    for cid, data in chunks:
        if cid == area.CODE:
            code = area.CodeChunk.unpack(data)
            found += [(code.load + at, v) for at in range(0, len(code.image) - 3, 2)
                      if lo <= (v := struct.unpack_from(">I", code.image, at)[0]) < hi]
    return found


def _dma(main: bytes, base: bytes, chunks) -> Item:
    title = "No new reference to stock's DMA buffers"
    lo, hi = ramcheck.STOCK_DMA
    w = ramcheck.WINDOW
    found = {(at, v) for at, v in _named(base, main, chunks, lo, hi) + _named(base, main, chunks, lo + w, hi + w)
             if not _text(v)}
    if not found:
        return Item("dma", title, "pass", "the new bytes name no address in stock's DMA section")
    shown = ", ".join(f"{at:#010x} names {v:#010x}" for at, v in sorted(found)[:SHOWN])
    return Item("dma", title, "warn",
                f"{len(found)} places name stock's DMA section ({shown}). A mod may read it on "
                "purpose; writing there damages saved projects")


def _record(main: bytes) -> tuple[Item, list[str], str]:
    title = "The /modinfo record checks out"
    try:
        at = modinfo.find(main)
    except modinfo.ModInfoError as exc:
        return Item("record", title, "fail", str(exc)), [], ""
    if at is None:
        return Item("record", title, "skip", "this image has no /modinfo record"), [], ""
    rec = bytes(main[at:at + modinfo.BYTES])
    info = modinfo.parse(rec)
    if not info["filled"]:
        return Item("record", title, "warn", "the record is present but was never filled"), [], ""
    if not info["ok"]:
        return Item("record", title, "fail", "the record's hash does not match its bytes"), [], ""
    zeroed = bytearray(main)
    zeroed[at + 20:at + 24] = bytes(4)
    zeroed[at + 252:at + 256] = bytes(4)
    if modinfo.xxh32(bytes(zeroed)) != info["image_id"]:
        return Item("record", title, "fail", "the record's image id does not match MAIN OS: "
                    "something changed MAIN OS after the record was written"), [], ""
    mods = [m for m, _ in info["mods"]]
    return (Item("record", title, "pass", f"tag {info['tag']}, build {info['commit']}, mods: {', '.join(mods)}"),
            mods, info["tag"])


def _canonical(main: bytes, base_length: int):
    """MAIN OS as (the stock part, the area's chunks sorted), each /modinfo record zeroed.

    The record is metadata: the CLI and the site write different tags, commits and code hashes
    into it, and `_record` checks it apart. The chunks are a set: a site user may apply lfo4
    before a mod the CLI applies first, and nothing at run time reads their order (as
    test_js_build_matches_cli compares them)."""
    if len(main) <= base_length:
        return bytes(main), []
    chunks = []
    for cid, data in area.parse(bytes(main[base_length:])):
        at = modinfo.find(data)
        if at is not None:
            data = data[:at] + bytes(modinfo.BYTES) + data[at + modinfo.BYTES:]
        chunks.append((cid, data))
    return bytes(main[:base_length]), sorted(chunks)


def _rebuild(ours: dict[int, bytes], stock: Firmware, mods: list[str], tag: str, rebuild) -> Item:
    title = "The record's mods rebuild this image exactly"
    if not mods:
        return Item("rebuild", title, "skip", "no mods list to rebuild from")
    if rebuild is None:
        return Item("rebuild", title, "skip", "no rebuild was asked for")
    got = rebuild(stock, mods, tag)
    if isinstance(got, str):
        return Item("rebuild", title, "skip", got)
    base = len(compare.content(stock.container.find(MAIN_OS))[0])
    same = (sorted(got) == sorted(ours)
            and _canonical(got[MAIN_OS], base) == _canonical(ours[MAIN_OS], base)
            and all(got[k] == ours[k] for k in ours if k != MAIN_OS))
    if same:
        return Item("rebuild", title, "pass", f"stock plus {', '.join(mods)} gives the same image, section for section")
    return Item("rebuild", title, "warn",
                f"stock plus {', '.join(mods)} gives a different image. The file may come from another "
                "version of the patcher, have options set, or have changes the record does not list")
