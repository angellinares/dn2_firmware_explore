"""Assemble lines with selas (and our post-fixes) and read each back with digikit's decoder.

    python scripts/selas_roundtrip.py "BITREV(I1, 4);" "LCNTR = R12, DO l. UNTIL LCE (F);"
    python scripts/selas_roundtrip.py --file csrc/waverider/sharc/fft3.asm

Prints, per instruction, the bytes, digikit's form and rendering, and the source line.
A line that comes back as something else is an encoder bug (selas or ours) or a decoder
bug (digikit): the PRM decides which. Found this way, 2026-10-09: selas swaps Type 19a's
g and bit-reverse bits (scripts/sharc_waverider_m3.py fix_type19a).
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw import sharcemu  # noqa: E402


def decoder(digikit: pathlib.Path):
    tools = str(digikit / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import sharc_disasm  # noqa: PLC0415
    import sharcfn  # noqa: PLC0415

    class NoMemory:                     # the renderer annotates literal addresses from it
        @staticmethod
        def read(address, n):
            return None

    def read(be: bytes, sw: int) -> tuple[str, str]:
        insn = sharc_disasm.decode_isa48(be[::-1])
        text, _, _ = sharcfn.render_instruction(sw, insn, NoMemory(), set(), collections.Counter(), [])
        return insn.type_name or "?", text
    return read


def assemble(source: str, work: pathlib.Path):
    import sharc_waverider_m3 as m3  # noqa: PLC0415
    src = work / "roundtrip.asm"
    src.write_bytes(source.encode())
    return m3._selas(src, work)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("lines", nargs="*")
    p.add_argument("--file", type=pathlib.Path)
    p.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    a = p.parse_args(argv)
    if a.file:
        source = a.file.read_text(encoding="utf-8")
    else:
        source = ".SECTION/PM seg_pmco;\n.GLOBAL rt.;\nrt.:\n" + "\n".join(a.lines) + "\nNOP;\n"
    texts = [t for t in (ln.split("//", 1)[0].strip() for ln in source.splitlines())
             if t and not t.startswith(".") and not t.endswith(":")]
    read = decoder(a.digikit)
    with tempfile.TemporaryDirectory() as tmp:
        be, offs = assemble(source, pathlib.Path(tmp))
    for i, off in enumerate(offs):
        end = offs[i + 1] if i + 1 < len(offs) else len(be)
        word = be[off:end]
        form, text = read(word, off // 2) if len(word) == 6 else ("-", "(16/32-bit, not read)")
        print(f"{word.hex():>12}  {form:<12} {text:<52} | {texts[i]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
