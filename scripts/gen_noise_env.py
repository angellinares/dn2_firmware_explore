"""Write csrc/waverider/noise_env.h: page 3's noise glyph envelope table
(dnfw.waverider.noise_glyph.env_steps) for the strip's width."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from dnfw.waverider import noise_glyph  # noqa: E402

WIDTH = 98          # page.c's strip, WAVE_X .. 121
OUT = pathlib.Path(__file__).resolve().parents[1] / "csrc" / "waverider" / "noise_env.h"
OUT.write_text(noise_glyph.header(WIDTH), newline="\n")
print(OUT)
