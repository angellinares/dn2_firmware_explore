"""Assemble the stage 3 FFT sources (fft.asm, rfft.asm) into their .json (WSL + selache), as the other objects are.

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

SOURCES = {"fft": 0x16F800, "rfft": 0x16F900, "fft2": 0x16FC00}   # name -> load sw
TOOLCHAIN = "selache selas -proc ADSP-21569 (js216/selache 2b26d3b, GPL-3.0, WSL)"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--assemble", action="store_true")
    a = p.parse_args(argv)
    if not a.assemble:
        p.error("nothing to do without --assemble")
    import sharc_waverider_m3 as m3  # noqa: PLC0415
    for name, load_sw in SOURCES.items():
        src = ROOT / "csrc" / "waverider" / "sharc" / f"{name}.asm"
        with tempfile.TemporaryDirectory() as tmp:
            be, offsets = m3._selas(src, pathlib.Path(tmp))
        sha = hashlib.sha256(src.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        spec = {"source": src.relative_to(ROOT).as_posix(), "source_sha256": sha, "toolchain": TOOLCHAIN,
                "section": "seg_pmco", "load_sw": hex(load_sw), "object_parcels_be": be.hex(),
                "instruction_offsets": offsets}
        src.with_suffix(".json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {src.stem}.json: {len(offsets)} instructions, {len(be)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
