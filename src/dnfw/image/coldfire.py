"""A decompressed section as the CPU sees it: address arithmetic against the
load destination the ELE3 section table gives.

Both Digitones load MAIN OS at 0x40000400, which is also where octabam
independently places the Octatrack's -- one Elektron platform, one convention.
The destination is read from the image rather than assumed, so this module
carries no magic base address.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LoadedImage:
    """Section content plus the address it is loaded at."""

    dest: int
    content: bytes

    @property
    def end(self) -> int:
        """One past the last address the section occupies."""
        return self.dest + len(self.content)

    def contains(self, address: int, length: int = 1) -> bool:
        return self.dest <= address and address + length <= self.end

    def offset_of(self, address: int) -> int:
        if not self.contains(address):
            raise ValueError(f"0x{address:08x} is outside 0x{self.dest:08x}..0x{self.end:08x}")
        return address - self.dest

    def address_of(self, offset: int) -> int:
        if not 0 <= offset < len(self.content):
            raise ValueError(f"offset {offset} is outside the {len(self.content)}-byte section")
        return self.dest + offset

    def read(self, address: int, length: int) -> bytes:
        if not self.contains(address, length):
            raise ValueError(f"0x{address:08x}+{length} runs past the end of the section")
        start = self.offset_of(address)
        return self.content[start : start + length]
