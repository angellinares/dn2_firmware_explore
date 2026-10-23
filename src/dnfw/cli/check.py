"""`dnfw check` -- the safety checklist of a patched image against stock (`firmware.safety`).

The website's Check page shows the same list (`site/js/safety.js`). The rebuild here applies
the record's mods with `dnfw mods apply`, so it can rebuild mods the website does not
publish, such as usbprobe.
"""

import argparse
import contextlib
import io
import pathlib
import tempfile

from ..firmware import compare, safety
from ..firmware.load import load
from .files import read_image

NAME = "check"
HELP = "the safety checklist of a patched Digitone II image against stock"
MARKS = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "info": "INFO", "skip": "SKIP"}
NEEDS_INPUT = ("transients", "bootscreen")        # mods built from the user's own files


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help="the patched image (.syx)")
    parser.add_argument("--stock", type=pathlib.Path, required=True,
                        help="Elektron's stock image (.syx or .zip) it was built from")
    parser.add_argument("--no-rebuild", action="store_true", help="skip the exact rebuild")


def rebuilder(stock_path: pathlib.Path):
    """REBUILD for `safety.check`: `dnfw mods apply` of MODS to STOCK_PATH, quietly."""
    from . import mods as cli_mods

    def rebuild(stock, mods, tag):
        unknown = [m for m in mods if m not in cli_mods.REGISTRY]
        if unknown:
            return f"this patcher does not know {', '.join(unknown)}"
        inputs = [m for m in mods if m in NEEDS_INPUT]
        if inputs:
            return f"{', '.join(inputs)} needs the user's own files, so it cannot be rebuilt"
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "rebuilt_DN2_1.11.syx"
            args = argparse.Namespace(image=stock_path, mod=list(mods), out=out,
                                      probe_tag=tag if "usbprobe" in mods else None)
            with contextlib.redirect_stdout(io.StringIO()):
                if cli_mods._apply(args) != 0:
                    return "dnfw mods apply refused these mods"
            built = load(out.read_bytes())
        return {s.id: compare.content(s)[0] for s in built.container.sections}
    return rebuild


def run(args) -> int:
    patched, stock = load(read_image(args.image)), load(read_image(args.stock))
    items = safety.check(patched, stock, None if args.no_rebuild else rebuilder(args.stock))
    for item in items:
        print(f"{MARKS[item.status]}  {item.title}")
        print(f"      {item.detail}")
    print("\nNot checked:")
    for line in safety.NOT_CHECKED:
        print(f"  - {line}")
    return 1 if any(i.status == "fail" for i in items) else 0
