"""Each mod's version and what changed in it.

A mod's version is three numbers, `MAJOR.MINOR.PATCH`:

- **PATCH** goes up for a fix: the mod does what it already said it did.
- **MINOR** goes up when the mod gains something: a new control, mode or option.
- **MAJOR** goes up when a project made on the earlier version may not behave the
  same on the new one.

A mod published on the site starts at 1.0.0; one that is in the registry and not
yet published starts at 0.1.0. Numbering began on 2026-10-11, so a mod's first
entry is that day's state, not its whole past.

`HISTORY` is the one place a version is written. The CLI (`dnfw mods list`,
`dnfw mods changelog`) and the site's pages read it: the pages hold generated
regions (`<!-- dnfw:version ID -->`, `<!-- dnfw:changes ID -->`) that
`dnfw mods changelog --write` fills and `test/test_mods_history.py` compares.
The same command writes `site/js/mods/versions.js` (`--js`), which the site
uses to put the version in the name of the file a user downloads.

To release a change: add a `Release` at the top of the mod's tuple, in words a
user reads (what they see or do differently), then run
`dnfw mods changelog --write site/*.html --js site/js/mods/versions.js`.

One subject: that record and its two renderings.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

FIRST = "2026-10-11"
VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Release:
    version: str
    date: str
    changes: tuple[str, ...]

    @property
    def key(self) -> tuple[int, int, int]:
        return tuple(int(n) for n in self.version.split("."))


def _first(version: str, *more: str) -> tuple[Release, ...]:
    return (Release(version, FIRST, ("First numbered version.",) + more),)


PUBLISHED = _first("1.0.0")
UNPUBLISHED = _first("0.1.0", "Not published on the site yet.")

# Newest first.
HISTORY: dict[str, tuple[Release, ...]] = {
    "arpmodes": PUBLISHED,
    "arpplocks": UNPUBLISHED,
    "arpscale": UNPUBLISHED,
    "bootscreen": PUBLISHED,
    "fxmod": (
        Release("1.0.1", "2026-10-15", (
            "You can now combine this mod with Waverider, in either order. The FX destinations in "
            "the DEST list operate as before.",
        )),
    ) + PUBLISHED,
    "layermidi": PUBLISHED,
    "lfo4": (
        Release("1.0.2", "2026-10-15", (
            "You can now combine this mod with Waverider, in either order. LFO4 operates as before.",
        )),
        Release("1.0.1", "2026-10-11", (
            "Projects you save or load with LFO4 no longer have LFO data written into them.",
        )),
    ) + _first("1.0.0", "Unavailable for now: song data can be damaged in projects used with it."),
    "lfolength": (
        Release("1.0.1", "2026-10-15", (
            "You can now combine this mod with Waverider. Its code is now at a different place in "
            "RAM. The LFOs operate as before.",
        )),
    ) + PUBLISHED,
    "lfowaves": PUBLISHED,
    "midiarp": PUBLISHED,
    "moddest": PUBLISHED,
    "reloadconfirm": PUBLISHED,
    "songguard": UNPUBLISHED,
    "transients": PUBLISHED,
    "usbprobe": UNPUBLISHED,
    "waverider": (
        Release("0.3.3", "2026-10-18", (
            "The short lists turn as the other machines' short lists do: a step needs a longer turn. "
            "That covers TYPE on page 5, OCT, WAVE, SRC and the noise TYPE on page 3, MOVE1, MOVE2, "
            "TRIG, PRST, SYN1 and SYN2.",
        )),
        Release("0.3.2", "2026-10-18", (
            "Every knob on Waverider's five pages now answers MIDI CC and NRPN. Pages 1 to 4 use the "
            "numbers each knob place has on the other machines: CC 40 to 77 and NRPN 1:73 to 1:104. "
            "Page 5 uses CC 12, 15, 35, 36, 37, 83, 93 and 119, and NRPN 1:112 to 1:119.",
            "When you turn a Waverider knob with MIDI out on, the knob sends the same number.",
            "A CC or NRPN sent to a track that is not on the screen now keeps that track's own limits.",
        )),
        Release("0.3.1", "2026-10-17", (
            "SLW1 and SLW2 on page 4 now turn the other way: Off is at the far left, and the slew gets "
            "longer to the right. A new sound starts with the slew off. A sound saved with an earlier "
            "version plays its SLW the other way round, so set SLW1 and SLW2 again on it.",
        )),
        Release("0.3.0", "2026-10-17", (
            "Alpha 5. WARP bends the phase of the two oscillators, and FM lets osc 2 change the phase of "
            "osc 1. NPOS, P1 and P2 do not change the sound yet.",
            "A sound with WARP and FM at 0 sounds as before.",
        )),
        Release("0.2.0", "2026-10-17", (
            "Page 5 plays: FOLD folds the oscillators' wave, and TYPE Ring or AM mixes osc 1 with osc 2 "
            "by AMT. WARP, FM, NPOS, P1 and P2 do not change the sound yet.",
            "TYPE offers Off, Ring and AM. A sound with page 5 at 0 sounds as before.",
        )),
        Release("0.1.3", "2026-10-17", (
            "You can now combine Waverider with LFO modulation of the FX and with the fourth LFO, "
            "in either order.",
        )),
        Release("0.1.2", "2026-10-17", (
            "Alpha 3. A turn of TRIM no longer clicks while a sound plays. The level now moves to the "
            "knob's value over up to 0.1 s.",
        )),
        Release("0.1.1", "2026-10-15", (
            "Alpha 2. On page 4, SMT1 and SMT2 are now SLW1 and SLW2 (slew). The header shows Osc1 "
            "POS Slew and Osc2 POS Slew. The slew operates as before, and saved sounds keep their values.",
            "The page has a Technical tab: the table formats, the files that DNX accepts, how the reader "
            "plays a table, DCLK, SLW and SYN, and the noise.",
        )),
        Release("0.1.0", "2026-10-15", (
            "The first public build (alpha). Waverider 0.1.0 has two wavetable oscillators with MOVE, a "
            "sub-oscillator, noise, sound options and wavetable pools from the +Drive. Page 5 is for "
            "a future version.",
        )),
    ),
}


def version(mod_id: str) -> str:
    """The mod's current version."""
    return HISTORY[mod_id][0].version


