"""Assemble csrc/waverider/sharc/fft.asm into fft.json (WSL + selache), as the other objects are.

    python scripts/build_fft.py --assemble
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

SRC = ROOT / "csrc" / "waverider" / "sharc" / "fft.asm"
OUT = SRC.with_suffix(".json")
LOAD_SW = 0x16F800
TOOLCHAIN = "selache selas -proc ADSP-21569 (js216/selache 2b26d3b, GPL-3.0, WSL)"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--assemble", action="store_true")
    a = p.parse_args(argv)
    if not a.assemble:
        p.error("nothing to do without --assemble")
    import sharc_waverider_m3 as m3  # noqa: PLC0415
    with tempfile.TemporaryDirectory() as tmp:
        be, offsets = m3._selas(SRC, pathlib.Path(tmp))
    sha = hashlib.sha256(SRC.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    spec = {"source": SRC.relative_to(ROOT).as_posix(), "source_sha256": sha, "toolchain": TOOLCHAIN,
            "section": "seg_pmco", "load_sw": hex(LOAD_SW), "object_parcels_be": be.hex(),
            "instruction_offsets": offsets}
    OUT.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.name}: {len(offsets)} instructions, {len(be)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
