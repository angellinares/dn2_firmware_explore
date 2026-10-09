"""The frames the ColdFire's loader sends to the DSP (`csrc/waverider/loader.c`), as bytes.

One subject: what a load frame and the pool's request directory look like, so the two
halves can be checked against one description. The SHARC gate (`scripts/sharc_waverider_pool.py`)
feeds these frames to the DSP's handler; the ColdFire's own frames, captured in the
emulator, must equal them byte for byte.

A frame here is **as the ColdFire holds it** (16-bit words, big-endian, the 2,688
bytes at the send's buffer). The DSP reads 32-bit little-endian words, DSP word k
being ColdFire words 2k (low half) and 2k+1 (high half), so `dsp_view` (every 16-bit
word byte-swapped) is the frame as the DSP sees it (`docs/drive-load-command.md`).

The store keeps a table as int16 big-endian, frame-major (`docs/waverider-store.md`),
which is what the loader reads off the +Drive into a chunk's payload unchanged. In
DDR that lands as int16 little-endian in the same order, which build3.asm builds the
levels from (`dnfw.waverider.table3`).

Nothing here does I/O.
"""

from __future__ import annotations

import struct

from . import dsp

FRAME_BYTES = 2688
COMMAND = 4
CHUNK_SECTORS = 5                      # loader.c: one chunk is five +Drive sectors
CHUNK_BYTES = CHUNK_SECTORS * 512      # 2,560 B, 640 DSP words (the DSP takes up to 668)
SEQ_TAG = 0x4C440000                   # 'LD' in the sequence's high half


def frame(dest: int, payload_be: bytes, seq: int) -> bytes:
    """One load frame: DEST (a byte offset into the load area), the payload as the
    ColdFire holds it, and the 16-bit sequence SEQ (tagged as loader.c tags it)."""
    if len(payload_be) % 4 or not 0 < len(payload_be) <= 4 * dsp.LOAD_MAX_WORDS:
        raise ValueError(f"a payload of {len(payload_be)} bytes is not 1..668 whole words")
    words = len(payload_be) // 4
    total = sum(struct.unpack(f"<{words}I", dsp_view(payload_be))) & 0xFFFFFFFF
    s = SEQ_TAG | (seq & 0xFFFF)
    head = struct.pack(">8H", COMMAND, words, dest & 0xFFFF, dest >> 16,
                       s & 0xFFFF, s >> 16, total & 0xFFFF, total >> 16)
    out = head + payload_be
    return out + bytes(FRAME_BYTES - len(out))


def table_frames(dest: int, table_be: bytes, seq: int = 1) -> list[bytes]:
    """A table's bytes off the +Drive, sent from DEST in five-sector chunks, the
    sequence counting from SEQ."""
    out = []
    for k, at in enumerate(range(0, len(table_be), CHUNK_BYTES)):
        out.append(frame(dest + at, table_be[at:at + CHUNK_BYTES], seq + k))
    return out


def pool_directory(entries: dict[int, tuple[int, int]], generation: int, count: int = dsp.POOL_SLOTS) -> bytes:
    """The request directory build3.asm reads, from its word 1, as the ColdFire holds it:
    COUNT, GENERATION, 0, then COUNT words, entry j's frames | points << 16 (ENTRIES[j]
    = (frames, points); 0 for none). Its magic is sent apart, last (`magic_frame`)."""
    words = [count, generation, 0] + [(lambda g: g[0] | g[1] << 16 if g else 0)(entries.get(j)) for j in range(count)]
    return b"".join(struct.pack(">HH", w & 0xFFFF, w >> 16) for w in words)


def pool_address(j: int) -> int:
    """Pool entry j's table, as stored, in DDR: after the directory's 4 KB, 512 KiB each."""
    if not 0 <= j < dsp.POOL_SLOTS:
        raise ValueError(f"pool slot {j} is outside 0..{dsp.POOL_SLOTS - 1}")
    return dsp.POOL_RAW + j * dsp.POOL_RAW_BYTES


def magic_frame(magic: int, seq: int) -> bytes:
    """The request directory's word 0 alone: 0 before a fill rewrites the tables, the
    magic once the directory is whole."""
    return frame(dsp.POOL_DIR - dsp.LOAD_AREA[0], struct.pack(">HH", magic & 0xFFFF, magic >> 16), seq)


def directory_frames(entries: dict[int, tuple[int, int]], generation: int, seq: int) -> list[bytes]:
    """The request directory, sent last: its body from word 1, then its magic."""
    body = table_frames(dsp.POOL_DIR + 4 - dsp.LOAD_AREA[0], pool_directory(entries, generation), seq)
    return body + [magic_frame(dsp.POOL_MAGIC, seq + len(body))]


def sectors(frames: int, points: int) -> int:
    """The +Drive sectors pool.c reads for a table: whole sectors, the last one's tail
    whatever the slot holds past the table."""
    return (2 * frames * points + 511) // 512


def table_be(table: list[list[int]]) -> bytes:
    """An int16 table as the store keeps it: big-endian, frame-major."""
    return b"".join(struct.pack(">h", v) for f in table for v in f)


def dsp_view(data: bytes) -> bytes:
    """ColdFire bytes -> the DSP's view of them: every 16-bit word byte-swapped."""
    out = bytearray(data)
    out[0::2], out[1::2] = data[1::2], data[0::2]
    return bytes(out)
