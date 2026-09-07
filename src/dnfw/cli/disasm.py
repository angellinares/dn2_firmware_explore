"""`dnfw disasm` -- disassemble a span of a section with m68k-elf-objdump.

**Use objdump, not radare2, and validate anything else against it.** octabam
measured r2's m68k backend against this exact CPU on 30 Aug 2026: below
0x40098000 it fails on 6,757 instructions, 4,543 of them longer than two bytes.
Because it then assumes the opcode was two bytes, each extension word is
decoded as a separate plausible-looking instruction and the stream
desynchronises -- so it does not report failure, it invents code. The bulk is
`mvz` and `mvs`, ordinary ColdFire ISA_B moves used throughout, not exotic
audio code. Any tool whose m68k support predates ColdFire has the same problem.

`m68k-elf-objdump` is not bundled and is not a Python dependency; this command
tells you what to install if it is missing rather than guessing at an answer.
"""

import pathlib
import shutil
import subprocess
import tempfile

from ..firmware.load import load
from ..image.coldfire import LoadedImage
from .files import read_image

NAME = "disasm"
HELP = "disassemble a span of a section (ColdFire V4e, via m68k-elf-objdump)"

TOOL = "m68k-elf-objdump"
ARCHITECTURE = "m68k:cfv4e"
MAIN_OS = 3


def configure(parser) -> None:
    parser.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    parser.add_argument("address", help="virtual address to start at, e.g. 0x40000400")
    parser.add_argument("length", nargs="?", type=int, default=128, help="bytes (default: 128)")
    parser.add_argument(
        "--section", type=int, default=MAIN_OS, help="section id (default: 3, MAIN OS)"
    )


def run(args) -> int:
    tool = shutil.which(TOOL)
    if tool is None:
        raise ValueError(
            f"{TOOL} not found on PATH. It is the only disassembler confirmed to read "
            f"this CPU correctly -- install a m68k-elf binutils build and retry. "
            f"See docs/mainos-image.md for why radare2 is not a substitute."
        )

    firmware = load(read_image(args.image))
    section = firmware.container.find(args.section)
    if section is None:
        raise ValueError(f"image has no section id={args.section}")
    content = section.unpack()
    if content is None:
        raise ValueError(f"section id={args.section} is stored raw, not code")

    image = LoadedImage(dest=section.dest, content=content)
    address = int(args.address, 0)
    span = image.read(address, args.length)

    with tempfile.TemporaryDirectory() as directory:
        blob = pathlib.Path(directory) / "span.bin"
        blob.write_bytes(span)
        result = subprocess.run(
            [tool, "-D", "-b", "binary", "-m", ARCHITECTURE,
             f"--adjust-vma={address:#x}", str(blob)],
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        raise ValueError(f"{TOOL} failed: {result.stderr.strip()}")
    print(result.stdout, end="")
    return 0
