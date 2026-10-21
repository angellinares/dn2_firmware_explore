"""Make the loadmap plan: assemble loadmap.asm and work out which jumps go to which mark stub.

    python scripts/build_loadmap.py --assemble        # (re)write src/dnfw/waverider/loadmap_code.json

Then any build made with DNFW_WAVERIDER_LOADMAP=1 carries the marks (dnfw.waverider.loadmap):

    DNFW_WAVERIDER_LOADMAP=1 dnfw mods apply IMAGE ... --mod waverider --mod usbprobe ...

The plan is computed on the Waverider section 7 that dsp.section7 makes now, from stock DN2
1.11, and records that stream's sha256: loadmap.apply refuses any other. For each mark:

- stock: a CJUMP on the frame's path (sites found by tracing a block in digikit's runner,
  2026-10-21: the per-block routine 0x1c2712's top-level calls and the dispatch's per-track
  calls). Its bytes must be `CJUMP target (DB)`.
- site: one of the JUMPs dsp.section7 writes into stock (the splice, the entry mark).
- ours: every JUMP, CALL and CJUMP in our placed objects whose target is the stage's label.
- ret: the return-address literal that sends a CJUMP's return to the label.

selache's selas (GPL-3.0) is a tool here, in WSL; nothing of it is copied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.image import bootstream, sharc_object        # noqa: E402
from dnfw.waverider import dsp, loadmap as L          # noqa: E402

SHARC = ROOT / "csrc" / "waverider" / "sharc"
SRC = SHARC / "loadmap.asm"
IMAGE = ROOT / "00_Resources" / "00_Firmware" / "Digitone_II_OS1.11_dist.zip"
TOOLCHAIN = "selache selas -proc ADSP-21569 (js216/selache 2b26d3b, GPL-3.0, WSL)"
# our objects in Waverider's stream: name -> load sw (the reader is the mip reader that ships)
PLACED = {"reader_m9": dsp.READER_SW, "machine9_live": dsp.LOOP_SW, "idle_load": dsp.IDLE_SW,
          "block_count": dsp.COUNT_SW, "entry_mark": dsp.EMARK_SW, "modulator": dsp.MOD_SW,
          "shapes": dsp.SHAPES_SW, "load": dsp.LOAD_SW, "pool": dsp.POOL_SW, "sync": dsp.SYNC_SW,
          "smooth": dsp.SMOOTH_SW, "dclk": dsp.DCLK_SW, "sub": dsp.SUB_SW, "noise": dsp.NOISE_SW,
          "trim": dsp.TRIM_SW, "reader_miph2": dsp.MIP_SW, "page5": dsp.PAGE5_SW,
          "phase": dsp.PHASE_SW, "formant": dsp.FORMANT_SW}
# mark -> how its stub is reached (see the module docstring); None: only by another stub or code
SPEC = {
    "emark": ("site", dsp.CALL_SITE_SW, dsp.EMARK_SW),
    "dispatch": ("stock", 0x1C3044, 0x1C8EF1),
    "splice": ("site", dsp.ENTRY_SW, dsp.COUNT_SW),
    "null": ("in", "block_count", dsp.LOOP_SW),          # block_count's way on; its stub goes to stub 4
    "publish": None,                                      # stub 3 -> stub 4 -> wr_lm_pub
    "w_entry": None,                                      # wr_lm_pub's last JUMP -> stub 5 -> wr_type5v
    "w_voice": ("ours", "machine9_live", "wr_t5v_loop"),
    "w_p5voice": ("ours", "page5", "wr_p5_voice"),
    "w_osc": ("ours", "machine9_live", "wr_t5v_osc"),
    "w_move": ("ours", "trim", "wr_trim"),
    "w_modded": ("ours", "machine9_live", "wr_t5v_modded"),
    "w_phase": ("ours", "page5", "wr_p5_phase"),
    "w_dclk": ("ours", "dclk", "wr_dclk_pre"),
    "w_read": ("ours", "reader_m9", "wr_render5"),
    "w_p5mid": ("ours", "page5", "wr_p5_mid"),
    "w_p5ran": ("ours", "page5", "wr_p5_ran"),
    "w_fmpost": ("ours", "formant", "wr_fm_post"),
    "w_sub": ("ours", "sub", "wr_sub_ran"),
    "w_noise": ("ours", "noise", "wr_noise"),
    "w_next": ("ours", "machine9_live", "wr_t5v_next"),
    "w_fmend": ("ours", "formant", "wr_fm_end"),
    "w_exit": ("ours", "reader_m9", "wr_t5v_exit"),
    "t_1cdb56": ("stock", 0x1C95C9, 0x1CDB56),
    "t_b80c39": ("stock", 0x1C94FD, 0xB80C39),
    "t_b81368": ("stock", 0x1C959F, 0xB81368),
    "t_b82342": ("stock", 0x1C98AF, 0xB82342),
    "t_b80345": ("stock", 0x1C99CC, 0xB80345),
    "s_1c1738": ("stock", 0x1C3054, 0x1C1738),
    "s_1c1f1e": ("stock", 0x1C305D, 0x1C1F1E),
    "s_1c244d": ("stock", 0x1C307B, 0x1C244D),
    "s_tail": ("stock", 0x1C3093, 0x1CA84E),
}


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def mem(be: bytes) -> bytes:
    return sharc_object.load_bytes(be)


def instruction_lines(text: str) -> list[str]:
    """The source's instruction lines, numbered as sharc_resolve_jumps.labels numbers them."""
    out = []
    for line in text.splitlines():
        t = line.split("//", 1)[0].strip()
        if t and not t.startswith(".") and not t.endswith(":"):
            out.append(line)
    return out


