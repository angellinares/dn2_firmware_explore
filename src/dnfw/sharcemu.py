"""Which digikit worktree runs our SHARC checks: one place for every script.

    from dnfw import sharcemu
    p.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())

DNFW_DIGIKIT_SHARC (or the older DIGIKIT_SHARC) overrides it, and DNFW_SHARC_NATIVE_LIB
the native engine. The default is `digikit-main`, the checkout of ElekLabs/digikit's main
beside this repository, with the native engine it builds (`mise run gen:native-lib`, into
out/native/shared-core). From a worktree under .claude/worktrees/ the same checkout is found.

History: 6f812e9 (`digikit-wt-sharcemu`) until 2026-10-09; then 277760a
(`digikit-wt-sharcemu3`). The DSP gate suite gave the same output on both
(scripts/sharc_gate_suite.py compare old new2) except m5's amp-output peaks: 6f812e9
scaled a plain `Ia = MODIFY(Ib, Mc)` by 4 in byte space (sw 0x1c905f), which the PRM says
only the (nw) form does; 277760a adds Mc unscaled. Moving on also needed two fix-ups
of ours (scripts/sharc_dn2_fixups.py G10, G11). From 2026-10-21, digikit-main at 3ff156f9
(ElekLabs/digikit main, 203 commits past our last sync) and its shared-core native engine,
in place of 277760a and digikit-rust's 163a4e6. The Waverider gates give the same verdicts
on both, on main's DSP and on the load plan's batch A: m5 47/47 (step 4 still needs the
Python runner: fix-up G5), shape 21/21, sub 7/7, noise, pool 13/13, DCLK hold 4/4, and
taming on all 16 voice slots.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
# the folder that holds this repository and digikit's checkouts: a worktree in
# .claude/worktrees/NAME is three levels below the main checkout
SIBLINGS = ROOT.parents[3] if ROOT.parent.name == "worktrees" else ROOT.parent
DEFAULT = SIBLINGS / "digikit-main"
HEAD = "3ff156f9"


NATIVE = DEFAULT / "out/native/shared-core/target/release/sharc_native.dll"


def native_library() -> pathlib.Path:
    """digikit's native SHARC engine (`native/sharc` built with a generated core), for
    scripts/sharc_native.py: DNFW_SHARC_NATIVE_LIB, or the build in the digikit-main checkout."""
    env = os.environ.get("DNFW_SHARC_NATIVE_LIB")
    return pathlib.Path(env) if env else NATIVE


class _SameModule(importlib.abc.Loader):
    def __init__(self, module):
        self.module = module

    def create_module(self, spec):
        return self.module

    def exec_module(self, module):
        pass


class _MainLayout(importlib.abc.MetaPathFinder):
    """`sharc_run` -> `tools.sharc_dev.sharc_run`, and the same for every module there."""

    def __init__(self, names: set[str]):
        self.names = names

    def find_spec(self, fullname, path, target=None):
        if fullname.split(".")[0] not in self.names:
            return None
        module = importlib.import_module(f"tools.sharc_dev.{fullname}")
        return importlib.util.spec_from_loader(fullname, _SameModule(module))


def alias_main_layout(checkout: pathlib.Path) -> None:
    """digikit main (since 2026-10) imports its SHARC tools as `tools.sharc_dev.*`, while
    our scripts and pickled snapshots name them `sharc_run`, `sharc_core.values` and so on.
    Two copies of a module give two `Const` classes, and main's `to_native` refuses values
    of the other one. After this call both names are one module. Call it before the first
    import of a digikit module."""
    dev = checkout / "tools" / "sharc_dev"
    if str(checkout) not in sys.path:
        sys.path.insert(0, str(checkout))
    if any(isinstance(f, _MainLayout) for f in sys.meta_path):
        return
    names = {p.stem for p in dev.glob("*.py")} | {p.name for p in dev.iterdir() if (p / "__init__.py").exists()}
    sys.meta_path.insert(0, _MainLayout(names - {"__init__"}))


def path() -> pathlib.Path:
    """The digikit checkout to use: the environment's, or DEFAULT."""
    env = os.environ.get("DNFW_DIGIKIT_SHARC") or os.environ.get("DIGIKIT_SHARC")
    return pathlib.Path(env) if env else DEFAULT
