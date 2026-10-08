"""dn2scope_ring.analyse: a torn read's overwritten blocks are left out."""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import dn2scope_ring as sr  # noqa: E402


def ring_blob(w: int, sample, overwritten: int = 0) -> bytes:
    """A ring whose write count is W, holding sample(t) for the 2,048 samples before W;
    the OVERWRITTEN oldest positions hold samples from after W (a read the ISR overtook)."""
    ring = [0] * sr.RING
    for t in range(w - sr.RING, w + overwritten):
        ring[t % sr.RING] = sample(t)
    data = b"".join(v.to_bytes(2, "big", signed=True) for v in ring)
    return w.to_bytes(4, "big") + data


def test_a_torn_read_shows_a_seam_and_the_write_count_removes_it():
    sine = lambda t: int(8000 * math.sin(2 * math.pi * t / 97.3))
    w = 32 * 10_000
    torn = ring_blob(w, lambda t: sine(t + 5000) if t >= w else sine(t), overwritten=6 * 32)
    seam = sr.analyse(torn)
    assert seam["big_boundary"] >= 1                     # the seam, at a block start
    clean = sr.analyse(torn, w_after=w + 6 * 32)
    assert clean["torn"] == 7 * 32
    assert clean["big_boundary"] == 0 and clean["repeated_blocks"] == 0
