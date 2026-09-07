# The MAIN OS image

Section id 3 of the ELE3 container: the code the instrument runs.

| | DN2 1.10E | DN1 1.42A |
|---|---|---|
| depacked size | 3,085,696 | 2,420,912 |
| load address | `0x40000400` | `0x40000400` |
| byte order | big-endian | big-endian |

## It is 68k-family, and almost certainly ColdFire V4e

The image opens `46 FC 27 00` — `MOVE #$2700,SR`, masking interrupts, the
classic first instruction of a 68k-family reset path. Counting opcodes across
the DN2 image: 11,285 `RTS` (`4E75`), 25,503 `JSR.L` (`4EB9`), 2,041 `LINK`
(`4E56`), 2,378 `UNLK` (`4E5E`).

**The variant is inferred, not measured here.** `sambanks/octabam` patches the
Octatrack's main CPU, establishes it as **ColdFire V4e**, and loads its MAIN OS
at **`0x40000400`** — the same address we measure on both Digitones, arrived at
independently. One Elektron platform, one convention. That is strong, and it is
still inference: nothing in this repository has yet disassembled a
ColdFire-only instruction and confirmed it decodes.

Settling it is Gate F, below.

## Do not trust radare2 on this CPU

octabam measured r2's m68k backend against this exact architecture on
**30 August 2026**, and the result is worse than "some instructions fail":

- 6,757 instructions below `0x40098000` cannot be decoded.
- 4,543 of them are longer than two bytes.
- r2 assumes an undecodable opcode was two bytes, so each extension word is
  then decoded as a **separate, ordinary-looking instruction**. The stream
  desynchronises and the disassembly *invents plausible code that is not
  there*.
- The bulk is `mvz` (4,539) and `mvs` (1,834) — ordinary ColdFire ISA_B moves
  used throughout, not exotic audio code. Their example: at `0x40003664`, r2
  reports `invalid / btst.l d4,(a0) / invalid / btst.l d4,(a0)` where the
  actual instructions are `msacl %d0,%a1,%acc2` and `msacl %d0,%a2,%acc3`.

Any tool whose m68k support predates ColdFire has the same failure mode, and it
fails *silently*. **`m68k-elf-objdump -m m68k:cfv4e` is the reference.**
`dnfw disasm` uses it and nothing else, and tells you to install it rather than
falling back to something that would answer wrongly.

### Gate F — validate any other disassembler before using it

Not yet done; `m68k-elf-objdump` is not installed on this machine.

1. Install m68k-elf binutils.
2. `dnfw extract <image> --section 3 -o out/` then import
   `section_3_MAIN_OS.aplib.bin` into Ghidra as raw binary, big-endian, base
   `0x40000400`.
3. Disassemble the same 4 KB span in both and diff.
4. Record here which Ghidra language setting agrees, the span, and the date.
   **No reverse-engineering work starts on a disassembler that has not passed
   this.**

## It was built with GCC, and the C++ names are still in it

This is the single most valuable property of the image. Elektron ship it with
RTTI intact, so a 3 MB anonymous blob carries several hundred class names.

`dnfw symbols <image>` lists them; `--ghidra FILE` writes a script that labels
each address.

454 Itanium-ABI type names are recovered from DN2 1.10E. A sample of what is
there, and why it matters:

| Name | Why it is interesting |
|---|---|
| `11LfoPageView` | the `[MOD]` key's page — the LFO4 work starts here |
| `12ModSetupView`, `15ModDestListView`, `22GroupedModDestListView` | modulation destination UI |
| `9ModConfig`, `12SoundModConf`, `14ModulationCopy` | modulation configuration and copying |
| `17SoundParameterSet`, `12ParameterSet`, `17ParameterPageView` | the parameter model |
| `N9Digisharc17soundStorage_v2_tE` | the persisted sound object |
| `15ValueWithMirrorIA4_N9Digisharc11modTarget_tE…` | a **four**-element array of `modTarget_t` |

**The DN2's internal namespace is `Digisharc`; the DN1's is `Digitone`.**
Useful for telling the two apart in shared code, and a reminder that names do
not always match the product.

That `A4_` — an array of four `modTarget_t` — is noted because four is the
number in question. It has **not** been established that it has anything to do
with the LFO slots. Do not build on it until something confirms it.

### The symbol finder has false positives, by construction

`image/symbols.py` accepts a length-prefixed identifier whose prefix matches
the identifier's length. Real strings sometimes satisfy that by accident —
`3VVE` and `4Hfc7` are both in the DN2 results and neither is a class. There is
no way to separate them without cross-referencing the vtables that point at
them, which is a later job. Treat the list as candidates.

## The string pool

UI strings live around file offset `0x1F7000`–`0x202000`, load address
`0x401F7400`+. The LFO parameter names are there in one run:

```
Speed.LFO1.SPD.Multiplier.MULT.Fade In/Out.FADE.Destination.Start Phase.SPH.Trig Mode.LFO2.
```

and `LFO3` appears separately at `0x40201cb0`. **There are exactly three LFO
page labels in the image** — `LFO1`, `LFO2`, `LFO3` — and no fourth.

The SETTINGS menu block is at `0x40200b09`:

```
MANAGE PROJECTS.ProjectMenuView.MIDI CONFIG.SYSEX DUMP.AUDIO ROUTING.PERSONALIZE.DigisharcSettingsMenu
```

`PERSONALIZE` at `0x40200b2e` is the Gate E patch target — unique in the image,
NUL-terminated, cosmetic, and two button presses from the front panel.
