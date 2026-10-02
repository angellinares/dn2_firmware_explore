"""Make the stock 1.11 snapshots the harnesses restore: `boot400M` and `ui1200M`.

    # with digikit's venv; paths from scripts/emulib/paths.py (docs/emulator.md):
    <digikit>/.venv/bin/python -u scripts/emu_make_snapshots.py [--force]

Nothing in the repository said how `ui1200M` was made, so a fresh clone could
not run any harness that restores it. This is a reconstruction, not the
original recipe:

1. **`boot400M`** -- a cold boot from reset to 400 M instructions, through
   digikit's `emu.checkpoint make` (eSDHC and the SD gate on, its defaults).
2. **`ui1200M`** -- `boot400M` resumed under digikit's `tools/guirun.py` with
   the flags `emulib.machine.FLAGS` names (unblock, softfloat, bitmap, dsp,
   weakptr, slc, sdgate, esdhc), run 800 M further and saved with its timer
   state, which `emulib.panel.Panel` claims.

**Needs digikit with the DN2 fixes**, which `paths.DIGIKIT` finds as the
sibling `digikit-up`. At digikit `main` `21b38b9` (2026-10-01) they are still
open PRs from this project: #19 (`devices/dn2-1.11`: guirun's terminal-loop
hook is a Digitakt II address, and on DN2 it fires on healthy code at ~63 M)
and #24 (`emu/weakptr-resume`, with the per-image weakptr sites). Plain
`main` fails here with `weakptr: 0x40188b40 holds 4878` or a false
`TERMINAL LOOP`.

`guirun` counts `--save-at` from the resume, so 800 M after `boot400M` is
1,200 M from reset -- the name. With softfloat on, instruction counts are not
comparable with a run that had it off (digikit `emu/longrun.py`).
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from emulib import paths  # noqa: E402

paths.use_digikit()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--force", action="store_true", help="remake snapshots that exist")
    args = p.parse_args()

    if not paths.SNAPSHOTS.is_dir():
        # paths.resolve falls back to the first default (the WSL /root path)
        # when none exists, so the folder has to be there before this runs.
        print(f"  {paths.SNAPSHOTS} does not exist: create "
              f"{paths.DIGIKIT / 'out/snapshots/dn2-1.11'} or set DN2_SNAPSHOTS")
        return 2
    boot = paths.SNAPSHOTS / "boot400M.snap"
    ui = paths.SNAPSHOTS / "ui1200M.snap"

    if args.force or not boot.exists():
        from emu.checkpoint import make
        print(f"  cold boot -> {boot}", flush=True)
        make([400_000_000], prefix=str(paths.SNAPSHOTS / "boot"), syx=str(paths.SYX))
    else:
        print(f"  {boot.name} exists; kept")

    if args.force or not ui.exists():
        print(f"  resume {boot.name} 800M -> {ui}", flush=True)
        done = subprocess.run(
            [sys.executable, "-u", str(paths.DIGIKIT / "tools/guirun.py"), str(boot),
             "--weakptr", "--slc", "--syx", str(paths.SYX),
             "--save-at", f"800M:{ui}", "--limit", str(801_000_000)],
            cwd=paths.DIGIKIT, check=False)
        if done.returncode or not ui.exists():
            print(f"  guirun exited {done.returncode}; {ui.name} not written")
            return 1
    else:
        print(f"  {ui.name} exists; kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
