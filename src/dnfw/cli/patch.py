"""`dnfw patch` -- list the declared patches, or apply them to an image."""

import pathlib

from ..container import ele3
from ..firmware.build import build as rebuild
from ..firmware.build import replacement
from ..firmware.load import load
from ..patch import discover
from ..patch.apply import applies_to, apply
from .build import write_verified
from .files import read_image

NAME = "patch"
HELP = "list declared patches, or apply them to an image"


def configure(parser) -> None:
    parser.add_argument(
        "-p",
        "--patches",
        type=pathlib.Path,
        default=discover.DEFAULT_DIRECTORY,
        help="directory of patch definitions (default: patches/)",
    )
    actions = parser.add_subparsers(dest="action", required=True)

    listing = actions.add_parser("list", help="show every declared patch")
    listing.add_argument(
        "--image",
        type=pathlib.Path,
        help="also say whether each patch applies to this image",
    )
    listing.set_defaults(action_run=_list)

    applying = actions.add_parser("apply", help="apply patches and rebuild")
    applying.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    applying.add_argument("-o", "--out", type=pathlib.Path, required=True, help="output .syx")
    applying.add_argument(
        "--id",
        action="append",
        dest="ids",
        metavar="ID",
        help="apply only this patch id; repeatable (default: all that apply)",
    )
    applying.set_defaults(action_run=_apply)


def run(args) -> int:
    return args.action_run(args)


def _list(args) -> int:
    patches = discover.load(args.patches)
    if not patches:
        print(f"no patches in {args.patches}/")
        return 0

    firmware = load(read_image(args.image)) if args.image else None
    for item in patches:
        print(f"{item.id}  [{item.group}]")
        print(f"  {item.description}")
        print(
            f"  device 0x{item.device:02x}  build {item.build}  version {item.version}  "
            f"section {item.section} ({ele3.name(item.section)})  at {item.target}  "
            f"{len(item.expect)} bytes"
        )
        if firmware is not None:
            reason = applies_to(item, firmware)
            print(f"  {'applies to ' + str(args.image) if reason is None else 'does not apply: ' + reason}")
        if item.notes:
            print(f"  {item.notes}")
    return 0


def _apply(args) -> int:
    firmware = load(read_image(args.image))
    patches = discover.load(args.patches)

    if args.ids:
        wanted = set(args.ids)
        patches = [p for p in patches if p.id in wanted]
        missing = wanted - {p.id for p in patches}
        if missing:
            raise ValueError(f"no such patch id: {', '.join(sorted(missing))}")
    else:
        patches = [p for p in patches if applies_to(p, firmware) is None]

    if not patches:
        raise ValueError("no patches apply to this image")

    contents, applied = apply(patches, firmware)
    for record in applied:
        print(f"  {record.patch.id}: section {record.section} at +0x{record.offset:x}")

    replacements = {sid: replacement(firmware, sid, data) for sid, data in contents.items()}
    return write_verified(rebuild(firmware, replacements), args.out)
