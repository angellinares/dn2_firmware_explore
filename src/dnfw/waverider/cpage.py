"""Compile Waverider's C page renderer (`csrc/waverider/page.c`) for `coldfire.compose`.

One subject: the generated header and the source in, the linked bytes out. The
header (`wr_gen.h`: the control table and the wave spans) is written beside a
temporary copy of nothing else; `page.c` is compiled from the repository.

Only `scripts/gen_waverider_code.py` (and the test that replays it) need this and the
m68k GCC it drives; applying the mod reads the committed bytes.
"""

from __future__ import annotations

import pathlib
import tempfile

from ..patch import cbuild

CSRC = pathlib.Path(__file__).resolve().parents[3] / "csrc"
SOURCE = CSRC / "waverider" / "page.c"
# the machine-independent modules the page uses (owner, 2026-10-07: new code in reusable
# parts): synth/ the generators, ui/ the drawing
MODULES = (CSRC / "synth" / "noise_q16.c", CSRC / "synth" / "sub_q16.c", CSRC / "ui" / "noise_strip.c", CSRC / "ui" / "scope.c")
ENTRY = "wr_page_draw"
POLL = "wr_poll"                        # the UI loop's redraw test (coldfire.POLL_SITE)


def available() -> bool:
    return cbuild.available()


def compile_page(header: str, *, base: int) -> tuple[bytes, dict[str, int], int]:
    """-> (image, symbols, bss) of page.c and its MODULES linked at BASE, with HEADER as wr_gen.h."""
    with tempfile.TemporaryDirectory(prefix="wr_gen_", dir=SOURCE.parent) as tmp:
        (pathlib.Path(tmp) / "wr_gen.h").write_bytes(header.encode())
        linked = cbuild.build([SOURCE, *MODULES], base=base, entries=[ENTRY, POLL], include=[pathlib.Path(tmp)])
    return linked.image, linked.symbols, linked.bss
