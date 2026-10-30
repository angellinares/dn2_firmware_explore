"""Assemble lines with selas (and our post-fixes) and read each back with digikit's decoder.

    python scripts/selas_roundtrip.py "BITREV(I1, 4);" "LCNTR = R12, DO l. UNTIL LCE (F);"
    python scripts/selas_roundtrip.py --file csrc/waverider/sharc/fft3.asm

Prints, per instruction, the bytes, digikit's form and rendering, and the source line.
A line that comes back as something else is an encoder bug (selas or ours) or a decoder
bug (digikit): the PRM decides which. Found this way, 2026-10-09: selas swaps Type 19a's
g and bit-reverse bits (scripts/sharc_waverider_m3.py fix_type19a). Found 2026-10-30, with
our post-fixes on and none of our sources using either form: the 32-bit Type 3b ureg access
`I12 = DM(I6, M7)` and `DM(I6, M7) = I12` come out pre-modify (u=0), and `I12 = PM(M15, I14)`
comes out as DM. test/test_sharc_object_accesses.py checks every committed object for this.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw import sharcemu  # noqa: E402

ACCESS = re.compile(r"(DM|PM)\s*\(([^()]*)\)", re.IGNORECASE)


def accesses(text: str, decoded: bool = False) -> list[str]:
    """The memory accesses of a source line, or of digikit's rendering of it (DECODED), in one
    form: space, pre or post modify, I and M register (DAG2's as 0-7, as digikit prints PM's),
    or the base and offset. digikit writes a pre-modify as `DM(Ia, Mb) u=0`, the source as
    `DM(Mb, Ia)`."""
    pre = decoded and " u=0" in text
    t = text.replace(" u=1", "").replace(" u=0", "").replace(" ", "").upper()
    out = []
    for space, inner in ACCESS.findall(t):
        a, _, b = inner.partition(",")
        if not b:                                         # DM(I4+0x2), DM(I4-2) or DM(addr)
            m = re.fullmatch(r"(I\d+)([+-])(0X[0-9A-F]+|\d+)", a)
            out.append(f"{space}({m.group(1)}{int(m.group(3), 0) * (1 if m.group(2) == '+' else -1):+d})"
                       if m else f"{space}({a})")
            continue
        here = pre
        if not a.startswith("I"):                         # DM(Mb, Ia) or DM(imm, Ia): pre-modify
            if re.fullmatch(r"-?(0X[0-9A-F]+|\d+)", a):
                out.append(f"{space}({b}{int(a, 0):+d})")
                continue
            a, b, here = b, a, True
        if space == "PM":
            a = f"I{int(a[1:]) % 8}"
            b = f"M{int(b[1:]) % 8}" if re.fullmatch(r"M\d+", b) else b
        out.append(f"{space}{'(pre)' if here else ''}({a},{b})")
    return out


def decoder(digikit: pathlib.Path):
    if (digikit / "tools" / "sharc_dev").is_dir():       # digikit main's layout (since #264)
        if str(digikit) not in sys.path:
            sys.path.insert(0, str(digikit))
        from tools.sharc_dev import sharc_disasm, sharcfn  # noqa: PLC0415
    else:
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
        if len(be) == 6:
            insn = sharc_disasm.decode_isa48(be[::-1])
        else:                           # the 16- and 32-bit forms: memory order is little-endian per 16-bit parcel
            insn = sharc_disasm.decode_confident(b"".join(be[i:i + 2][::-1] for i in range(0, len(be), 2)), 0)
            if insn.length_bytes != len(be):
                return "?", f"(decoded as {insn.length_bytes or 'no'} bytes, assembled as {len(be)})"
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
        form, text = read(word, off // 2)
        print(f"{word.hex():>12}  {form:<12} {text:<52} | {texts[i]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
