"""What a project's licence lets this repository do with its code, from the project's own files.

This repository is under AGPL-3.0-or-later. `check(path)` reads a local checkout and returns a verdict
from one fixed table, with the file and line behind it:

- COPY: the code can come into this repository, with the listed duties
- OWNER: the licence allows the combination, and the repository owner decides
- NO: the code stays out of this repository
- ASK: the tool cannot read the licence, so a person reads it

A LICENSE file does not settle "only" or "or later". GPL-2 text is the same in both cases, so the
project's own statement decides: the README's licence section, its NOTICE, or its manifest. With no such
statement, the tool reads the licence as "only".

This is a reading of a project's statements, not legal advice. It says nothing about a third party's
rights in what the project contains, so it always prints that warning.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re

OURS = "AGPL-3.0-or-later"
COPY, OWNER, NO, ASK = "COPY", "OWNER", "NO", "ASK"
EXIT = {COPY: 0, OWNER: 2, ASK: 2, NO: 1}

KEEP = "Keep its notices and mark what you change."
THIRD_PARTY = "Keep its notice in THIRD-PARTY.md."
VERSION_3 = "The combined work can use AGPL version 3 only, which is narrower than our licence."

# id -> (verdict, why and what to do). Every licence the tool can name is here.
TABLE = {
    "AGPL-3.0-or-later": (COPY, f"The same licence as ours. {KEEP}"),
    "AGPL-3.0-only": (OWNER, f"Compatible. {VERSION_3}"),
    "GPL-3.0-or-later": (COPY, f"GPL section 13 and AGPL section 13 allow the combination. {KEEP}"),
    "GPL-3.0-only": (OWNER, f"GPL section 13 and AGPL section 13 allow the combination. {VERSION_3}"),
    "GPL-2.0-or-later": (COPY, f"Take it forward as GPL-3.0-or-later. {KEEP}"),
    "GPL-2.0-only": (NO, "GPL-2.0-only cannot combine with AGPL-3.0. Do not copy its code."),
    "Apache-2.0": (COPY, f"Compatible with version 3. {THIRD_PARTY} Keep its NOTICE file, if it has one."),
    "MIT": (COPY, THIRD_PARTY),
    "BSD": (COPY, THIRD_PARTY),
    "ISC": (COPY, THIRD_PARTY),
    "CC0-1.0": (COPY, "CC0 asks for no notice. Credit the project."),
    "none": (NO, "No licence gives no right to copy. Use what you learn, in your own words."),
    "mixed": (ASK, "Parts of the project have different licences. Check the licence of the part you want."),
    "unknown": (ASK, "The tool does not know this text. A person reads it."),
}

# The owner's rules, by the checkout's folder name. A rule outranks a COPY from the table.
STANDING = {
    "dn2-cfw": "The owner keeps this project method only, whatever its licence allows. Ask before you copy its code.",
}

ELEKTRON = "No project's licence clears Elektron's material or another third party's. Check what you copy."

LICENCE_FILES = re.compile(r"^(LICEN[CS]E|COPYING)([.-].*)?$", re.IGNORECASE)
# Anywhere in the tree: also a prefixed name such as spleen-LICENSE, but not a script about licences.
ANY_LICENCE_FILE = re.compile(r"^(.*[-_.])?(LICEN[CS]E|COPYING)(\.(md|txt|rst))?$", re.IGNORECASE)
SKIP_DIRS = {".git", "node_modules", "__pycache__", "target", "out", "dist", "build"}
# A license heading in Markdown, or a plain README's heading with its line of = or -.
HEADING = re.compile(r"^\s*#{1,6}\s+(.*)$")
UNDERLINE = re.compile(r"^\s*(=+|-+)\s*$")
LICENCE_WORD = re.compile(r"licen[cs]", re.IGNORECASE)
MANIFEST_LINE = re.compile(r"""^\s*"?license"?\s*[=:]\s*(.+)$""", re.IGNORECASE)
NOTICE_LINES = 12
BRACKETS = re.compile(r"\([^()]*\)")       # "uses X (GPL-2.0-or-later)" is X's licence, not this project's
PORT_LINE = re.compile(r"\b(ports? of|ported from)\b", re.IGNORECASE)

FAMILY = {
    "AGPL": r"(?:AGPL|Affero)",
    "GPL": r"(?<![AL])(?:GPL|GNU General Public)",
}
PERMISSIVE = {"MIT": r"\bMIT\b", "Apache-2.0": r"\bApache\b", "BSD": r"\bBSD\b", "CC0-1.0": r"\bCC0\b", "ISC": r"\bISC\b"}


@dataclasses.dataclass
class Result:
    path: str
    licence: str
    verdict: str
    why: str
    evidence: list[str]
    other_licences: list[str]
    notice: str | None
    ports: list[str]

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def identify(text: str) -> str | None:
    """A licence file's text -> its family and version, or None. 'or later' never comes from here."""
    head = text[:4000]
    if re.search(r"GNU AFFERO GENERAL PUBLIC LICENSE", head) and re.search(r"Version 3", head):
        return "AGPL-3.0"
    if re.search(r"GNU LESSER GENERAL PUBLIC LICENSE", head):
        return None
    if re.search(r"GNU GENERAL PUBLIC LICENSE", head):
        if re.search(r"Version 3", head):
            return "GPL-3.0"
        if re.search(r"Version 2", head):
            return "GPL-2.0"
        return None
    if re.search(r"Apache License", head) and re.search(r"Version 2\.0", head):
        return "Apache-2.0"
    if "Permission is hereby granted, free of charge" in head:
        return "MIT"
    if "Redistribution and use in source and binary forms" in head:
        return "BSD"
    if re.search(r"CC0 1\.0 Universal", head):
        return "CC0-1.0"
    if "Permission to use, copy, modify, and/or distribute this software for any purpose" in head:
        return "ISC"
    return None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _readme_section(path: pathlib.Path) -> list[tuple[int, str]]:
    """The README's licence section, as (line number, text). A plain mention elsewhere does not count."""
    lines = _read(path).splitlines()
    out, inside, level = [], False, 0
    for k, line in enumerate(lines):
        title, this_level = None, 0
        match = HEADING.match(line)
        if match:
            title, this_level = match.group(1), len(line) - len(line.lstrip().lstrip("#"))
        elif k + 1 < len(lines) and line.strip() and UNDERLINE.match(lines[k + 1]):
            title, this_level = line, 1
        if title is not None:
            if LICENCE_WORD.search(title):
                inside, level = True, this_level
                continue
            if inside and this_level <= level:
                inside = False
        if inside and line.strip() and not UNDERLINE.match(line):
            out.append((k + 1, line))
    return out


