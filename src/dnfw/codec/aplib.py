"""aPLib-variant depacker: LZ77 with interlaced Elias-gamma codes.

Ported from `ap_depack` in mischa85/elektron-firmware-tool (`decompress.c`),
MIT, with thanks.

One deviation from the C, deliberate: the C codec is handed the section's
8-byte `[length][sum]` header and skips it. That header is a property of an
ELE3 *section*, not of the compression, so here it belongs to
`container.section` and this module sees only the compressed stream.
"""

OFFSET_BIAS = 767  # raw offset field; a raw value equal to this ends the stream
REUSE_GAMMA = 2  # gamma value that selects "reuse the last offset"
FAR_THRESHOLD = 3328  # beyond this: +1 length bonus, minimum match 3
MIN_MATCH = 2


class _Bits:
    """The interlaced bit reader. Control bits come from a tag byte that is
    refilled every eight bits; literal and offset bytes are read inline."""

    __slots__ = ("data", "pos", "tag", "exhausted")

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.tag = 0
        self.exhausted = False

    def byte(self) -> int:
        if self.pos >= len(self.data):
            self.exhausted = True
            return 0
        value = self.data[self.pos]
        self.pos += 1
        return value

    def bit(self) -> int:
        self.tag = (self.tag << 1) & 0xFFFFFFFF
        if (self.tag & 0xFF) == 0:
            value = self.byte()
            self.tag = (value << 1) | 1
            return (value >> 7) & 1
        return (self.tag >> 8) & 1

    def gamma(self) -> int:
        value = 1
        while True:
            value = (value << 1) + self.bit()
            if self.bit():
                break
            if self.exhausted or value > 0x02000000:
                break
        return value


class DepackError(ValueError):
    """The stream is not a valid aPLib stream, or ran out mid-token."""


def depack(stream: bytes, allow_truncated: bool = False) -> bytes:
    """Decompress one aPLib stream (no section header).

    `allow_truncated` returns whatever was produced before the input ran out,
    which is how a caller can probe whether a section is compressed at all
    without having to trust its declared length.
    """
    bits = _Bits(stream)
    out = bytearray()
    last_offset = 1

    while True:
        if bits.exhausted:
            return _truncated(out, allow_truncated)

        if bits.bit():  # literal
            if bits.pos >= len(bits.data):
                return _truncated(out, allow_truncated)
            out.append(bits.data[bits.pos])
            bits.pos += 1
            continue

        gamma = bits.gamma()
        if gamma == REUSE_GAMMA:
            offset = last_offset
        else:
            # Masked to 32 bits on purpose: the end-of-stream token is a gamma
            # of 0x1000002 followed by 0xFF, which only decodes to the bias
            # because the C computes it in a uint32 and the high bits fall off.
            offset = ((gamma << 8) + bits.byte()) & 0xFFFFFFFF
            if bits.exhausted:
                return _truncated(out, allow_truncated)
            if offset == OFFSET_BIAS:
                break  # end of stream
            offset -= OFFSET_BIAS
            last_offset = offset

        high, low = bits.bit(), bits.bit()
        short = 2 * high + low
        length = short if short else bits.gamma() + 2
        if bits.exhausted:
            return _truncated(out, allow_truncated)
        if offset > FAR_THRESHOLD:
            length += 1

        count = length + 1
        # `offset <= 0` rather than `== 0`: a raw offset below the bias makes
        # this negative here, where the C wraps it to a huge unsigned value and
        # catches it on the range test instead. Without this a non-aPLib
        # section reads off the end of its own output.
        if offset <= 0 or len(out) < offset:
            raise DepackError(f"offset {offset} outside the {len(out)} bytes emitted so far")
        src = len(out) - offset
        for _ in range(count):  # overlapping copy: a run can read what it just wrote
            out.append(out[src])
            src += 1

    if not out and not allow_truncated:
        raise DepackError("stream decoded to nothing")
    return bytes(out)


def _truncated(out: bytearray, allow: bool) -> bytes:
    if not allow:
        raise DepackError("input ran out mid-token")
    return bytes(out)
