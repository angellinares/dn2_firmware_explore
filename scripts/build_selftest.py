"""Stock DN2 1.11 with the USB probe, the SHARC idle stub and the stage 3 FFT self-test: a diagnostic.

    python scripts/build_selftest.py IMAGE -o OUT.syx [--probe-tag fftself]

Answers one question: does the stage 3 FFT (fft3.asm, spec3.asm) compute on the DSP what
it computes in the emulator? Section 7 is `dnfw.waverider.selftest.section7_selftest`
(stock, the idle stub, selftest.asm in the idle loop's back edge, fft3.asm, spec3.asm,
the test's frames and twiddles); section 3 is the usbprobe mod on stock, so
`tools/dn2selftest.py` can read the result. None of Waverider's mods is in either
processor. Assemble the sources first (`scripts/build_fft.py --assemble`). The image goes
through the same rebuild and integrity check as `dnfw mods apply`, and is not written
unless every check passes; then OUT.json carries the emulator's hash for the tool
(`scripts/sharc_selftest_check.py --write`).
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.waverider import selftest                    # noqa: E402

MAIN_OS, DSP_STREAM = 3, 7


def build(image: pathlib.Path, out_path: pathlib.Path, tag: str) -> int:
    from dnfw.cli.files import read_image                   # noqa: PLC0415
    from dnfw.firmware.build import build as rebuild        # noqa: PLC0415
    from dnfw.firmware.build import replacement             # noqa: PLC0415
    from dnfw.firmware.load import load                     # noqa: PLC0415
    from dnfw.firmware.verify import verify                 # noqa: PLC0415
    from dnfw.mods import usbprobe                          # noqa: PLC0415
    import sharc_selftest_check                             # noqa: PLC0415

    expected = out_path.with_suffix(".json")
    if out_path.exists() or expected.exists():
        print(f"  {out_path} (or its .json) exists: builds are never overwritten")
        return 1
    firmware = load(read_image(image))
    probe = usbprobe.apply(firmware, tag=tag)
    stream = firmware.container.find(DSP_STREAM).unpack()
    payloads = {MAIN_OS: probe.payloads[MAIN_OS], DSP_STREAM: selftest.section7_selftest(stream)}
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
    if sharc_selftest_check.main(["--image", str(image), "--write", str(expected)]):
        print("  the emulator run failed: no build written")
        expected.unlink(missing_ok=True)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out)
    print(f"wrote {out_path} ({len(out):,} bytes); nothing has been sent to an instrument")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("image", type=pathlib.Path)
    p.add_argument("-o", "--out", type=pathlib.Path, required=True)
    p.add_argument("--probe-tag", default="fftself")
    a = p.parse_args(argv)
    return build(a.image, a.out, a.probe_tag)


if __name__ == "__main__":
    raise SystemExit(main())
