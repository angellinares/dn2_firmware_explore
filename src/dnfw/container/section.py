"""One ELE3 section: the 8-byte header in front of a compressed stream, and
the question of whether a section is compressed at all.

    [u32 stream length BE][u32 sum of the stream bytes BE][stream ...]

Not every section has this. On both Digitones `meta`, `updater` and `boot` --
and DN1's `blob` -- are stored raw, and the only reliable test is whether the
bytes depack. So a section is modelled as its **stored** bytes, exactly as they
sit in the container, and compression is something we discover rather than
assume. `dnfw build` must never recompress a section it could not depack.
"""

from dataclasses import dataclass

from ..codec import aplib, aplibpack

HEADER = 8


@dataclass(frozen=True)
class Section:
    """A section as the container holds it."""

    id: int
    dest: int
    stored: bytes

    @property
    def declared_length(self) -> int:
        """Stream length from the header. Meaningless on a raw section."""
        return int.from_bytes(self.stored[0:4], "big")

    @property
    def declared_sum(self) -> int:
        return int.from_bytes(self.stored[4:8], "big")

    @property
    def computed_sum(self) -> int:
        """Sum of the declared stream bytes, which is what the header claims."""
        end = min(HEADER + self.declared_length, len(self.stored))
        return sum(self.stored[HEADER:end]) & 0xFFFFFFFF

    @property
    def sum_ok(self) -> bool:
        return self.declared_sum == self.computed_sum

    def unpack(self) -> bytes | None:
        """The section content, or None if these bytes are not an aPLib stream.

        Truncation is tolerated: a raw section can decode a few plausible bytes
        before running out, so the caller distinguishes raw from compressed by
        None rather than by trusting a length field it has no reason to.
        """
        if len(self.stored) <= HEADER:
            return None
        try:
            out = aplib.depack(self.stored[HEADER:], allow_truncated=True)
        except aplib.DepackError:
            return None
        return out or None


def compress(section_id: int, dest: int, content: bytes) -> Section:
    """Build a compressed section from raw content, header included."""
    stream = aplibpack.pack(content)
    header = len(stream).to_bytes(4, "big") + (sum(stream) & 0xFFFFFFFF).to_bytes(4, "big")
    return Section(id=section_id, dest=dest, stored=header + stream)


def store_raw(section_id: int, dest: int, content: bytes) -> Section:
    """Build a section that is stored verbatim, for the sections that are."""
    return Section(id=section_id, dest=dest, stored=content)
