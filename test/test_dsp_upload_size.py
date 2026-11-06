"""Section 7 must fit the ColdFire's uploader, and a span's zero tail goes as a fill block."""

import unittest

from dnfw.image import bootstream
from dnfw.waverider import dsp


class UploadSize(unittest.TestCase):
    def test_over_the_limit_is_refused(self):
        dsp.check_upload_size(bytes(dsp.STREAM_LIMIT))
        with self.assertRaises(dsp.DspError):
            dsp.check_upload_size(bytes(dsp.STREAM_LIMIT + 1))

    def test_zero_tail_becomes_a_fill_block(self):
        payload = b"\x01\x02\x03" + bytes(253)
        blocks = bootstream.walk(dsp.stream_blocks(0x282DD600, payload)).blocks
        self.assertEqual([(b.target, b.count, b.has_payload) for b in blocks],
                         [(0x282DD600, 4, True), (0x282DD604, 252, False)])
        self.assertLess(len(dsp.stream_blocks(0x282DD600, payload)), len(bootstream.block(0x282DD600, payload)))

    def test_the_memory_loaded_is_the_same(self):
        for payload in (bytes(512), b"\x07" * 512, b"\x07" * 500 + bytes(12), b"\x05" + bytes(1023)):
            self.assertEqual(bootstream.load_regions(dsp.stream_blocks(0x282DD600, payload)),
                             bootstream.load_regions(bootstream.block(0x282DD600, payload)))

    def test_every_count_is_a_multiple_of_4(self):
        """The silent table is 1,534 B: its block had a count of 1,534 (sharc_bootcheck H3)."""
        for payload in (b"\x07" * 1534, b"\x07" * 10 + bytes(1524), bytes(1534), b"\x07" * 3):
            blocks = bootstream.walk(dsp.stream_blocks(0x80600000, payload)).blocks
            self.assertTrue(all(b.count % 4 == 0 for b in blocks), [(b.target, b.count) for b in blocks])
            self.assertEqual(sum(b.count for b in blocks), len(payload) + -len(payload) % 4)

    def test_a_short_or_unaligned_tail_stays_in_the_payload(self):
        for at, payload in ((0x282DD600, b"\x07" * 500 + bytes(12)), (0x282DD602, b"\x07" + bytes(255))):
            self.assertEqual(dsp.stream_blocks(at, payload), bootstream.block(at, payload))


if __name__ == "__main__":
    unittest.main()
