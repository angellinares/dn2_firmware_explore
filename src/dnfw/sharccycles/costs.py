"""The cost of each counted event, where the number comes from, and the estimate.

`DEFAULTS` holds the manuals' numbers ("prm", "ee375", "ee412") and our guesses
("guess"), each with its unit: "cycles" per event, or "scale" on a count already
in PRM stall cycles (model.py). The instrument tunes them: fit.py writes a
costs file whose entries override these, each with source "fit" and the cases
it came from.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Cost:
    value: float
    unit: str            # "cycles" (per event) or "scale" (on PRM stall cycles)
    source: str          # prm | ee375 | ee412 | guess | fit
    note: str = ""


DEFAULTS: dict[str, Cost] = {
    "instructions": Cost(1, "cycles", "prm", "one issue per cycle, the pipeline full"),
    "emulated": Cost(0, "cycles", "guess", "steps the runner's fixups ran (already counted as instructions)"),
    # DAG (PRM Table 4-38, 4-40)
    "dag_load_use": Cost(1.0, "scale", "prm", "Ix = DM(..) -> use: 4 at d = 1, 4-38 #1"),
    "dag_move_use": Cost(1.0, "scale", "guess", "Ix = Rn -> use: not tabulated; priced as a load until measured"),
    "cjump_i6_use": Cost(1.0, "scale", "prm", "CJUMP/RFRAME -> I6/I7: 6, 4-40 #1-2"),
    # compute (PRM Table 4-36)
    "fwd_float": Cost(1, "cycles", "prm", "float compute/multiply -> dependent compute, 4-36 #1"),
    "fwd_fmul_to_fixed": Cost(1, "cycles", "guess", "float multiply -> fixed ALU, 4-36 #3 (number lost in the PDF)"),
    "anomaly_20000072": Cost(1, "cycles", "guess", "float into F0 -> single-operand compute: a stall, length unpublished"),
    # branches (EE-375 Table 7, read in btb.py; PRM 4-39..4-42)
    "br_taken_ok": Cost(2, "cycles", "ee375", "conditional, predicted taken, taken"),
    "br_taken_ok_db": Cost(0, "cycles", "ee375", ""),
    "br_wrong_nottaken": Cost(11, "cycles", "ee375", "predicted taken, not taken"),
    "br_wrong_taken": Cost(11, "cycles", "prm", "predicted not taken (or masked), taken: 4-39 #2"),
    "br_wrong_taken_db": Cost(9, "cycles", "prm", ""),
    "br_uncond_hit": Cost(2, "cycles", "ee375", "unconditional, in the BTB"),
    "br_uncond_hit_db": Cost(0, "cycles", "ee375", ""),
    "br_uncond_miss": Cost(6, "cycles", "prm", "4-39 #1"),
    "br_uncond_miss_db": Cost(4, "cycles", "prm", ""),
    "rti": Cost(7, "cycles", "prm", "4-40 note **"),
    "loop_exit": Cost(11, "cycles", "prm", "termination of an E2-active, short or arithmetic loop, 4-41"),
    "loop_exit_f1": Cost(0, "cycles", "prm", "termination of an F1-active counter loop run 11 instructions or more, 4-33"),
    # memory (PRM Table 4-35; EE-412 Table 6)
    "l1_same_block": Cost(1, "cycles", "prm", "two accesses to one L1 block in a cycle, 4-35"),
    "pm_conflict_miss": Cost(1, "cycles", "prm", "PM data access, conflict-cache miss, 4-35"),
    "l2_hit_rd": Cost(0, "cycles", "guess", "data cache hit"),
    "l2_hit_wr": Cost(0, "cycles", "guess", ""),
    "l2_miss_rd": Cost(30, "cycles", "guess", "a 64-byte line from L2"),
    "l2_miss_wr": Cost(30, "cycles", "guess", "write-allocate"),
    "ddr_hit_rd": Cost(0, "cycles", "guess", ""),
    "ddr_hit_wr": Cost(0, "cycles", "guess", ""),
    "ddr_miss_rd": Cost(100, "cycles", "guess", "a 64-byte line from DDR3"),
    "ddr_miss_wr": Cost(100, "cycles", "guess", "write-allocate"),
    "spi_hit_rd": Cost(0, "cycles", "guess", ""),
    "spi_miss_rd": Cost(500, "cycles", "guess", ""),
    "l1sys_rd": Cost(30, "cycles", "guess", "L1 through the completer port"),
    "l1sys_wr": Cost(10, "cycles", "guess", ""),
    "cmmr_rd": Cost(2, "cycles", "prm", "0-4, 4-43"),
    "cmmr_wr": Cost(2, "cycles", "prm", "0-4, 4-43"),
    "smmr_rd": Cost(43, "cycles", "ee412", "Table 6, 1 GHz / 500 MHz SYSCLK, typical"),
    "smmr_wr": Cost(1, "cycles", "guess", "posted; EE-412's 44 is with a SYNC after"),
    "unmapped_rd": Cost(0, "cycles", "guess", ""),
    "unmapped_wr": Cost(0, "cycles", "guess", ""),
    "icache_miss_l2": Cost(30, "cycles", "guess", "a 64-byte line of code from L2"),
    "icache_miss_ddr": Cost(100, "cycles", "guess", ""),
    "icache_miss_spi": Cost(500, "cycles", "guess", ""),
    "fetch_unmapped": Cost(0, "cycles", "guess", ""),
}


def load(path: pathlib.Path | None) -> dict[str, Cost]:
    """DEFAULTS, overridden by PATH's {"costs": {key: {value, unit, source, note}}}."""
    table = dict(DEFAULTS)
    if path is not None and path.exists():
        for key, e in json.loads(path.read_text(encoding="utf-8"))["costs"].items():
            table[key] = Cost(float(e["value"]), e.get("unit", table.get(key, Cost(0, "cycles", "")).unit),
                              e.get("source", "fit"), e.get("note", ""))
    return table


def estimate(counts: dict[str, float], table: dict[str, Cost]) -> tuple[float, dict[str, float], list[str]]:
    """COUNTS priced by TABLE -> (cycles, cycles per key, keys TABLE has no price for)."""
    parts, unpriced = {}, []
    for key, n in counts.items():
        cost = table.get(key)
        if cost is None:
            unpriced.append(key)
            continue
        parts[key] = n * cost.value
    return sum(parts.values()), parts, sorted(unpriced)
