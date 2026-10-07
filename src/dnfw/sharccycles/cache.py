"""A set-associative cache with LRU replacement, counting hits and misses.

The SHARC+ L1 caches (Programming Reference, "L1 Cache Parameters"): two-way,
512-bit (64-byte) lines, LRU. The DN2's stock start-up sizes each at 16 KB
(docs/waverider-dsp-silence.md), so 128 sets.
"""

from __future__ import annotations


class Cache:
    def __init__(self, size: int = 16 * 1024, line: int = 64, ways: int = 2) -> None:
        self.line, self.ways = line, ways
        self.sets = size // (line * ways)
        self._tags: list[list[int]] = [[] for _ in range(self.sets)]   # most recent last
        self.hits = self.misses = 0

    def access(self, address: int) -> bool:
        """Touch ADDRESS's line. True on a hit."""
        tag = address // self.line
        ways = self._tags[tag % self.sets]
        if tag in ways:
            ways.remove(tag)
            ways.append(tag)
            self.hits += 1
            return True
        if len(ways) == self.ways:
            ways.pop(0)
        ways.append(tag)
        self.misses += 1
        return False
