"""aPLib-variant packer: produces a stream `codec.aplib.depack` accepts.

The bit-level encoding -- literal, match, offset reuse, gamma codes, the far
threshold, the end-of-stream token -- is ported exactly from `ap_pack` in
mischa85/elektron-firmware-tool (`compress.c`), MIT, with thanks. So is the
cost model (`_gamma_cost`, `match_cost`), which is what makes the parse
decisions here cost-based rather than guesswork.

**The parse strategy is deliberately not the same.** `compress.c` runs a
cost-optimal forward dynamic program over every position with a 2,048-deep
match chain. That is the right answer in C and unreachable in Python: the
Digitone II MAIN OS section is 3,085,696 bytes. This module uses greedy
matching with a one-position lazy lookahead, decided by the same cost function.

It costs nothing measurable. Against the sections Elektron ship (2026-09-07):

    DN2 DSP      30,302 B raw ->    16,131 vs   16,160 stock   -0.2%
    DN2 MAIN OS 3,085,696 B raw -> 1,093,366 vs 1,093,808      -0.0%
    DN2 blob      833,060 B raw ->   596,466 vs   600,148      -0.6%
    DN1 DSP      28,766 B raw ->    15,702 vs   15,764 stock   -0.4%
    DN1 MAIN OS 2,420,912 B raw ->   923,519 vs   925,768      -0.2%

Every section comes out smaller than stock, so a rebuild never needs more flash
than the image it replaces. MAIN OS packs in about 15 seconds.
"""

from .aplib import FAR_THRESHOLD, MIN_MATCH, OFFSET_BIAS, REUSE_GAMMA

MAX_MATCH = 2048
LITERAL_BITS = 9  # 1 control bit + 8 data bits
DEFAULT_CHAIN_DEPTH = 32

# Two, not three or four. The minimum match length in this format is two, so a
# wider hash key silently discards every short match: measured on the Digitone
# II DSP section, a 4-byte key costs 12.4% and a 3-byte key 3.2% against stock,
# while a 2-byte key at depth 32 comes out 0.2% *smaller* than Elektron ship.
_HASH_BYTES = 2


class _Writer:
    """Interlaced bit/byte output. Control bits accumulate into a tag byte that
    is reserved in the stream at the moment its first bit is written, so bits
    and inline bytes stay in the order the depacker expects."""

    __slots__ = ("out", "tag_pos", "tag_bits")

    def __init__(self) -> None:
        self.out = bytearray()
        self.tag_pos = -1
        self.tag_bits = 0

    def bit(self, value: int) -> None:
        if self.tag_bits == 0:
            self.tag_pos = len(self.out)
            self.out.append(0)
            self.tag_bits = 8
        if value:
            self.out[self.tag_pos] |= 1 << (self.tag_bits - 1)
        self.tag_bits -= 1

    def byte(self, value: int) -> None:
        self.out.append(value)

    def gamma(self, value: int) -> None:
        width = value.bit_length()
        for i in range(width - 2, -1, -1):
            self.bit((value >> i) & 1)
            self.bit(1 if i == 0 else 0)

    def literal(self, value: int) -> None:
        self.bit(1)
        self.byte(value)

    def match(self, offset: int, length: int, last_offset: int) -> int:
        self.bit(0)
        if offset == last_offset:
            self.gamma(REUSE_GAMMA)
        else:
            raw = offset + OFFSET_BIAS
            self.gamma(raw >> 8)
            self.byte(raw & 0xFF)
            last_offset = offset
        base = length - 1 - (1 if offset > FAR_THRESHOLD else 0)
        if base <= 3:
            self.bit(base >> 1)
            self.bit(base & 1)
        else:
            self.bit(0)
            self.bit(0)
            self.gamma(base - 2)
        return last_offset

    def end(self) -> None:
        """End of stream: a match whose raw offset field decodes to the bias."""
        self.bit(0)
        self.gamma(0x1000002)
        self.byte(0xFF)


def _gamma_cost(value: int) -> int:
    return 2 * (value.bit_length() - 1)


