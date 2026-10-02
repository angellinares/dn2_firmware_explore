"""Where this checkout, digikit, the firmware and the emulator's working files are.

Every harness used to carry one machine's absolute WSL paths --
`/mnt/d/01_Code/Z_Personal/...` and `/root/...` -- so it ran on that machine
and nowhere else. They are resolved here once, in the same order digikit's own
`emu/config.py` uses:

    1. the environment variable, if set
    2. the first default that exists
    3. the first default, so the error names a path rather than None

| variable | what | defaults, in order |
|---|---|---|
| `DIGIKIT` | the digikit clone | sibling `digikit-up`, sibling `digikit` |
| `DT2_SYX` | stock Digitone II 1.11 | `00_Resources/00_Firmware/Digitone_II_OS1.11_dist/...syx` |
| `DT2_SECTIONS` | its extracted sections | `/root/dn2-sections-111`, `<digikit>/out/sections/dn2-1.11` |
| `DN2_SNAPSHOTS` | this project's snapshots | `/root/dn2-snapshots/Digitone_II_OS1.11`, `<digikit>/out/snapshots/dn2-1.11` |
| `SELMAP`, `SELAS` | selache's tools | `/root/<tool>-target/release/<tool>`, `tools/selmap/target/release/selmap` |

The WSL paths stay as defaults so the original setup needs no configuration;
a sibling clone is what makes it work anywhere else.

Standard library only: these scripts run under digikit's venv, which has no
`dnfw`.
"""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def resolve(var: str, *defaults: pathlib.Path) -> pathlib.Path:
    """-> $VAR if set, else the first of DEFAULTS that exists, else the first."""
    if os.environ.get(var):
        return pathlib.Path(os.environ[var]).expanduser()
    return next((d for d in defaults if d.exists()), defaults[0])


DIGIKIT = resolve("DIGIKIT", ROOT.parent / "digikit-up", ROOT.parent / "digikit")
SYX = resolve("DT2_SYX",
              ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx")
SECTIONS = resolve("DT2_SECTIONS", pathlib.Path("/root/dn2-sections-111"),
                   DIGIKIT / "out/sections/dn2-1.11")
SNAPSHOTS = resolve("DN2_SNAPSHOTS", pathlib.Path("/root/dn2-snapshots/Digitone_II_OS1.11"),
                    DIGIKIT / "out/snapshots/dn2-1.11")
SELMAP = resolve("SELMAP", pathlib.Path("/root/selmap-target/release/selmap"),
                 ROOT / "tools/selmap/target/release/selmap")
SELAS = resolve("SELAS", pathlib.Path("/root/selache-target/release/selas"))


def use_digikit(tools: bool = False) -> pathlib.Path:
    """Put digikit (and with TOOLS, its `tools/` ahead of it) on sys.path, and
    point digikit's own configuration at the 1.11 sections, before anything
    imports `emu`.

    digikit's `DT2_SECTIONS` default is `sections`, relative to the working
    directory -- which, run from this checkout, is a directory that does not
    exist, or worse, one holding another firmware's sections
    (`docs/emulator.md`, "a stale section cache"). An explicit setting wins.
    """
    for path in (DIGIKIT, DIGIKIT / "tools") if tools else (DIGIKIT,):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    os.environ.setdefault("DT2_SECTIONS", str(SECTIONS))
    return DIGIKIT
