"""Write csrc/ui/noise_env.h: the noise strip's envelope table
(dnfw.waverider.noise_glyph.env_steps) for the strip's width."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from dnfw.waverider import noise_glyph  # noqa: E402

WIDTH = 98          # page.c's strip, WAVE_X .. 121 (ui/noise_strip.h: the box's width)
OUT = pathlib.Path(__file__).resolve().parents[1] / "csrc" / "ui" / "noise_env.h"
OUT.write_text(noise_glyph.header(WIDTH), newline="\n")
print(OUT)
