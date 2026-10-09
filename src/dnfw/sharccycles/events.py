"""The per-step record the cycle model consumes."""

from __future__ import annotations

from dataclasses import dataclass

from .forms import Static

# how an I register got its new value in a step
LOAD, MOVE, IMM, DAG = "load", "move", "imm", "dag"


@dataclass(frozen=True)
class Step:
    pc: int                                    # short-word address
    static: Static
    taken: bool | None = None                  # a branch's outcome; None when not a branch
    in_loop: bool = False                      # a hardware loop was active when it issued
    loop_exit: bool = False                    # a hardware loop terminated at this step
    reads: tuple[int, ...] = ()                # data addresses read
    writes: tuple[int, ...] = ()               # data addresses written
    ireg_writes: tuple[tuple[int, str], ...] = ()   # (I register 0..15, LOAD/MOVE/IMM/DAG)
    pm_data: bool = False                      # a data access on the PM bus
    emulated: bool = False                     # the runner's fixups ran it, not the runner
    loop_f1: bool = False                      # that loop was F1-active: its exit costs nothing