def _statements(root: pathlib.Path) -> list[tuple[str, int, str]]:
    """The project's own licence statements, as (file, line number, text)."""
    out = []
    for name in sorted(p.name for p in root.iterdir() if p.is_file() and p.name.upper().startswith("README")):
        out += [(name, n, text) for n, text in _readme_section(root / name)]
    for name in ("NOTICE", "NOTICE.md", "NOTICE.txt"):
        if (root / name).is_file():
            # The top only: lower down, a NOTICE credits other projects and quotes their licences.
            out += [(name, k + 1, line) for k, line in enumerate(_read(root / name).splitlines()[:NOTICE_LINES]) if line.strip()]
    for name in ("pyproject.toml", "Cargo.toml", "package.json"):
        if (root / name).is_file():
            for k, line in enumerate(_read(root / name).splitlines()):
                match = MANIFEST_LINE.match(line)
                if match:
                    out.append((name, k + 1, match.group(1)))
    return out


def _says_later(joined: str, family: str, version: str) -> bool:
    name = FAMILY[family]
    number = version.split(".")[0]
    short = rf"{name}[- ]?(?:v|version )?{number}(?:\.0)?(?:[- ]?(?:or[- ]later)|\+)"
    prose = rf"{name}.{{0,220}}?version {number}\b.{{0,60}}?\bor\b.{{0,40}}?later"
    return bool(re.search(short, joined, re.IGNORECASE | re.DOTALL) or re.search(prose, joined, re.IGNORECASE | re.DOTALL))


def _says_only(joined: str, family: str, version: str) -> bool:
    number = version.split(".")[0]
    return bool(re.search(rf"{FAMILY[family]}[- ]?(?:v|version )?{number}(?:\.0)?[- ]only", joined, re.IGNORECASE))


