"""Write the Formant's level table, src/dnfw/waverider/formant_levels.json.

    python scripts/waverider_formant_levels.py

`formant.level_exact` at the grid of `formant.level_table` (33 positions x 9 P1 points), each
float32 as its bit pattern, so the model and the DSP image read the same words. Takes about
10 seconds.
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.waverider import formant as F  # noqa: E402


def main() -> int:
    rows = [[f"{struct.unpack('<I', struct.pack('<f', v))[0]:08x}" for v in row] for row in F.level_table()]
    doc = {"what": "dnfw.waverider.formant.level_exact at positions j / 8 (rows) and P1 16k (columns), float32 bits",
           "levels": rows}
    F.LEVELS_FILE.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{F.LEVELS_FILE}: {len(rows)} x {len(rows[0])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
