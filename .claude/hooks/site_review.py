"""After an edit to the site or the README, ask for the common sections to be reviewed.

A `PostToolUse` hook on Write|Edit. When the file just written is under `site/` or is
`README.md`, it injects a reminder: the owner asked (2026-10-08) that every update to
the web page reviews the sections that describe all the mods, and updates them when
they no longer match. The mechanical part is `scripts/site_check.py` (also the git
pre-commit hook); this covers the judgement part a script can't.

No dependencies beyond Python: the machine has no `jq`.
"""

import json
import re
import sys

REMINDER = (
    "Site edit: before committing, review the site's common sections and update any "
    "that no longer match: site/index.html's New features, Bug fixes (factory bugs, "
    "each with a Source link), Design tools and In progress tables, the top links, "
    "and README.md's mods table. Run `python scripts/site_check.py`; if a mod was "
    "added or its compatibility changed, rerun `dnfw mods matrix ... --page` on the "
    "site's pages (~8 min). For a fixed factory bug, give the owner the "
    "Description/Issue/Source/Fixed/Link text block (memory factory-bug-report-text)."
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    norm = path.replace("\\", "/")
    if re.search(r"(^|/)site/[^/].*\.(html|js|css)$", norm) or re.search(r"(^|/)README\.md$", norm):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": REMINDER}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
