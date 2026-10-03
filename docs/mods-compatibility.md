# Which mods combine

**Generated, not kept.** The table below is rewritten by

    dnfw mods matrix 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \
        --page docs/mods-compatibility.md --page site/index.html \
        --page site/arp-modes.html --page site/arp.html --page site/boot.html \
        --page site/destinations.html --page site/fx.html --page site/lfo.html \
        --page site/lfo4.html --page site/transients.html \
        --boots out/mod-pairs

(the tool pages each carry their own mod's row, `<!-- dnfw:matrix-row ID -->`,
and the index carries the whole table at the top), which tries **every pair of mods, in both orders**, on stock 1.11 (`src/dnfw/mods/matrix.py`).
A table kept by hand is a copy, and it goes stale the first time a mod changes.
octabam's remixer makes the same choice: its `matrix()` prints from the conflict
check rather than from a README (`docs/references.md`).

## What each mark means

- **yes**: the two mods write disjoint bytes and each accepts the image the other
  produced, in either order.
- **order**: they combine in one order only:
  - **The wrong order is refused.** Every mod checks the stock bytes it replaces, so
    that order fails with an error rather than a broken image. Example: bootscreen
    after arpplocks.
  - **Or the wrong order would silently lose an edit.** A mod that *copies* part of
    the image declares it (`COPIES`). lfo4 copies the stock parameter table into its
    appended area. Applied after lfo4, a table edit such as moddest's thirteen masks
    or fxmod's Chorus records still finds its stock bytes and applies cleanly, but it
    lands on a table the firmware no longer reads. `dnfw mods apply` therefore
    applies lfo4 last, whatever order it is given.

    Neither edit is left to order alone any more. moddest refuses an lfo4 image
    (it finds two candidate tables), and since 2026-09-26 fxmod does too: it checks
    that all 56 of the table's accessor bases still reach the stock table
    (`paramtable.base_sites`) and otherwise says to apply fxmod first. The browser
    pages carry the same checks, which matters there: each page applies one mod
    and the user chains them by loading one page's download into the next, so the
    page, not the CLI, has to enforce the order. `site/lfo4.html` accepts an image
    fxmod, moddest or midiarp already built (arpplocks too, from the CLI), and
    refuses lfowaves and bootscreen images on their length.
- **NO**: refused. Either the bytes overlap, or neither order applies.

## What it does not promise

- **Not a hardware result**, with one exception: lfowaves, bootscreen and lfo4
  together passed on the instrument on 2026-09-30 (`platform-trio2`). Every
  other pair has only been checked here.
- **Functional clashes are not detected.** Two mods can write disjoint bytes and still
  fight over one feature. What is known about that is in each pair's note. A pair
  with no note has simply not been examined beyond bytes and apply.
- **Boot.** Every combinable pair that includes a loader mod (lfo4, lfowaves or
  bootscreen) was booted from reset in the emulator (`scripts/emu_boot_check.py`),
  2026-09-26: **12 of 12 booted and drew their UI.**
  - The other pairs were not booted: a boot runs a mod's loader and init and
    nothing else, so it would run neither mod's code. Pairs with transients only
    change section 7.
  - The results are recorded below the table.
  - 2026-10-03: midiarp became a platform mod (a `CODE` chunk), so its pairs with
    bootscreen, lfo4 and lfowaves were booted again with the new code, and the new pair
    with usbprobe was booted: **4 of 4 booted and drew their UI**, as did midiarp alone.

## One loader, one appended area (since 2026-09-30)

lfowaves, bootscreen and lfo4 each used to install a start-up loader of their own
at `0x4000053e` and append their own area to MAIN OS, so no two of them combined.
They now share one **platform** (`src/dnfw/mods/platform.py`), the octabam /
elekloader idea reduced to what this firmware needs (`docs/references.md`):

- **One loader** owns the start-up calls: `csrc/runtime/loader.S`, in the cave at
  `0x4028da6e`. It is the loader lfo4 already used on the instrument, byte for byte
  (`scripts/gen_platform_code.py` checks that).
