"""`dnfw build` -- rebuild an image with replaced sections, and verify it.

The output is re-loaded and re-verified before it is written. Nothing leaves
this command that the toolchain cannot check end to end.
"""

import pathlib

from ..firmware.build import build as rebuild
from ..firmware.build import replacement
from ..firmware.load import load
from ..firmware.verify import verify
from .files import read_image

NAME = "build"
HELP = "rebuild an image with replaced sections, recomputing every checksum"


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    parser.add_argument("-o", "--out", type=pathlib.Path, required=True, help="output .syx")
    parser.add_argument(
        "-s",
        "--section",
        action="append",
        default=[],
        dest="replacements",
        metavar="ID=FILE",
        help="replace section ID with FILE's contents; repeatable",
    )


def run(args) -> int:
    firmware = load(read_image(args.image))

    replacements = {}
    for item in args.replacements:
        section_id, _, path = item.partition("=")
        if not path:
            raise ValueError(f"--section wants ID=FILE, got {item!r}")
        content = pathlib.Path(path).read_bytes()
        replacements[int(section_id, 0)] = replacement(firmware, int(section_id, 0), content)
        print(f"  section {int(section_id, 0)} <- {path}  ({len(content):,} bytes)")

    output = rebuild(firmware, replacements)
    return write_verified(output, args.out)


def write_verified(output: bytes, destination: pathlib.Path) -> int:
    """Re-load, verify, then write. Shared with `dnfw patch apply`."""
    checked = load(output)
    report = verify(checked)
    for check in report.checks:
        if not check.ok:
            print(f"    [BAD] {check.name:<32} {check.detail}")
    if not report.ok:
        raise ValueError("rebuilt image does not verify; nothing written")

    destination.write_bytes(output)
    signing = "unsigned" if checked.key is None else "HMAC-SHA256 signed"
    print(f"  wrote {destination}  ({len(output):,} bytes, {signing}, all checks pass)")
    return 0
