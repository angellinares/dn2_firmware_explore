"""Loading patch records from the `patches/` directory.

Adapted from `discover()` in bryantysinger/octa-bt-pt (`tools/patchlib.py`),
MIT: each `patches/*.py` declares a module-level `PATCHES` list, files are
loaded in sorted order so a listing is stable, and duplicate ids are refused.

A patch file is Python because a patch is data with arithmetic in it -- an
address plus an offset, a string built from a constant -- and a data format
that has to grow expressions ends up a worse programming language than the one
it is written in.
"""

import importlib.util
import pathlib

from .spec import Patch, PatchError, validate

DEFAULT_DIRECTORY = pathlib.Path("patches")


def load(directory: pathlib.Path = DEFAULT_DIRECTORY) -> list[Patch]:
    """Every patch declared under `directory`, in file then declaration order."""
    if not directory.is_dir():
        return []

    patches: list[Patch] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        patches.extend(_from_file(path))
    validate(patches)
    return patches


def _from_file(path: pathlib.Path) -> list[Patch]:
    spec = importlib.util.spec_from_file_location(f"dnfw_patches_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise PatchError(f"{path}: cannot be loaded as a Python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    declared = getattr(module, "PATCHES", None)
    if declared is None:
        raise PatchError(f"{path}: no module-level PATCHES list")
    for item in declared:
        if not isinstance(item, Patch):
            raise PatchError(f"{path}: PATCHES contains a {type(item).__name__}, not a Patch")
    return list(declared)
