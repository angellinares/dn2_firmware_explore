# dn_firmware

Tools to inspect, modify and rebuild **Elektron Digitone** firmware, and a set of
mods for the Digitone II that we built with them. The tools cover the Digitone II
(DN2) and the original Digitone and Digitone Keys (DN1).

**This repository holds code and documentation only.** It contains no Elektron
firmware, original or modified, and it never will. Bring your own OS file: the one
that Elektron publish for your instrument. Each mod applies to *your* copy of that
file. Before a mod writes, it checks that your copy is the one we measured it against.

## Mods for the Digitone II 1.11

Apply them with `dnfw mods apply`, or in the browser on the project site,
**<https://angellinares.github.io/dn2_firmware_explore/>**. The site runs entirely
in your browser and uploads nothing. The browser and the command line make the same
file, byte for byte. A test checks this.

| Mod | What it does | Status | In the browser |
|---|---|---|---|
| `lfo4` | A fourth LFO under `[MOD]`, like LFO1–3. Modulates on every voice; kept by SAVE PROJECT and across a power-cycle | confirmed on hardware | yes |
| `arpmodes` | SHUF and RAND as real arpeggiator modes | confirmed on hardware | yes (#131) |
| `fxmod` | An LFO can be aimed at 24 Chorus, Delay and Reverb parameters | confirmed on hardware | yes |
| `moddest` | 13 more per-voice parameters open as LFO destinations | confirmed on hardware | yes |
| `lfowaves` | Seven new LFO waveforms, three of them your own wavetables | confirmed on hardware | yes |
| `midiarp` | The arpeggiator on MIDI tracks | confirmed on hardware | yes |
| `layermidi` | TRACK WILL TRIGGER onto a MIDI track plays it over MIDI: notes, chords, releases | confirmed on hardware | yes |
| `arpplocks` | MODE, SPEED, RANGE and N.LEN lockable per trig | confirmed on hardware; changed since, emulator-checked | no |
| `bootscreen` | Your own mark in the start-up animation | confirmed on hardware | yes |
| `reloadconfirm` | FUNC + NO can ask before it reloads the pattern (a switch in SETTINGS > PERSONALIZE) | confirmed on hardware | yes |
| `arpscale` | The arp's step offsets move by degrees of the track's scale and root, not semitones (a switch in SETTINGS > PERSONALIZE) | confirmed on hardware (2026-10-14) | no |
| `degreetranspose` | [KEYBOARD] + [FUNC] or [TRK] + [+]/[−] (stock's track transpose keys, with [KEYBOARD] added) transposes the active track by degrees of its scale, not semitones, kept in each pattern, MIDI tracks included | not yet tested by the repository owner; external reports in `docs/flashing.md` | no |
| `transients` | Replace the FM drum transient bank with your own samples | confirmed on hardware | yes |
| `songguard` | A song with a damaged row count loads as empty instead of halting the instrument (a stock bug) | confirmed on hardware | no |
| `lfolength` | The LFO ONE/HALF fix: TRIG MODE ONE and HALF run one cycle / half a cycle from the start phase and hold the value they reached, on audio and MIDI tracks (two stock bugs; supersedes `lfohold`) | confirmed on hardware (2026-10-09, audio track); MIDI tracks in the emulator | yes |
| `waverider` | A sixth synth machine: two wavetable oscillators with MOVE, a sub-oscillator and noise, with tables from the +Drive (alpha) | alpha, confirmed on hardware (2026-10-14) | yes |
| ~~`lfohold`~~ | Superseded by `lfolength` (2026-10-09): the hold, audio tracks only. Kept in the tree for the record, not offered | confirmed on hardware (2026-10-08) | no |

**Combining them.** `dnfw mods matrix` tries each pair in both orders. The command
writes the result into `docs/mods-compatibility.md` and the site. Most pairs combine
freely. A few pairs need an order, and `dnfw mods apply` applies them in that order.

Some pairs cannot combine, and the table gives the reason for each. Three combinations
passed on the instrument:

- `lfowaves`, `bootscreen` and `lfo4` (2026-09-30)
- `bootscreen` and `layermidi` (2026-10-02)
- `bootscreen`, `layermidi` and `usbprobe` (2026-10-03)

`docs/flashing.md` has the details.

**Old projects that halt on load:** a project with a damaged song row count halts
even stock 1.11 on load (`EXCEPTION DS0059`). The `songguard` mod limits the count.
It passed on the instrument (`docs/old-project-load.md`).

**Waverider is an alpha.** It is a wavetable machine for the Digitone II, after the
Wavefinder of Tonverk (`docs/waverider-feasibility.md`). It is a sixth machine in MACHINE
SEL. It has two wavetable oscillators, a sub-oscillator, noise and its own modulator. Page 5
(Shape) does not change the sound yet. Our own SHARC reader runs inside a real DN2 voice.

Its tables are in the wavetable pool of the project, on the +Drive. You put them there with
DNX. The manual is `docs/waverider-manual.md`, and the measurements are in
`docs/waverider-performance.md`. Sounds that you save may not load the same way in a later
version. On the command line, use `dnfw mods apply ... --mod waverider`.

## Installation

You need Python 3.11 or later. There are no dependencies.

```
pip install -e .
dnfw inspect 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip
dnfw mods apply Digitone_II_OS1.11.syx --mod lfo4 -o modded.syx
```

To run without an install, use `PYTHONPATH=src python -m dnfw.cli.main ...`.

Each command that takes a `.syx` file also takes the `.zip` that Elektron ship.

### Commands

| Command | Does |
|---|---|
| `dnfw inspect <image>` | report transport, container, sections and every integrity field |
| `dnfw extract <image> -o DIR` | write each section out, depacked where it is compressed |
| `dnfw build <image> -s 3=FILE -o OUT` | rebuild with a replaced section, recomputing every checksum |
| `dnfw diff <a> <b>` | compare two images section by section |
| `dnfw mods list` / `apply` / `extract` | the mods above: list them, apply them, extract their factory content |
| `dnfw mods matrix <image>` | try every pair of mods and report which combine |
| `dnfw patch list` / `apply` | declarative single patches with stock-byte guards |
| `dnfw params <image>` | find and dump the instrument's parameter table |
| `dnfw symbols` / `symbolmap <image>` | the C++ names GCC left in the image; a Ghidra seeding script |
| `dnfw disasm <image> ADDR [N]` | disassemble a span (ColdFire V4e, via objdump) |
| `dnfw validate-disasm <image> ADDR [N]` | check another disassembler against objdump |
| `dnfw cave <image>` | find free space and size a hook for a code-cave detour |
| `dnfw fn <image> ADDR` | count direct callers of an address, or find the function containing it |
| `dnfw ldr <image>` | walk the SHARC program (section 7) as an ADI boot stream |
| `dnfw waverider ...` | Waverider's tables: scan and reduce WAVs, bake, render a reference, build a frame |

Before they write a file, `build`, `patch apply` and `mods apply` load it again for a
check. This tool writes no file that it cannot check.

## How we check a change before it reaches an instrument

- **Integrity:** the tool calculates every checksum and the HMAC-SHA256 signature
  again, and checks them on the rebuilt file.
- **Boot from reset in an emulator:** the `boot_gate` of digikit boots the image from reset
  (about 11 s on our computer). It watches the fault reporter of the firmware and the refusal
  of the uploader, and both must see zero hits. `scripts/emu_boot_check.py` is the older route,
  against a stock control. A snapshot of a machine that has already booted does not count
  (`docs/emulator.md`).
- **The engine and save/load:** `scripts/emu_boot_engine.py` runs the evaluator of
  the audio engine. It also takes a stored sound through LOAD and SAVE.
- **ColdFire encodings:** `scripts/check_coldfire.py` rejects an addressing mode that
  the chip refuses and generic emulators run.
- **Per-mod harnesses** under `scripts/emu_*.py`, each with a stock control.
- **DSP code** runs offline in the SHARC runner of digikit. A script compares it with
  a Python reference (`scripts/sharc_waverider_*.py`).
- **Frame words:** a mod can put data in a word of the ColdFire-to-DSP frame. Before it
  does, two scripts run the stock DSP over recorded and random frames:
  `scripts/sharc_frame_census.py` and `sharc_frame_word_check.py`. They name every instruction that reads that word
  (`docs/waverider-frame-words.md`).
- **On the instrument:** before we flash anything, the project's test plan gives a
  written pass and fail for each hardware test. The recovery route (stock through the
  Early Start-up Menu) works on the instrument. Send it over a clean MIDI link
  (`docs/flashing.md`).

## What the firmware is

We measured this from the images. The evidence is in `docs/ele3-format.md` and
`docs/mainos-image.md`.

- An `ELE3` container inside a block-streaming SysEx transport.
- The sections use an aPLib variant for compression. `MAIN OS` loads at `0x40000400`.
  `MAIN OS` is big-endian **ColdFire V4e** code, built with GCC, and it still carries its
  **C++ RTTI names**. Section 7 is the **SHARC+ DSP** program, as an ADI boot stream.
- An **HMAC-SHA256** signature seals the DN2 container. The key comes from material in
  the image itself, so a tool can sign a modified image correctly. The DN1 container
  has **no signature**: its trailer is 32 zero bytes.
- The +Drive is a 32 GB eMMC with no filesystem. The +Drive has fixed slots for projects,
  presets and kits, and about 21 GiB that the stock firmware never touches
  (`docs/drive-storage-research.md`).

## Testing

```
pytest -m "not slow"     # the fast set
pytest                   # everything, a few minutes
```

Gate F needs an m68k objdump. On Windows, install it with
`wsl -u root apt-get install -y binutils-m68k-linux-gnu`. The browser parity tests
need Node. The emulator gates need digikit (`docs/emulator.md`). A test that needs
something absent (the OS images in `00_Resources/`, objdump or Node) skips, and says so.

## Documentation

| File | Subject |
|---|---|
| `docs/PRINCIPLES.md` | how code here is built, and why |
| `docs/mods.md` | every mod: what it changes, how it was verified |
| `docs/mods-compatibility.md` | which mods combine, generated by `dnfw mods matrix` |
| `docs/flashing.md` | the recovery path, and the order hardware steps happen in |
| `docs/emulator.md` | running builds in digikit's ColdFire emulator |
| `docs/instruments.md` | which tool answers which question |
| `docs/lfo4-build-plan.md` | the whole LFO4 story, including the dead ends |
| `docs/waverider-feasibility.md` | Waverider, milestone by milestone |
| `docs/waverider-manual.md` | Waverider as the alpha behaves: pages, controls, wavetable pool |
| `docs/waverider-frame-words.md` | which frame words stock writes and the DSP reads, and where Waverider's position moved |
| `docs/drive-storage-research.md` | the +Drive, and where a sample library could live |
| `docs/ideas-backlog.md` | ideas, costed, with their state |
| `docs/ele3-format.md` | the transport, container, codec and integrity layers |
| `docs/mainos-image.md` | the CPU, the load address, and which disassembler to trust |
| `docs/sharc-voice-path.md` | the DSP voice path, as measured in the runner |
| `docs/references.md` | prior art, what each is good for, and its licence |

## Licence

**[GNU AGPL-3.0-or-later](LICENSE).** Use it, fork it and change it. Keep the notices,
and pass on the same freedoms. If you distribute a modified version, or run it as a
service, it stays open. DNX has the same licence, for the same reasons.

Some parts come from MIT projects. [THIRD-PARTY.md](THIRD-PARTY.md) carries their
notices.

## Credit

The container, transport, codec and integrity work stands on
[mischa85/elektron-firmware-tool](https://github.com/mischa85/elektron-firmware-tool)
(MIT). The patch model comes from
[bryantysinger/octa-bt-pt](https://github.com/bryantysinger/octa-bt-pt) (MIT), and the
ColdFire disassembly findings come from [sambanks/octabam](https://github.com/sambanks/octabam)
(MIT).

The ColdFire and SHARC emulators are from
[m-dwyer/digikit](https://github.com/m-dwyer/digikit) (GPL-2.0-or-later). We use them as
external tools. We assemble our own SHARC code with
[js216/selache](https://github.com/js216/selache) (GPL-3.0). The Digitone data formats
come from the sibling project DNX.

The USB SysEx probe adapts the design of
[irpina/digihealth](https://github.com/irpina/digihealth) (GPL-2.0-or-later). The
frame-word census follows the method of the OS 1.12 notes of
[naturarum/dn2-cfw](https://github.com/naturarum/dn2-cfw) (GPL-2.0, method only, no code
taken). Its report on words 0xa54 and 0xa56 (issue #49) moved the song position of
Waverider. The `arpscale` mod is the work of
[w-winter](https://github.com/w-winter) (pull request #212). `docs/references.md` says
what we took from each, and where this project does it differently on purpose.

None of them is affiliated with Elektron, and neither is this project. We measured
everything in `docs/` from OS files that Elektron publish. This repository contains no
copied Elektron code, and it redistributes no firmware.
