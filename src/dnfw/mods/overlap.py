"""The ranges a dnfw build declares, against a digikit patchkit plan: every place both would use.

A step towards one image with our mods and digikit's runtime. patchkit's plan (`patchkit patch ... --plan FILE`,
the JSON beside its image) lists each write (cpu, addr, len), each hook site and the regions it fills. dnfw's
mods declare extents: section 3 offsets, RAM addresses, and the DSP boot stream. Both use ColdFire addresses
for the MAIN OS and RAM, so those compare directly. The DSP side does not: our extents are offsets in the
section 7 stream, patchkit's are DSP addresses. A mod that rebuilds the stream owns all of it, so any DSP
write of patchkit's is a collision there.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass

from . import RAM

MAIN_OS, DSP_STREAM = 3, 7


@dataclass(frozen=True)
class Use:
    """One range one side uses. SPACE is "cf" (ColdFire addresses: the MAIN OS image and RAM) or "dsp"."""

    owner: str
    space: str
    lo: int
    hi: int
    what: str

    def label(self) -> str:
        span = f"0x{self.lo:08x}..0x{self.hi:08x}" if self.space == "cf" else f"{self.hi - self.lo:,} B"
        return f"{self.owner}: {span} {self.what}"


def ours(named, base: int) -> list[Use]:
    """NAMED: (mod id, extents) as `mods apply` gathers them. BASE: the address of section 3's first payload byte."""
    out = []
    for mod_id, extents in named:
        for e in extents:
            if e.section == RAM:
                out.append(Use(mod_id, "cf", e.start, e.end, e.what))
            elif e.section == MAIN_OS:
                out.append(Use(mod_id, "cf", base + e.start, base + e.end, e.what))
            elif e.section == DSP_STREAM:
                out.append(Use(mod_id, "dsp", e.start, e.end, e.what))
    return out


def theirs(plan: dict, port: dict) -> list[Use]:
    """The plan's writes and hook sites, and the used part of each region (from the port file's region starts)."""
    out = []
    for w in plan.get("writes", []):
        space = "cf" if w["cpu"] == "cf" else "dsp"
        out.append(Use(w.get("owner", "patchkit"), space, w["addr"], w["addr"] + w["len"], f"{w['kind']} {w.get('what', '')}"))
    for h in plan.get("hooks", []):
        space = "cf" if h["cpu"] == "cf" else "dsp"
        out.append(Use(h["module"], space, h["addr"], h["addr"] + h["site_len"], f"hook site {h['anchor']}"))
    starts = {r["name"]: r for r in port.get("region", [])}
    for name, (used, _total) in plan.get("regions", {}).items():
        r = starts.get(name)
        if r and r.get("cpu") == "cf" and used:
            for lo, hi in _first_fit(r["start"], r["end"], r.get("excludes", []), used):
                out.append(Use("patchkit", "cf", lo, hi, f"region {name}, the part in use"))
    return out


def _first_fit(start: int, end: int, excludes, used: int) -> list[tuple[int, int]]:
    """The spans USED bytes fill when placed first fit from START, around the region's excludes."""
    spans, at = [], start
    for a, b in sorted(excludes) + [(end, end)]:
        if used <= 0:
            break
        take = min(used, max(0, a - at))
        if take:
            spans.append((at, at + take))
            used -= take
        at = max(at, b)
    return spans


# The kinds of collision, in the order the summary prints them
SAME = "both write the same bytes"
HOOK = "a patchkit hook site"
RAM_IN_REGION = "our RAM inside a patchkit region"
STREAM = "the DSP boot stream"


def collisions(mine: list[Use], other: list[Use]) -> list[tuple[str, str]]:
    """-> (kind, line) per collision; empty when the two can share an image."""
    found = []
    for a in (u for u in mine if u.space == "cf"):
        for b in (u for u in other if u.space == "cf"):
            if a.lo < b.hi and b.lo < a.hi:
                kind = HOOK if b.what.startswith("hook site") else RAM_IN_REGION if (
                    b.what.startswith("region") or b.what.startswith("place")) else SAME
                found.append((kind, f"{a.label()}  <->  {b.label()}"))
    streams = [u for u in mine if u.space == "dsp"]
    dsp = [u for u in other if u.space == "dsp"]
    if streams and dsp:
        owners = ", ".join(sorted({u.owner for u in streams}))
        found.append((STREAM, f"the DSP boot stream: {owners} rebuilds it, and patchkit writes {len(dsp)} DSP ranges "
                              f"(first: {dsp[0].owner} {dsp[0].what})"))
    return found


def load_port(path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)