def match_cost(offset: int, length: int, last_offset: int) -> int:
    """Cost in bits of encoding this match, by the compress.c model."""
    bits = 1 + (2 if offset == last_offset else _gamma_cost((offset + OFFSET_BIAS) >> 8) + 8)
    base = length - 1 - (1 if offset > FAR_THRESHOLD else 0)
    bits += 2 if base <= 3 else 2 + _gamma_cost(base - 2)
    return bits


def _min_match(offset: int) -> int:
    return MIN_MATCH + 1 if offset > FAR_THRESHOLD else MIN_MATCH


def _run(data: bytes, a: int, b: int, cap: int) -> int:
    """Common-prefix length of data[a:] and data[b:], capped at `cap`.

    Compared in 32-byte slices first -- a slice comparison runs at C speed,
    which is what makes this usable on a multi-megabyte image -- then refined
    byte by byte. Overlapping matches are fine: the depacker copy reads what it
    has just written, and equality on the original array is exactly the
    condition that makes that reproduce the original.
    """
    n = 0
    while n + 32 <= cap and data[a + n : a + n + 32] == data[b + n : b + n + 32]:
        n += 32
    while n < cap and data[a + n] == data[b + n]:
        n += 1
    return n


def _best(
    data: bytes,
    i: int,
    cap: int,
    head: dict,
    prev: list,
    last_offset: int,
    chain_depth: int,
):
    """Best (offset, length, cost) at position `i`, or (0, 0, 0) for none.

    Longest wins, ties broken by cost -- so among equally long matches the one
    that reuses the last offset, or sits nearer, is preferred.
    """
    best_offset = best_length = best_cost = 0
    best_key = None

    def consider(offset: int, length: int) -> None:
        nonlocal best_offset, best_length, best_cost, best_key
        if length < _min_match(offset):
            return
        cost = match_cost(offset, length, last_offset)
        key = (-length, cost)
        if best_key is None or key < best_key:
            best_offset, best_length, best_cost, best_key = offset, length, cost, key

    if 0 < last_offset <= i:
        consider(last_offset, _run(data, i - last_offset, i, cap))

    if i + _HASH_BYTES <= len(data):
        candidate = head.get(data[i : i + _HASH_BYTES], -1)
        depth = chain_depth
        while candidate >= 0 and depth:
            consider(i - candidate, _run(data, candidate, i, cap))
            if best_length >= cap:
                break
            candidate = prev[candidate]
            depth -= 1

    return best_offset, best_length, best_cost


def pack(data: bytes, chain_depth: int = DEFAULT_CHAIN_DEPTH) -> bytes:
    """Compress `data` into an aPLib stream (no section header).

    `chain_depth` trades build time for size: how many earlier positions with
    the same 2-byte prefix are considered at each step.
    """
    writer = _Writer()
    size = len(data)
    if size == 0:
        writer.end()
        return bytes(writer.out)

    head: dict = {}
    prev = [-1] * size
    last_offset = 1
    i = 0

    while i < size:
        cap = min(size - i, MAX_MATCH)
        offset, length, cost = _best(data, i, cap, head, prev, last_offset, chain_depth)

        if length and i + 1 < size:
            # Lazy: is a literal here plus the next position match cheaper per
            # byte than taking this match now?
            next_cap = min(size - i - 1, MAX_MATCH)
            _, alt_length, alt_cost = _best(
                data, i + 1, next_cap, head, prev, last_offset, chain_depth
            )
            if alt_length and (LITERAL_BITS + alt_cost) * length < cost * (1 + alt_length):
                length = 0

        if length:
            last_offset = writer.match(offset, length, last_offset)
            step = length
        else:
            writer.literal(data[i])
            step = 1

        limit = min(i + step, size - _HASH_BYTES + 1)
        for k in range(i, limit):
            key = data[k : k + _HASH_BYTES]
            prev[k] = head.get(key, -1)
            head[key] = k
        i += step

    writer.end()
    return bytes(writer.out)
