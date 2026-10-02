"""A tunnel mark is stored turned over, so it shows the right way up.

The intro's copy maps its source bitmap to the panel flipped vertically
(`docs/display-path.md`); `mark_from_pixels` stores an upright mark that way, as
the animations already store their frames. Filmed under the emulator and flashed
on 2026-10-02 (`docs/flashing.md`).
"""

from dnfw.cli import mods as cli
from dnfw.mods import bootscreen

H = bootscreen.H


def test_top_left_is_stored_bottom_left():
    assert bootscreen.mark_from_pixels({(0, 0)}) == bootscreen.image_from_pixels({(0, H - 1)})


def test_is_image_from_pixels_turned_over():
    lit = {(x, y) for x in range(0, 128, 3) for y in range(0, 20) if (x + y) % 5 == 0}
    assert bootscreen.mark_from_pixels(lit) == bootscreen.image_from_pixels(
        {(x, H - 1 - y) for x, y in lit})


def test_the_cli_builds_tunnel_marks_with_it(tmp_path, monkeypatch):
    """`--boot-image` with the tunnel: the mark reaches `apply` turned over."""
    pgm = tmp_path / "dot.pgm"
    pix = bytearray(128 * 64)
    pix[0] = 255                                     # (0, 0), top left
    pgm.write_bytes(b"P5\n128 64\n255\n" + bytes(pix))
    seen = {}
    monkeypatch.setattr(bootscreen, "apply", lambda fw, images, **kw: seen.setdefault("images", images))

    class Args:
        boot_image = [pgm]
        boot_animation = "tunnel"
        boot_invert = False
        boot_slow, boot_fast, boot_rush, boot_stop = 4, 3, 48, 72
        tunnel = list(bootscreen.STOCK_TUNNEL)

    cli._apply_bootscreen(bootscreen, None, Args)
    assert seen["images"] == [bootscreen.image_from_pixels({(0, H - 1)})]
