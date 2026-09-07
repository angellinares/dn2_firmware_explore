"""Reading a firmware image from wherever it is kept.

Elektron ship OS files inside a `.zip` beside a readme, and that is how the
corpus in `00_Resources/` stores them. Accepting the zip directly means the
distributed file never has to be unpacked, so there is one less loose `.syx`
on disk to confuse with a build output.
"""

import pathlib
import zipfile


def read_image(path: pathlib.Path) -> bytes:
    """Read a `.syx`, or the single `.syx` inside a `.zip`."""
    if path.suffix.lower() != ".zip":
        return path.read_bytes()

    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".syx")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected exactly one .syx inside, found {len(names)}")
        return archive.read(names[0])
