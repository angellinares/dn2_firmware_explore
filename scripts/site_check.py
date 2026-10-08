"""Check the site's common sections against the mods, fast enough for a pre-commit hook.

    python scripts/site_check.py            # exit 1, with what to fix, if anything is off

The site (`site/`) and the README describe the mods in places that drift when one is
added or changes: the index's sections, the README's mods table, the shared parts of
every tool page, and the compatibility table `dnfw mods matrix` generates. This checks:

- **every mod is on the index:** its own entry (`<span class="mod-id">ID</span>`, under
  New features or Bug fixes), or named as `<code>ID</code>` in the In progress section;
  `DIAGNOSTIC` mods are exempt;
- **every mod is in the README table**, except `DIAGNOSTIC` and `NOT_OFFERED` ones;
- **the generated tables cover every mod:** each page's `dnfw:matrix` / `dnfw:matrix-row`
  header has exactly the registry's ids, and every tool page whose mod is in the
  registry has its `dnfw:combines` region filled. A new mod, or a removed one, fails
  here until `dnfw mods matrix --page ...` is rerun (it takes ~8 minutes, so the hook
  doesn't run it on every commit);
- **every tool page has the shared parts:** a link back to `index.html`, the footer's
  "Not affiliated with or endorsed by Elektron", and on every page that builds firmware
  the "prove your way back" warning.

The judgement part (is the In progress table still true? does a new fix belong under Bug
fixes?) can't be checked by a script: the Claude Code hook in `.claude/settings.json`
reminds the agent to review those sections when a site file is edited.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SITE = ROOT / "site"
DIAGNOSTIC = {"usbprobe"}            # a measuring tool for our own builds, never offered
NOT_OFFERED = {"waverider"}          # in development: on the index's In progress table, not the README's
SHARED = (("a link back to the index", 'href="index.html"', False),
          ("the 'prove your way back' warning", "Prove your way back", True),
          ("the footer's disclaimer", "Not affiliated with or endorsed by Elektron", False))
MATRIX_HEAD = re.compile(r"<!-- dnfw:matrix(?:-row [a-z0-9]+)? -->.*?<thead>(.*?)</thead>", re.S)
COMBINES = re.compile(r"<!-- dnfw:combines ([a-z0-9]+) -->(.*?)<!-- /dnfw:combines -->", re.S)


def problems() -> list[str]:
    from dnfw.cli.mods import REGISTRY
    ids = set(REGISTRY)
    out = []
    index = (SITE / "index.html").read_text(encoding="utf-8")
    entries = set(re.findall(r'<span class="mod-id">([a-z0-9]+)</span>', index))
    progress = index.split('id="in-progress"', 1)[1] if 'id="in-progress"' in index else ""
    named = set(re.findall(r"<code>([a-z0-9]+)</code>", progress))
    for mid in sorted(ids - DIAGNOSTIC - entries - named):
        out.append(f"site/index.html: mod `{mid}` has no entry (New features / Bug fixes) "
                   "and isn't named in In progress")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    rows = set(re.findall(r"^\| `([a-z0-9]+)` \|", readme, re.M))
    for mid in sorted(ids - DIAGNOSTIC - NOT_OFFERED - rows):
        out.append(f"README.md: mod `{mid}` is missing from the mods table")
    for page in sorted(SITE.glob("*.html")):
        text = page.read_text(encoding="utf-8")
        rel = page.relative_to(ROOT).as_posix()
        for head in MATRIX_HEAD.findall(text):
            cols = set(re.findall(r"<code>([a-z0-9]+)</code>", head))
            if cols != ids:
                gone, new = sorted(cols - ids), sorted(ids - cols)
                out.append(f"{rel}: the compatibility table is stale (new: {new}, gone: {gone}); "
                           "rerun `dnfw mods matrix IMAGE --page` on the site's pages")
        for mid, body in COMBINES.findall(text):
            if mid in ids and not body.strip():
                out.append(f"{rel}: the `{mid}` Combines line is empty; rerun `dnfw mods matrix`")
        if page.name != "index.html":
            builds = "Build firmware" in text     # the bench builds wavetables, not firmware
            for what, needle, only_builders in SHARED:
                if (builds or not only_builders) and needle not in text:
                    out.append(f"{rel}: missing {what}")
    return out


def main() -> int:
    found = problems()
    for p in found:
        print(f"site_check: {p}")
    if found:
        print(f"site_check: {len(found)} problem(s). Fix them, or commit with --no-verify deliberately.")
        return 1
    print("site_check: the site's common sections match the mods")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
