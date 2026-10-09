"""Stock DN2 1.11 with the USB probe, the SHARC idle stub and the DDR scanner: a diagnostic.

    python scripts/build_ddrscan.py --assemble          # (re)write ddrscan_code.json (WSL + selache)
    python scripts/build_ddrscan.py IMAGE -o OUT.syx [--probe-tag ddrscan]

Answers one question: does anything write the DSP's spare DDR while the instrument plays?
Section 7 is `dnfw.waverider.ddrscan.section7_ddrscan` (stock, the idle stub, ddrscan.asm, and
fill blocks writing a pattern over 0x80531000..0xa0000000); section 3 is the usbprobe mod on
stock, so `tools/dn2ddrscan.py` can read the result. None of Waverider's code is in either
processor. The image goes through the same rebuild and integrity check as `dnfw mods
apply`, and is not written unless every check passes.
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

from dnfw.waverider import ddrscan                     # noqa: E402

SRC = ROOT / "csrc" / "waverider" / "sharc" / "ddrscan.asm"
TOOLCHAIN = "selache selas -proc ADSP-21569 (js216/selache 2b26d3b, GPL-3.0, WSL)"
MAIN_OS, DSP_STREAM = 3, 7


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def assemble() -> None:
    import sharc_waverider_m3 as m3  # noqa: PLC0415  (WSL + selas)
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        be, offsets = m3._selas(SRC, work)
        line = f"JUMP {ddrscan.SCAN_SW:#x};"
        jump, _ = m3._selas_line(line, work)
    spec = {"ddrscan": {"source": SRC.relative_to(ROOT).as_posix(), "source_sha256": sha(SRC),
                        "toolchain": TOOLCHAIN, "section": "seg_pmco", "load_sw": hex(ddrscan.SCAN_SW),
                        "object_parcels_be": be.hex(), "instruction_offsets": offsets},
            "scan_jump": {"source": line, "toolchain": TOOLCHAIN, "object_parcels_be": jump.hex()}}
    ddrscan.CODE.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {ddrscan.CODE.name}: ddrscan.asm {len(offsets)} instructions, scan JUMP {len(jump)} bytes")


def build(image: pathlib.Path, out_path: pathlib.Path, tag: str) -> int:
    from dnfw.cli.files import read_image                   # noqa: PLC0415
    from dnfw.firmware.build import build as rebuild        # noqa: PLC0415
    from dnfw.firmware.build import replacement             # noqa: PLC0415
    from dnfw.firmware.load import load                     # noqa: PLC0415
    from dnfw.firmware.verify import verify                 # noqa: PLC0415
    from dnfw.mods import usbprobe                          # noqa: PLC0415

    spec = json.loads(ddrscan.CODE.read_text(encoding="utf-8"))
    if spec["ddrscan"]["source_sha256"] != sha(SRC):
        print(f"  {ddrscan.CODE.name} is stale for {SRC.name}: run with --assemble")
        return 1
    if out_path.exists():
        print(f"  {out_path} exists: builds are never overwritten")
        return 1
    firmware = load(read_image(image))
    probe = usbprobe.apply(firmware, tag=tag)
    stream = firmware.container.find(DSP_STREAM).unpack()
    payloads = {MAIN_OS: probe.payloads[MAIN_OS], DSP_STREAM: ddrscan.section7_ddrscan(stream)}
    extra = set(probe.payloads) - {MAIN_OS}
    if extra:
        print(f"  the probe also wrote sections {sorted(extra)}: not expected")
        return 1
    out = rebuild(firmware, {sid: replacement(firmware, sid, pl) for sid, pl in payloads.items()})
    report = verify(load(out))
    bad = [c for c in report.checks if not c.ok]
    print(f"integrity: {len(report.checks) - len(bad)}/{len(report.checks)} checks pass")
    if bad:
        for c in bad:
            print(f"  FAILED: {c.name}")
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out)
    print(f"wrote {out_path} ({len(out):,} bytes); nothing has been sent to an instrument")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("image", type=pathlib.Path, nargs="?")
    p.add_argument("-o", "--out", type=pathlib.Path)
    p.add_argument("--probe-tag", default="ddrscan")
    p.add_argument("--assemble", action="store_true")
    a = p.parse_args(argv)
    if a.assemble:
        assemble()
    if a.image:
        if not a.out:
            p.error("-o is required with an image")
        return build(a.image, a.out, a.probe_tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
