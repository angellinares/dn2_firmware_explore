"""Every committed Waverider DSP object, read back with digikit's decoder, makes the memory
accesses its source line says: the same space (DM or PM), the same I and M registers, and the
same pre or post modify.

selas encodes some accesses wrong (scripts/selas_roundtrip.py's notes): the 32-bit Type 3b
ureg access with post-modify comes out pre-modify, and a pre-modify ureg load from PM comes
out as DM (found 2026-10-30, after EmDee's report on digikit's debug/fault-trace branch). None
of our sources uses those forms today. This test fails if one ever reaches a committed object.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

CODE = ROOT / "src/dnfw/waverider/sharc_code.json"


@pytest.fixture(scope="module")
def decode():
    from dnfw import sharcemu
    try:
        path = sharcemu.path()
        sharcemu.alias_main_layout(path)
        from tools.sharc_dev import sharc_disasm  # noqa: PLC0415
    except Exception as exc:                      # noqa: BLE001  (no digikit checkout here)
        pytest.skip(f"no digikit decoder: {exc}")
    import selas_roundtrip
    return sharc_disasm, selas_roundtrip.decoder(path)


def _records():
    return {k: v for k, v in json.loads(CODE.read_text(encoding="utf-8")).items() if isinstance(v, dict)}


def _texts(source: str) -> list[str]:
    return [t for t in (ln.split("//", 1)[0].strip() for ln in source.splitlines())
            if t and not t.startswith(".") and not t.endswith(":")]


@pytest.mark.parametrize("name", sorted(_records()))
def test_committed_object_makes_its_sources_accesses(name, decode):
    from selas_roundtrip import accesses
    sharc_disasm, read = decode
    rec = _records()[name]
    source = rec["source"]
    texts = _texts((ROOT / source).read_text(encoding="utf-8") if source.endswith(".asm") else source)
    be = bytes.fromhex(rec["object_parcels_be"])
    le = b"".join(be[i:i + 2][::-1] for i in range(0, len(be), 2))
    off, got = 0, []
    while off < len(le):
        n = sharc_disasm.decode_confident(le, off).length_bytes
        assert n, f"{name}: nothing decodes at +{off}"
        got.append(read(be[off:off + n], off // 2)[1])
        off += n
    assert len(got) == len(texts), f"{name}: {len(got)} instructions for {len(texts)} source lines"
    changed = [(t, g) for t, g in zip(texts, got) if accesses(t) != accesses(g, decoded=True)]
    assert not changed, changed


@pytest.mark.parametrize("source, decoded, same", [
    ("R0 = DM(I1, M2);", "R0 = DM(I1, M2) u=1", True),
    ("R4 = DM(M2, I0);", "R4 = DM(I0, M2) u=0", True),             # pre-modify, as digikit prints it
    ("I12 = DM(I6, M7);", "I12 = DM(I6, M7) u=0", False),          # selas's Type 3b: post became pre
    ("I12 = PM(M15, I14);", "I12 = DM(I6, M7) u=0", False),        # selas: PM became DM
    ("R5 = PM(I11, M11);", "R5 = PM(I3, M3)", True),               # digikit prints DAG2 as 0-7
    ("R0 = DM(2, I4);", "R0 = DM(I4 + 0x2)", True),
    ("DM(0x2df064) = R4;", "DM(0x2df064) = R4", True),
])
def test_accesses_compares_space_modify_and_registers(source, decoded, same):
    from selas_roundtrip import accesses
    assert (accesses(source) == accesses(decoded, decoded=True)) is same
