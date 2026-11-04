# Contributing

This file holds the house rules for changes to this repository. A pull request (PR) that follows them
needs no style review, and a reviewer comments only on what the change does.

The repository owner merges every PR. Nobody pushes to `main`.

## 1. Agree the design first

- **A new mod or a new feature:** open an issue first, or start the discussion on Discord. Describe what
  the user sees and does. Build after the owner agrees the design.
- **After the design is agreed:** a new idea does not block the PR. Open a new issue for it.
- **A bug fix, a test or a doc fix:** open the PR directly.

## 2. Branches and pull requests

1. Fork the repository, or ask for write access.
2. Make one branch for each feature, from `main`.
3. Install the hooks once: `git config core.hooksPath .githooks`. The pre-push hook refuses a push to
   `main`. The pre-commit hook runs `scripts/site_check.py`.
4. Open the PR against `main`.
5. Tick **Allow edits by maintainers**. The maintainers then fix small things on your branch
   themselves (see section 7).

**Conflicts:** when `main` moves on, the maintainers rebase your branch and resolve the conflicts
before they merge. You do not have to.

**Checks on GitHub:** every PR runs the fast tests and `scripts/site_check.py`
(`.github/workflows/checks.yml`). The tests that need the stock firmware skip there, because the
firmware is not in the repository. The writing check of section 6 runs on the lines that a PR adds to Markdown files.
It reports only, and it does not block the merge.

**Labels:**

| Label | Meaning |
|---|---|
| `proposal` | a design to agree before building |
| `design agreed` | the owner agreed the design, so a PR can start |
| `needs unit test` | the PR waits for the test on the instrument |
| `unit test passed` | the test on the instrument passed |

## 3. What a PR contains

### Every PR

- The tests pass: `pytest -m "not slow"`. Add a test for each new behaviour.
- The PR text says what changes for the user, and how you checked it.

### A new mod

- The mod is in `src/dnfw/mods/<id>.py`, with `ID`, `NAME`, `SUMMARY`, `DEVICE`, `SECTION`,
  `extents(firmware)` and `apply(firmware, ...)`. It is registered in `REGISTRY` in
  `src/dnfw/cli/mods.py`.
- `extents` declares every byte the mod changes. A build refuses a change that no mod declares.
- The site's patcher builds the same bytes as the CLI. Add the mod to
  `test/test_js_build_matches_cli.py`.
- The mod has a version and an entry in `src/dnfw/mods/history.py`.
- The site has an entry for the mod, and the README's mods table lists it. `scripts/site_check.py`
  fails until both are there.
- If the mod changes bytes or compatibility, run `dnfw mods matrix` again (about 8 minutes). The
  pre-commit hook tells you when.

### A change to a mod

- Increase the mod's version and add a line to `src/dnfw/mods/history.py`.

### A change that you can see

This includes device pages, emulator captures, figures, site pages and manual images.

- Put the images in the PR text. A list of file names is not enough.
- Link each image at the full commit SHA (`raw.githubusercontent.com/.../<full SHA>/...`). A link to a
  branch breaks after a rebase.
- Show a before image and an after image.
- Show emulator frames inverted (white on black, as the screen) and scaled 2:1.

## 4. Checks before an instrument

The README lists the checks, in "How we check a change before it reaches an instrument". For a mod:

- The image boots from reset in the emulator (`boot_gate`), with zero hits at the fault reporter.
- The mod has an emulator harness, `scripts/emu_<mod>.py`, with stock as the control.
- A DSP change runs in the SHARC runner against a reference, on all 16 voices.

## 5. Tests on the instrument

- **Every code change gets a test on an instrument.** The owner runs it on the project's Digitone II,
  and posts the result in the PR. The owner can drop the test for a change with low risk.
- **Your own test is welcome.** Say what you tested, and give the `.syx` file name. The name holds the
  OS version and the version of each mod.
- **A DSP or sound change** also gets a load reading and an audio report (`dnfw wav report`).

## 6. Writing

These rules apply to docs, the site, the manuals, help text and PR text.

- Write what the user sees and does. Leave out how the code is built.
- Use short sentences, with one idea each. Use the active voice.
- Use one word for one meaning, and keep it.
- Do not use semicolons or em dashes.
<!-- ste-lint off -->
- Do not use filler or marketing words: delve, leverage, seamless, robust, powerful, pivotal, vital,
  meticulous, holistic, "In conclusion", "Not only X but also Y".
<!-- ste-lint on -->
- End on the last fact or action. Do not add a summary.

The rules follow ASD-STE100 (Simplified Technical English) for structure. Check a file with
`python scripts/ste_lint.py --mode descriptive FILE.md`. Use `--mode procedural` for steps that the
reader follows while reading. Errors are rules. Warnings are advice.

## 7. Review

- The maintainers fix style and house-rule nits on your branch themselves, in a follow-up commit. These
  nits do not block the merge, and you do not have to answer them.
- Review comments are for what the change does: behaviour, risk and tests.
- The maintainers and the contributors can be 10 hours apart. Each review says what is left to do
  before the merge.

## 8. Licence and other people's work

- This repository is under the [GNU AGPL-3.0-or-later](LICENSE). A contribution is under the same
  licence.
- Do not add Elektron material: firmware bytes, logos, artwork or manual text. A mod changes the
  firmware at apply time, on the user's own copy.
- Code from an MIT project keeps its notice in [THIRD-PARTY.md](THIRD-PARTY.md).
- Before you copy code from another project, run `python tools/licence_check.py <checkout>`. It reads the
  project's licence and statements, and it gives a verdict from one fixed table, with its evidence.
- `docs/references.md` gives the licence of each reference project, as checked on its date. Do not copy
  code under GPL-2.0-only into this repository.
