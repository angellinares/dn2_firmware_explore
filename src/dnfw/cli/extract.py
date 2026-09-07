"""`dnfw extract` -- write each section out for disassembly or diffing."""

import pathlib

from ..container import ele3
from ..firmware.load import load
from .files import read_image

NAME = "extract"
HELP = "write each section to a directory, depacked where it is compressed"


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    parser.add_argument("-o", "--out", type=pathlib.Path, required=True, help="output directory")
    parser.add_argument(
        "--section",
        type=int,
        action="append",
        dest="sections",
        metavar="ID",
        help="extract only this section id; repeatable (default: all)",
    )


def run(args) -> int:
    firmware = load(read_image(args.image))
    args.out.mkdir(parents=True, exist_ok=True)

    wanted = set(args.sections) if args.sections else None
    written = 0
    for section in firmware.container.sections:
        if wanted is not None and section.id not in wanted:
            continue
        content = section.unpack()
        label = ele3.name(section.id).replace(" ", "_")
        # The suffix records how the section is stored, because that decides
        # how a rebuild must put it back.
        kind = "aplib" if content else "raw"
        path = args.out / f"section_{section.id}_{label}.{kind}.bin"
        path.write_bytes(content if content else section.stored)
        print(f"  {path}  {len(content) if content else len(section.stored):,} bytes"
              f"  dest 0x{section.dest:08x}")
        written += 1

    if wanted is not None and written != len(wanted):
        raise ValueError(f"asked for {sorted(wanted)} but wrote {written} section(s)")
    return 0
