"""dnfw.mods.modinfo: the /modinfo record the build writes (docs/for-dnx-modinfo.md)."""

import struct

import pytest

from dnfw.mods import modinfo as MI
from dnfw.waverider.store import xxh32


def chunk_record(caps=0x37) -> bytes:
    """the record as csrc/wrstore/modinfo.c leaves it in the image, before the build"""
    head = MI.MAGIC + struct.pack(">HHIHHHBB", MI.VERSION, MI.BYTES, caps, 128, 2, 256, 15, 14) + bytes(4)
    return (head + MI.MARKER).ljust(MI.BYTES, b"\0")


def payload(caps=0x37) -> bytes:
    return b"\x11" * 1000 + chunk_record(caps) + b"\x22" * 500


def test_an_image_without_the_record_is_unchanged():
    raw = b"\x11" * 2000
    assert MI.locate(raw) is None and MI.fill(raw, [("lfo4", 1)], "t", "c", "1.11") == raw


def test_fill_writes_the_build_fields_and_keeps_the_chunks():
    raw = payload()
    out = MI.fill(raw, [("waverider", 0x1234), ("usbprobe", 0)], "wr-modinfo", "a97b3ca08f+", "1.11")
    assert len(out) == len(raw) and out[:1000] == raw[:1000] and out[1256:] == raw[1256:]
    info = MI.parse(out[1000:1256])
    assert info["ok"] and info["filled"]
    assert info["capabilities"] == ["store", "pool", "rename", "pool_cas", "page"]
    assert (info["pool_slots"], info["pool_version"], info["store_slots"]) == (128, 2, 256)
    assert info["mods"] == [("waverider", 0x1234), ("usbprobe", 0)]
    assert (info["os"], info["tag"], info["commit"]) == ("1.11", "wr-modinfo", "a97b3ca08f+")
    assert (info["name_kept"], info["name_shown"]) == (15, 14)


def test_the_image_id_is_the_payload_hash_with_the_id_and_the_hash_zeroed():
    out = MI.fill(payload(), [("waverider", 1)], "t", "c", "1.11")
    zeroed = bytearray(out)
    zeroed[1000 + 20:1000 + 24] = bytes(4)
    zeroed[1000 + 252:1000 + 256] = bytes(4)
    assert MI.parse(out[1000:1256])["image_id"] == xxh32(bytes(zeroed))


def test_two_builds_of_the_same_mods_differ_in_the_id():
    """tbl128 vs tbl128b: the same mods and tag, a different loader constant"""
    a = MI.fill(payload(), [("waverider", 1)], "wr-tbl128", "c", "1.11")
    other = bytearray(payload())
    other[10] ^= 1
    b = MI.fill(bytes(other), [("waverider", 1)], "wr-tbl128", "c", "1.11")
    assert MI.parse(a[1000:1256])["image_id"] != MI.parse(b[1000:1256])["image_id"]


def test_unknown_capability_bits_are_kept_and_ignored():
    out = MI.fill(payload(caps=0x37 | 0x8008), [], "t", "c", "1.11")
    info = MI.parse(out[1000:1256])
    assert info["ok"] and info["caps"] & 0x8000
    assert info["capabilities"] == ["store", "pool", "rename", "pool_cas", "page"]


def test_a_second_marker_is_refused():
    with pytest.raises(MI.ModInfoError):
        MI.locate(payload() + chunk_record())


def test_too_many_mods_are_refused():
    with pytest.raises(MI.ModInfoError):
        MI.fill(payload(), [(f"m{k}", 0) for k in range(MI.MAX_MODS + 1)], "t", "c", "1.11")


def test_a_bad_hash_reads_as_not_ok():
    out = bytearray(MI.fill(payload(), [], "t", "c", "1.11"))
    out[1000 + 40] ^= 1
    assert not MI.parse(bytes(out[1000:1256]))["ok"]


def test_a_longer_record_reads_with_its_hash_at_bytes_minus_4():
    """a later version appends fields: an old reader checks the hash where `bytes` puts it
    and reads the prefix it knows (DNX, rev 1 review)"""
    out = MI.fill(payload(), [("waverider", 7)], "t", "c", "1.11")
    rec = bytearray(out[1000:1256])
    grown = bytearray(rec[:252]) + bytes(512 - 252)
    struct.pack_into(">HH", grown, 4, 2, 512)
    struct.pack_into(">I", grown, 508, xxh32(bytes(grown[:508])))
    info = MI.parse(bytes(grown))
    assert info["ok"] and info["bytes"] == 512 and info["mods"] == [("waverider", 7)]
    assert not MI.parse(bytes(grown[:256]))["ok"]          # cut short: the stated length isn't there