def _families_stated(joined: str) -> list[str]:
    found = []
    for family, name in FAMILY.items():
        for match in re.finditer(rf"{name}[^0-9\n]{{0,30}}?(\d)(?:\.0)?", joined, re.IGNORECASE):
            base = f"{family}-{match.group(1)}.0"
            if base not in found:
                found.append(base)
    for licence, pattern in PERMISSIVE.items():
        if re.search(pattern, joined) and licence not in found:
            found.append(licence)
    return found


def _other_licence_files(root: pathlib.Path, top: pathlib.Path | None) -> list[str]:
    out = []
    stack = [root]
    while stack:
        here = stack.pop()
        for entry in sorted(here.iterdir()):
            if entry.is_dir() and not entry.is_symlink():
                if entry.name not in SKIP_DIRS:
                    stack.append(entry)
            elif ANY_LICENCE_FILE.match(entry.name) and entry != top:
                out.append(f"{entry.relative_to(root).as_posix()}: {identify(_read(entry)) or 'unknown'}")
    return sorted(out)


def _ports(root: pathlib.Path) -> list[str]:
    out = []
    for path in sorted(p for p in root.iterdir() if p.is_file() and p.name.upper().startswith("README")):
        out += [f"{path.name}:{k + 1}: {line.strip()[:150]}" for k, line in enumerate(_read(path).splitlines()) if PORT_LINE.search(line)]
    return out


def _with_scope(base: str, later: bool, only: bool) -> str:
    """AGPL-3.0, GPL-3.0 or GPL-2.0 with its scope. With no statement, or a conflict, the narrower reading."""
    return f"{base}-{'or-later' if later and not only else 'only'}"


def check(root: pathlib.Path) -> Result:
    root = pathlib.Path(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    top = next((p for p in sorted(root.iterdir()) if p.is_file() and LICENCE_FILES.match(p.name)), None)
    statements = _statements(root)
    joined = BRACKETS.sub(" ", "\n".join(text for _, _, text in statements))
    evidence = [f"{name}:{line}: {text.strip()[:150]}" for name, line, text in statements if LICENCE_WORD.search(text) or _families_stated(text)]
    base = identify(_read(top)) if top else None
    others = _other_licence_files(root, top)

    if top:
        evidence.insert(0, f"{top.name}: {base or 'text not recognised: ' + _read(top).strip().splitlines()[0][:80]}")
    if top and base is None:
        licence = "unknown"
    elif top:
        family = base.split("-")[0]
        licence = _with_scope(base, _says_later(joined, family, base.split("-")[1]), _says_only(joined, family, base.split("-")[1])) if family in FAMILY else base
    else:
        stated = _families_stated(joined)
        if not stated:
            licence = "mixed" if others else "none"
        elif len(stated) > 1:
            licence = "mixed"
        elif stated[0].split("-")[0] in FAMILY:
            family, version = stated[0].split("-")
            licence = _with_scope(stated[0], _says_later(joined, family, version), _says_only(joined, family, version))
        else:
            licence = stated[0]

    verdict, why = TABLE[licence]
    rule = STANDING.get(root.resolve().name)
    if rule and verdict == COPY:
        verdict, why = OWNER, f"{rule} The licence alone: {why}"
    return Result(str(root), licence, verdict, why, evidence[:12], others,
                  next((n for n in ("NOTICE", "NOTICE.md", "NOTICE.txt") if (root / n).is_file()), None), _ports(root))


def render(r: Result) -> str:
    lines = [f"{r.verdict}: {r.path}", f"  licence: {r.licence}, against ours: {OURS}", f"  {r.why}"]
    lines += ["  evidence:"] + [f"    {e}" for e in r.evidence or ["none found"]]
    if r.notice:
        lines.append(f"  read {r.notice}: it can add terms that travel with the code")
    if r.other_licences:
        lines += ["  other licence files, which apply to their own folders:"] + [f"    {x}" for x in r.other_licences[:12]]
        if len(r.other_licences) > 12:
            lines.append(f"    and {len(r.other_licences) - 12} more")
    if r.ports:
        lines += ["  the README names ports, so check their source:"] + [f"    {x}" for x in r.ports[:8]]
    lines.append(f"  {ELEKTRON}")
    return "\n".join(lines)


def as_json(results: list[Result]) -> str:
    return json.dumps([r.as_dict() for r in results], indent=1)