class Obj:
    def __init__(self, name: str, load_sw: int, stream: bytes):
        from sharc_resolve_jumps import labels                    # noqa: PLC0415
        spec = json.loads((SHARC / f"{name}.json").read_text(encoding="utf-8"))
        text = (SHARC / f"{name}.asm").read_text(encoding="utf-8")
        if spec["source_sha256"] != sha(SHARC / f"{name}.asm"):
            raise SystemExit(f"{name}.json is stale for {name}.asm")
        self.name, self.load_sw, self.text = name, load_sw, text
        self.be = bytes.fromhex(spec["object_parcels_be"])
        self.offs = spec["instruction_offsets"]
        self.lines = instruction_lines(text)
        if len(self.lines) != len(self.offs):
            raise SystemExit(f"{name}: {len(self.lines)} instruction lines, {len(self.offs)} offsets")
        if bootstream.read_span(stream, dsp.dm_to_load(2 * load_sw), len(self.be)) != mem(self.be):
            raise SystemExit(f"{name} in Waverider's stream is not {name}.json's object")
        self.labels = {lab: load_sw + self.offs[k] // 2 for lab, k in labels(text).items() if k < len(self.offs)}

    def instructions(self):
        """(byte offset, the 48-bit instruction's parcels) for each 48-bit instruction."""
        ends = self.offs[1:] + [len(self.be)]
        for o, e in zip(self.offs, ends):
            if e - o == 6:
                yield o, self.be[o:o + 6]

    def load(self, off: int) -> int:
        return dsp.dm_to_load(2 * self.load_sw + off)


def is_branch_to(ins: bytes, target: int) -> bool:
    """JUMP / CALL (Type 8a, absolute: 06 cc 00 addr24) or CJUMP (18 04 00 addr24) to TARGET."""
    form = ins[0] == 0x06 and ins[2] == 0x00 or ins[:3] == b"\x18\x04\x00"
    return form and int.from_bytes(ins[3:], "big") == target


def plan(stream: bytes) -> tuple[list[dict], list[dict]]:
    objs = {n: Obj(n, sw, stream) for n, sw in PLACED.items()}
    lm_labels = {}
    marks, patches = [], []
    for k, (name, what) in enumerate(L.MARKS):
        spec, stub = SPEC[name], L.stub_sw(k)
        if spec is None:
            target = {"publish": None, "w_entry": dsp.LOOP_SW}[name]
        elif spec[0] in ("site", "stock"):
            kind, site, target = spec
            op = "063e00" if kind == "site" else "180400"
            at = dsp.sw_to_load(site)
            old, new = mem(bytes.fromhex(f"{op}{target:06x}")), mem(bytes.fromhex(f"{op}{stub:06x}"))
            if bootstream.read_span(stream, at, 6) != old:
                raise SystemExit(f"{name}: sw {site:#x} is not `{op} {target:#x}` in Waverider's stream")
            patches.append({"what": f"{name}: sw {site:#x} -> stub {k}", "load": at, "old": old.hex(), "new": new.hex()})
        elif spec[0] == "in":
            _, oname, target = spec
            o = objs[oname]
            hits = [(off, ins) for off, ins in o.instructions() if is_branch_to(ins, target)]
            if len(hits) != 1:
                raise SystemExit(f"{name}: {len(hits)} branches to {target:#x} in {oname}, not 1")
            off, ins = hits[0]
            patches.append({"what": f"{name}: {oname} +{off:#x} -> stub {k}", "load": o.load(off),
                            "old": mem(ins).hex(), "new": mem(ins[:3] + stub.to_bytes(3, "big")).hex()})
        elif spec[0] == "ours":
            _, oname, label = spec
            target = objs[oname].labels[label]
            n = 0
            for o in objs.values():
                for off, ins in o.instructions():
                    if is_branch_to(ins, target):
                        patches.append({"what": f"{name}: {o.name} +{off:#x} -> stub {k}", "load": o.load(off),
                                        "old": mem(ins).hex(), "new": mem(ins[:3] + stub.to_bytes(3, "big")).hex()})
                        n += 1
            if not n:
                raise SystemExit(f"{name}: nothing branches to {label} ({target:#x})")
        elif spec[0] == "ret":
            _, oname, label = spec
            o = objs[oname]
            target = o.labels[label]
            hits = [k2 for k2, line in enumerate(o.lines) if f"return address - 1: {label}." in line]
            if len(hits) != 1:
                raise SystemExit(f"{name}: {len(hits)} return literals for {label}")
            off = o.offs[hits[0]]
            ins = o.be[off:off + 6]
            if int.from_bytes(ins[2:], "big") != target - 1:
                raise SystemExit(f"{name}: the literal at {oname} +{off:#x} is not {target - 1:#x} ({ins.hex()})")
            patches.append({"what": f"{name}: {oname} +{off:#x} return -> stub {k}", "load": o.load(off),
                            "old": mem(ins).hex(), "new": mem(ins[:2] + (stub - 1).to_bytes(4, "big")).hex()})
        marks.append({"name": name, "what": what, "stub_sw": stub, "target_sw": target})
    return marks, patches


def assemble() -> int:
    import sharc_waverider_m3 as m3                               # noqa: PLC0415  (WSL + selas)
    import sharc_waverider_render as m1                           # noqa: PLC0415
    from sharc_resolve_jumps import labels                        # noqa: PLC0415
    if os.environ.get("DNFW_WAVERIDER_LOADMAP") == "1":
        raise SystemExit("unset DNFW_WAVERIDER_LOADMAP: the plan is made on the plain Waverider stream")
    with tempfile.TemporaryDirectory() as tmp:
        be, offs = m3._selas(SRC, pathlib.Path(tmp))
    text = SRC.read_text(encoding="utf-8")
    lab = {n: L.MARK_SW + offs[k] // 2 for n, k in labels(text).items() if k < len(offs)}
    if lab.get("wr_lm_mark") != L.MARK_SW:
        raise SystemExit("wr_lm_mark is not loadmap.asm's first instruction")
    stream = dsp.section7(m1.dn2_section7(IMAGE))
    marks, patches = plan(stream)
    marks[L.MARKS.index(next(m for m in L.MARKS if m[0] == "publish"))]["target_sw"] = lab["wr_lm_pub"]
    marks[[m[0] for m in L.MARKS].index("null")]["target_sw"] = L.stub_sw([m[0] for m in L.MARKS].index("publish"))
    spec = {"note": "generated by scripts/build_loadmap.py --assemble; do not edit",
            "base_section7_sha256": hashlib.sha256(stream).hexdigest(),
            "loadmap": {"source": SRC.relative_to(ROOT).as_posix(), "source_sha256": sha(SRC),
                        "toolchain": TOOLCHAIN, "section": "seg_pmco", "load_sw": hex(L.MARK_SW),
                        "object_parcels_be": be.hex(), "instruction_offsets": offs,
                        "labels": {k: hex(v) for k, v in lab.items()}},
            "marks": marks, "patches": patches}
    L.CODE.write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {L.CODE.relative_to(ROOT)}: loadmap.asm {len(be)} B, {len(marks)} marks, {len(patches)} patches")
    for m in marks:
        n = sum(1 for p in patches if p["what"].startswith(m["name"] + ":"))
        print(f"  {L.MARKS.index(next(x for x in L.MARKS if x[0] == m['name'])):2d} {m['name']:10s} "
              f"stub {m['stub_sw']:#x} -> {m['target_sw']:#x}  sites {n}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--assemble", action="store_true")
    a = p.parse_args(argv)
    if a.assemble:
        return assemble()
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