- **One area**, a `DNFW` directory of chunks. A mod *adds* its chunks to whatever
  area the image carries, so chaining pages in the browser works as the CLI does.
  Data chunks run from `0x46710000` plus their offset; a `CODE` chunk runs at its
  own load address.
- **Run-time RAM is checked**: every chunk's range, and the RAM a mod uses without
  a chunk (`ram()`, such as lfowaves' NOIS state), are compared like byte ranges.
- **Displaced instructions**: lfowaves' `getShortName` hook replays the compare
  that holds the parameter table's bound, and lfo4 widens that bound. The hook
  records what it moved (a `DISP` chunk), and lfo4's edit lands on the replayed
  copy. That is why lfo4 must come after lfowaves (the CLI applies lfo4 last).

What moved to get there:
- **lfowaves:** its blob is a `CODE` chunk at `0x46780000`, where it was
  assembled to run. Its 46-byte copy stub at `0x402cf52c` is gone, and that cave
  is free again.
- **arpplocks (2026-10-02):** its code, seven caves until then (two shared with
  usbprobe and fxmod), is a 1,944-byte `CODE` chunk at `0x467c8000`, past its shadow
  sounds. The hooks and patches are the same, pointing at the chunk. It now combines
  with every mod. `scripts/emu_arp_plocks.py` passes 42/42 on the chunk build and on
  the cave build alike.
- **bootscreen:** its stamp is a `CODE` chunk at `0x46708000` (not `0x46700000`, which is lfo4's LFO state: the first flash of the three together raised V04 there). The 896-byte cave
  at `0x402dfa1c`, which lfo4 also uses, is no longer bootscreen's. The stamp's
  bytes are unchanged.
- **layermidi (2026-10-03):** its code, the cave at `0x402d0664` until then (shared
  with midiarp and usbprobe), is a 324-byte `CODE` chunk at `0x467d8000`, above
  midiarp's. The two hooks are the same, pointing at the chunk. It now combines
  with usbprobe; midiarp stays refused by hand (`matrix.REFUSED`).

Checked under the emulator, 2026-09-30, on the three together (lfowaves, then
bootscreen, then lfo4):
- **Boot:** from reset, it booted and drew its UI (`scripts/emu_boot_check.py`).
- **Loader layout:** stopped at the loader's hand-over to the BSS clear, all 7
  run-time ranges matched the platform's model byte for byte
  (`scripts/emu_platform_check.py`).
- **The browser:** the same chains, each page's download loaded into the next,
  gave the Python's bytes (`test/test_js_platform.py`).

**On the instrument, 2026-09-30:**

- **`platform-trio`: FAILED.** It showed the mark, then `V04 M0 P46700000` after
  the intro. The stamp sat at `0x46700000`, which is also lfo4's LFO state
  array (LIVE). lfo4's `ram()` declared only its chunks, so the overlap check
  could not see it, and the evaluator wrote over the stamp. Each check had run
  one of the two; none ran both.
- **`platform-trio2`: PASSED** ("it worked well"). The stamp moved to
  `0x46708000`. It is the first combined image to pass on the instrument, and
  the first hardware pass of lfowaves and bootscreen on the platform loader.

Two checks came out of the failure:

- **`dnfw.mods.ramcheck`** (`test/test_mods_ramcheck.py`) reads every mod's
  bytes and refuses any address above BSS the mod does not declare. It also
  found three more misses, since fixed: lfowaves' glyph tiles, and the RAM of
  arpmodes and arpplocks. None of them collided yet.
- **`scripts/emu_boot_engine.py`** now fails if any `CODE` chunk has changed
  after the engine has run. It fails on `platform-trio` at `0x46700000`, and
  passes on `platform-trio2`.

## The table

<!-- dnfw:matrix -->
| | `arpmodes` | `arpplocks` | `bootscreen` | `fxmod` | `layermidi` | `lfo4` | `lfowaves` | `midiarp` | `moddest` | `songguard` | `transients` | `usbprobe` | `waverider` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `arpmodes` | - | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| `arpplocks` | yes | - | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| `bootscreen` | yes | yes | - | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| `fxmod` | yes | yes | yes | - | yes | order | yes | yes | yes | yes | yes | yes | **NO** |
| `layermidi` | yes | yes | yes | yes | - | yes | yes | **NO** | yes | yes | yes | yes | yes |
| `lfo4` | yes | yes | yes | order | yes | - | order | yes | order | yes | yes | yes | **NO** |
| `lfowaves` | yes | yes | yes | yes | yes | order | - | yes | yes | yes | yes | yes | yes |
| `midiarp` | yes | yes | yes | yes | **NO** | yes | yes | - | yes | yes | yes | yes | yes |
| `moddest` | yes | yes | yes | yes | yes | order | yes | yes | - | yes | yes | yes | yes |
| `songguard` | yes | yes | yes | yes | yes | yes | yes | yes | yes | - | yes | yes | yes |
| `transients` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | - | yes | **NO** |
| `usbprobe` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | - | yes |
| `waverider` | yes | yes | yes | **NO** | yes | **NO** | yes | yes | yes | yes | **NO** | yes | - |

- **arpmodes + arpplocks: yes**: disjoint bytes. *Note:* emulator, 2026-09-26: arpplocks' MODE lock takes its ceiling from setMode's clamp (0x4004bf01), which arpmodes widens to 6. Turning MODE with every step held locks DOWN CYCL SHUF RAND RAND RAND with both, and DOWN CYCL CYCL ... with arpplocks alone (scripts/emu_arp_modes.py). A locked SHUF or RAND playing from a trig was not run.
- **arpmodes + midiarp: yes**: disjoint bytes. *Note:* a MIDI track's arp runs the same step, so SHUF and RAND should reach MIDI tracks; not run.
- **bootscreen + layermidi: yes**: disjoint bytes. *Note:* on the instrument, 2026-10-02, with layermidi's cave build (layer-midi6): flashed together (a static tunnel mark), the intro plays the mark and layering onto a MIDI track plays over MIDI; the boot check from reset passed for the tunnel, ascii and spin animations each combined with it. With layermidi on the platform (2026-10-03): the boot check from reset passes with a static tunnel mark, and the loader puts both chunks where the platform predicts (scripts/emu_platform_check.py), and on the instrument, 2026-10-03, flashed with usbprobe as well: works.
- **fxmod + lfo4: order**: fxmod refuses after lfo4: the parameter table has been moved (expected 53 site(s) holding 0x401f7f94 (table - 60 + 8), found 0); lfo4 does that, and fxmod opens records in the stock table, which nothing reads once it has moved: apply fxmod first, then lfo4. *Note:* emulator, 2026-09-26: the LFO4 slot harness and a turn of all eight LFO4 dials match lfo4 alone; fxmod's DEST checks and names match fxmod alone; every LFO page, LFO4's included, gains the same 24 FX destinations. The hooks are on different paths (fxmod's slot lookup at 0x400dc02a is asked above slot 100 only while the DEST list is built). Not exercised: LFO4 aimed at an FX destination. fxmod's own helper at 0x4028ea02 keeps the stock table bounds, so it would answer LFO4's own entries with -1; it is only ever called with destination entries.
- **fxmod + waverider: NO**: waverider refuses after fxmod: 0x400dc02a (slot_to_id: saves d2, d1 = 100, a0 = slot) is not stock; this mod is for unmodified Digitone II 1.11.
- **layermidi + midiarp: NO**: refused by hand: they fight over one feature (see the note). *Note:* refused by hand, not by bytes (both run from the platform, at 0x467d8000 and 0x467d0000): both turn layered copies on MIDI tracks into MIDI notes. midiarp's hook on the voice trigger (0x400268f8) used to play every layered copy on a MIDI track, from the inline note fields a sequencer trig never fills (random notes and lengths on the bench, 2026-10-01). Since 2026-10-03 (#179) it plays a copy only when its own track's arp is on and playing it. Checked in the emulator with the refusal bypassed (the maintainer, 2026-10-03, on emu_midiarp_layered.py's rig): a layered copy that is an arp step, on a MIDI track with its arp on, is sent twice -- midiarp sends the arp's note and layermidi sends it again; an arp step that is not a copy is sent once; with the arp off, or the arp without layering, the pair behaves. So the one clash is layering onto a MIDI track whose arp is on, and the pair stays refused until layermidi leaves those copies to midiarp.
- **lfo4 + lfowaves: order**: lfowaves refuses after lfo4: 0x400372da is not stock (202f00080c800000014b...); lfo4 widens this bound: apply lfowaves first, then lfo4.
- **lfo4 + moddest: order**: moddest refuses after lfo4: found 2 candidate parameter tables, expected 1; this image's layout is not the one this mod was measured against. *Note:* measured: with moddest applied first, all 13 masks it opens are in lfo4's relocated table (test/test_lfo4_mod.py).
- **lfo4 + waverider: NO**: lfo4 and waverider both write section 3 0x000dce86..0x000dce88 (2 bytes).
- **transients + waverider: NO**: transients and waverider both write section 7 0x000795d4..0x00084f24 (47,440 bytes).
<!-- /dnfw:matrix -->

## Boot from reset, per pair

Written from `out/mod-pairs/*/boot.txt` (`--boots out/mod-pairs`). A boot runs the loader and
the init, so only pairs that include a loader mod are booted; the rest say why they were skipped.

<!-- dnfw:boots -->
- `arpmodes` + `bootscreen`: booted and drew its UI (1 frame(s), control 1).
- `arpmodes` + `lfo4`: booted and drew its UI (1 frame(s), control 1).
- `arpmodes` + `lfowaves`: booted and drew its UI (1 frame(s), control 1).
- `arpplocks` + `bootscreen`: booted and drew its UI (1 frame(s), control 1).
- `arpplocks` + `lfo4`: booted and drew its UI (1 frame(s), control 1).
- `arpplocks` + `lfowaves`: booted and drew its UI (1 frame(s), control 1).
- `bootscreen` + `fxmod`: booted and drew its UI (1 frame(s), control 1).
- `bootscreen` + `lfo4`: booted and drew its UI (1 frame(s), control 1).
- `bootscreen` + `lfowaves`: booted and drew its UI (1 frame(s), control 1).
- `bootscreen` + `midiarp`: booted and drew its UI (1 frame(s), control 1).
- `bootscreen` + `moddest`: booted and drew its UI (1 frame(s), control 1).
- `bootscreen` + `songguard`: booted and drew its UI (1 frame(s), control 1).
- `bootscreen` + `waverider`: booted and drew its UI (1 frame(s), control 1).
- `fxmod` + `lfo4`: booted and drew its UI (1 frame(s), control 1).
- `fxmod` + `lfowaves`: booted and drew its UI (1 frame(s), control 1).
- `lfo4` + `lfowaves`: booted and drew its UI (1 frame(s), control 1).
- `lfo4` + `midiarp`: booted and drew its UI (1 frame(s), control 1).
- `lfo4` + `moddest`: booted and drew its UI (1 frame(s), control 1).
- `lfo4` + `songguard`: booted and drew its UI (1 frame(s), control 1).
- `lfowaves` + `midiarp`: booted and drew its UI (1 frame(s), control 1).
- `lfowaves` + `moddest`: booted and drew its UI (1 frame(s), control 1).
- `lfowaves` + `songguard`: booted and drew its UI (1 frame(s), control 1).
- `lfowaves` + `waverider`: booted and drew its UI (1 frame(s), control 1).
- `midiarp` + `usbprobe`: booted and drew its UI (1 frame(s), control 1).
<!-- /dnfw:boots -->
