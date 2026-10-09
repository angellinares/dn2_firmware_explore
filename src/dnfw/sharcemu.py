"""Which digikit worktree runs our SHARC checks: one place for every script.

    from dnfw import sharcemu
    p.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())

DNFW_DIGIKIT_SHARC (or the older DIGIKIT_SHARC) overrides it. The default is a worktree
of m-dwyer/digikit's work/sharc-emulator, the branch this project tracks.

History: 6f812e9 (`digikit-wt-sharcemu`) until 2026-10-09; then 277760a
(`digikit-wt-sharcemu3`). The DSP gate suite gave the same output on both
(scripts/sharc_gate_suite.py compare old new2) except m5's amp-output peaks: 6f812e9
scaled a plain `Ia = MODIFY(Ib, Mc)` by 4 in byte space (sw 0x1c905f), which the PRM says
only the (nw) form does; 277760a adds Mc unscaled. Moving on also needed two fix-ups
of ours (scripts/sharc_dn2_fixups.py G10, G11).
"""

from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT = ROOT.parent / "digikit-wt-sharcemu3"
HEAD = "277760a"


def path() -> pathlib.Path:
    """The digikit checkout to use: the environment's, or DEFAULT."""
    env = os.environ.get("DNFW_DIGIKIT_SHARC") or os.environ.get("DIGIKIT_SHARC")
    return pathlib.Path(env) if env else DEFAULT
