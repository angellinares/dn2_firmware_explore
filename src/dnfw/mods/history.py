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

To release a change: add a `Release` at the top of the mod's tuple, in words a
user reads (what they see or do differently), then run
`dnfw mods changelog --write site/*.html`.

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
    "bootscreen": PUBLISHED,
    "fxmod": PUBLISHED,
    "layermidi": PUBLISHED,
    "lfo4": _first("1.0.0", "Unavailable for now: song data can be damaged in projects used with it."),
    "lfolength": PUBLISHED,
    "lfowaves": PUBLISHED,
    "midiarp": PUBLISHED,
    "moddest": PUBLISHED,
    "reloadconfirm": PUBLISHED,
    "songguard": UNPUBLISHED,
    "transients": PUBLISHED,
    "usbprobe": UNPUBLISHED,
    "waverider": UNPUBLISHED,
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