def problems(mod_ids) -> list[str]:
    """What is wrong with the record for these mods: a missing history, a version
    or date that does not parse, an entry out of order, or an empty one."""
    out = [f"{m}: no history" for m in sorted(set(mod_ids) - set(HISTORY))]
    out += [f"{m}: has a history and is not a mod" for m in sorted(set(HISTORY) - set(mod_ids))]
    for mod_id, releases in sorted(HISTORY.items()):
        for r in releases:
            if not VERSION.match(r.version):
                out.append(f"{mod_id}: {r.version!r} is not MAJOR.MINOR.PATCH")
            if not DATE.match(r.date):
                out.append(f"{mod_id} {r.version}: {r.date!r} is not YYYY-MM-DD")
            if not r.changes or not all(c.strip() for c in r.changes):
                out.append(f"{mod_id} {r.version}: says nothing changed")
        good = [r for r in releases if VERSION.match(r.version)]
        for newer, older in zip(good, good[1:]):
            if newer.key <= older.key or newer.date < older.date:
                out.append(f"{mod_id}: {newer.version} ({newer.date}) is listed above "
                           f"{older.version} ({older.date}) and is not newer")
    return out


def version_html(mod_id: str) -> str:
    """The version as the mod list shows it beside the mod's id."""
    return f"v{version(mod_id)}"


def changes_html(mod_id: str) -> str:
    """The mod's releases, newest first, as the page's list."""
    rows = []
    for r in HISTORY[mod_id]:
        items = "".join(f"<li>{html.escape(c)}</li>" for c in r.changes)
        rows.append(f'  <dt><span class="version">v{r.version}</span> <time datetime="{r.date}">{r.date}</time></dt>\n'
                    f"  <dd><ul>{items}</ul></dd>")
    return '<dl class="changes">\n' + "\n".join(rows) + "\n</dl>"


def versions_js() -> str:
    """`site/js/mods/versions.js`: each mod's current version, for the download's name."""
    lines = ["// Generated by `dnfw mods changelog --js` from src/dnfw/mods/history.py. Do not edit.",
             "export const VERSIONS = {"]
    lines += [f'  {mod_id}: "{version(mod_id)}",' for mod_id in sorted(HISTORY)]
    return chr(10).join(lines + ["};", ""])


def changes_text(mod_id: str) -> str:
    """The same, for a terminal."""
    lines = []
    for r in HISTORY[mod_id]:
        lines.append(f"  v{r.version}  {r.date}")
        lines += [f"    - {c}" for c in r.changes]
    return "\n".join(lines)


VERSION_REGION = re.compile(r"(<!-- dnfw:version ([a-z0-9]+) -->).*?(<!-- /dnfw:version -->)", re.S)
CHANGES_REGION = re.compile(r"(<!-- dnfw:changes ([a-z0-9]+) -->).*?(<!-- /dnfw:changes -->)", re.S)


def rewrite(text: str) -> str:
    """TEXT with every version and changes region filled from `HISTORY`."""
    text = VERSION_REGION.sub(lambda m: m.group(1) + version_html(m.group(2)) + m.group(3), text)
    return CHANGES_REGION.sub(lambda m: m.group(1) + "\n" + changes_html(m.group(2)) + "\n" + m.group(3), text)


def regions(text: str) -> tuple[set[str], set[str]]:
    """(mods with a version region, mods with a changes region) in TEXT."""
    return ({m.group(2) for m in VERSION_REGION.finditer(text)},
            {m.group(2) for m in CHANGES_REGION.finditer(text)})
