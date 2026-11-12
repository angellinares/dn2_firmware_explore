# What changed between Digitone II OS releases

Measured 2026-09-11 with `dnfw diff`, from the images Elektron publish. Every
comparison is on **decoded** content: two compressions of the same code differ
everywhere, and that is not a change.

```
dnfw diff Digitone_II_OS1.10D_dist.zip Digitone_II_OS1.10E_dist.zip --strings
dnfw diff Digitone_II_OS1.10E_dist.zip Digitone_II_OS1.11_dist.zip  --strings
```

| | 1.10D | 1.10E | 1.11 |
|---|---|---|---|
| build | 40049 | **40050** — every patch here targets this | 40059 |
| built (meta section) | 2025-07-27 23:51 | 2025-09-10 15:18 | 2026-09-08 14:25 |
| published at | `…/uploads/2025/10/` | `…/uploads/2026/06/` | `…/uploads/2026/09/` |
| signing key | `"Multiplier"` | same | same |

## 1.10D → 1.10E: "support for updated production processes"

Elektron's release note is one line. What the images show:

| Section | Change |
|---|---|
| meta | the build timestamp, nothing else |
| **bootstrap** (id 2) | **28,254 → 30,302 bytes, and its load address moved `0x01080000` → `0x02000000`.** Rebuilt almost entirely: 24,934 of the first 28,254 bytes differ |
| MAIN OS | +4,096 bytes, and all of it is a zeroed region at the end. The rest is 70 blocks of change, mostly the scattered one-byte pointer updates of a relink, with two dense ones (below) |
| updater | **byte-identical** |
| blob | **byte-identical** |

**No text changed.** Not one human-readable string was added or removed in MAIN
OS. The service-command strings (`#WRITE_SERIAL`, `#READ_SERIAL`, `#WRITE`,
`#MMC_RECONFIGURE`) are at identical addresses in both. So this is not a
feature and not a change to the factory command set.

The two dense MAIN OS blocks:

| Where (1.10E) | Bytes | What it looks like |
|---|---|---|
| `0x402dcb12 .. 0x402e1bf3` | 15,265 | ColdFire code addressing on-chip peripheral registers (`lea 0xffff8006`), with exception returns — driver or start-up code |
| `0x400c2bc6 .. 0x400d8af7` | 4,788 | code just below the service dispatcher at `0x400cf906`; the dispatcher itself barely changed |

**Reading it — INFERRED, not confirmed:** a hardware revision. The bootstrap
runs from RAM and moved to a different RAM address, and the densest MAIN OS
change is low-level peripheral code. "Production processes" would then mean a
new build of the board, and 1.10E is the release that runs on it. Nothing here
was disassembled; the reading rests on where the changes are and what kind of
bytes they are.

**What it means for this project:** little, and usefully so. The only
recovery-related code that moved is the bootstrap, and our images carry stock
1.10E's bootstrap byte for byte. The updater did not change. So 1.10E did not
introduce the recovery stall — that is our images' shape, see
`docs/flashing.md`.

## 1.10E → 1.11: Outbox 8

A different kind of release entirely.

| Section | Change |
|---|---|
| bootstrap | same size, **moved again** to `0x02010000`; 5,666 bytes differ |
| MAIN OS | **+106,496 bytes**, and everything after the first few bytes has shifted — real feature work, not a relink |
| **updater** | **changed for the first time** in these three releases: 14,231 bytes differ |
| blob | +3,896 bytes |
| **id 8** | **new**, 159,948 bytes decoded, not yet looked at |

The text that appeared is all Outbox 8 and CV configuration — `OUTBOX 8
CONNECTED`, `CV OUT %d`, `PITCH V/oct`, `S-TRIG`, `BreakOutBoxRoutingMenuView` —
plus new storage versions (`projectStorage_v14_t`, `soundStorage_v3_t`, …).

**What it means for this project:** a patch written against 1.10E cannot be
reapplied to 1.11 by offset. MAIN OS moved throughout, so every patch has to be
found again — which is what the `find`/`expect` fields in `patches/` are for,
and why a patch names the build it targets. The compression and signing are
unchanged, and the limits in `src/dnfw/codec/limits.py` were measured on 1.11,
so the pipeline itself carries over.

## Reading `dnfw diff`

- **Blocks are densest first.** A relink produces many small blocks; a rewrite
  produces one large one. Read the top of the list.
- **When lengths differ, the shared prefix is compared unshifted.** Growth at
  the end — 1.10D to 1.10E — then shows only the real changes. An insertion
  part-way through shows as one block from the insertion to the end, as in
  1.10E to 1.11. That is correct, not a failure to align.
- **`--strings` is a filter, not a parser.** It keeps strings that contain a
  word and drops most code, but the odd code fragment (`DHKU *`) gets through
  and reads as one.

---

## What 1.11 added, from the storage type names (2026-09-14)

MAIN OS carries its storage struct names in mangled symbols, so diffing them
between images says what the release changed to *persisted* state. 1.10E has 63
such names, 1.11 has 67.

| | |
|---|---|
| **new** | `bobConfigStorage_v0_t`, `midiSetupStorage_v3_t`, `projectSettingsStorage_v8_t`, `projectStorage_v14_t`, `soundPoolStorage_v3_t` |
| **gone** | `soundPoolStorage_v2_t` — so that one is a version bump, not an addition |

`projectStorage_v14_t` is confirmed on the instrument from the other direction:
the DNX session reports every occupied project slot re-written by 1.11 to
container format `0059` (build 40059), decoding to 12,890,116 bytes against
1.10E's `0050` and 12,889,604. Two tools, two methods, one answer.

### The new one is the breakout box, and it is not audio content

`bobConfigStorage_v0_t` is `v0` — genuinely new rather than a bump — in
namespace **`BOB`**:

```
0x401ff7f5  ZN19BreakOutBoxSettings12updateMirrorEPN3BOB21bobConfigStorage_v0_tE
0x4021e736  Value<BOB::bobConfigStorage_v0_t>
0x4021e75d  ValueWithMirror<BOB::bobConfigStorage_v0_t>
```

The same `ValueWithMirror<live, storage>` shape as `Sound` /
`soundStorage_v3_t`. Its cluster: `BreakOutBoxSettings` (`0x4021e78f`),
`BreakOutBoxSettingsCvConfigCopy` (`0x4021e713`), `BreakOutBoxEditMenuView`
(`0x4021ed2c`), `BreakOutBoxRoutingMenuView` (`0x4021ef1a`),
`BreakOutBoxCVOutputConfigMenuView` (`0x4021f068`). Beside them at `0x4021e857`
sits `ValueWithMirror<modTarget_t[4], modTargetStorage_v0_t[4]>` — four
modulation targets, which reads as one assignable target per CV output, though
that is positional evidence. It is **not** new in 1.11.

**The owner confirms: 1.11's "Outbox" is the breakout box, and has nothing to do
with the FM drum transients.** Recorded so the next person who greps `Outbox`
while hunting audio content stops here rather than following it.

## Before the 1.12 port: mod RAM that 1.12's DMA buffers take (2026-11-04)

On 1.11, stock's DMA section runs `0x466b8000..0x46701340`. In 1.12 it moved
+0x8000. Our static read of 1.12 (2026-10-18) puts the eMMC bounce buffer at
`0x4e6f9300`, which is RAM `0x466f9300..0x46709300`, from the same six sites at
code +0x2e0. Digiwerk and elekloader's DN2 1.12 profile give `0x46709340` as the
end (static, as collected in Aggregat's `hardware/common/memory-maps.md`). Nobody
has measured it on a 1.12 unit or in a 1.12 emulator run.

Two of our chunks are free on 1.11 and inside or beside that range on 1.12:

| mod | chunk | on 1.12 |
|---|---|---|
| bootscreen | `0x46708000` | inside the DMA buffers |
| waverider | `0x4670a000` (the SYN pages) | 3,264 bytes above their end (3,328 by our read) |

The RAM check (`dnfw.mods.ramcheck.STOCK_DMA`) holds the 1.11 range only.
Before any mod builds for 1.12:

1. Measure 1.12's DMA range in both windows, as `docs/lfo4-state-memory.md` did for 1.11.
2. Make `STOCK_DMA` per OS version.
3. Move each chunk that the 1.12 range covers, and give the mod a new version.
4. Measure the OS update buffer again (`docs/version-gate.md` section 5b).

## The 1.12 port: tools (issue #382, 2026-11-12)

Every mod gets a 1.12 build beside its 1.11 build, in the same repository. 1.11 stays the build users get until all mods are on 1.12. Then 1.12 becomes the default, and the 1.11 builds move to an archive.

**Which OS an image is.** `dnfw.osport.versions.identify(main_os)` names the version of a stock MAIN OS from its sha256. `by_length` does the same when the platform's area is appended. The table there also holds what differs between the versions:

| | 1.11 | 1.12 |
|---|---|---|
| MAIN OS length | 3,192,192 B | 3,196,288 B |
| the reset clears stock's data up to | `0x466b74d0` | `0x466b84d0` |
| stock's DMA section | `0x466b8000..0x46701340` | `0x466c0000..0x46709340` |
| the loader's 138-byte cave | `0x4028da6e` | `0x4028dfae` |

**Where an address went.** `src/dnfw/osport/codemap.py` decodes both images and anchors runs of 10 instructions with their address operands masked. Each matched instruction's old and new operands give a vote for the data map. A second map anchors the image's data part on byte windows. `scripts/osport_check.py` checks the maps against addresses read by hand.

**Every mod site, checked.** `scripts/osport_survey.py` runs every address the mods, their generators and `dn2_111.h` name through the maps. For each edit and guard site it reads the 1.12 image at the new address. The site passes when its stock bytes are there, or when each differing word is an address that maps to its new value. On 2026-11-12: 778 sites decided, 594 with the same bytes, 184 relocated, none unexplained. `--write` saves the decisions to `src/dnfw/osport/map_1.12.json`.

**How a generator uses it.** `dnfw.osport.addr("1.12", va)` gives the 1.12 address of a 1.11 one. An address the map did not decide raises `NotPorted`. Mod RAM above 1.12's DMA section keeps its address. Mod RAM that 1.12's DMA section now covers raises `NotPorted`, so that mod moves (bootscreen's `0x46708000`). `scripts/gen_dn2_header.py --os 1.12` writes `csrc/include/dn2_112.h` from `dn2_111.h`, so the C code builds for either OS from one source.

**The RAM and frame checks on 1.12.** The RAM `0x46709340..0x48000000` passed the three checks of `docs/mod-memory-regions.md`: a refscan in nine windows, the data pointer scan and the touch run with a project upload. Stock 1.12 writes the same 902 frame words as 1.11, and the 301 distinct frames of the corpus are the same byte for byte (`scripts/frame_word_diff.py`). The corpus script also selected the wrong machines until this change. Its earlier corpora held FM TONE, FM DRUM and WAVETONE only, so results drawn from them cover those three.

## The platform on 1.12 (issue #382)

The platform has one spec per OS version: `platform_code.json` for 1.11 and `platform_code_1.12.json` for 1.12. `scripts/gen_platform_code.py --os 1.12` writes the 1.12 spec. `platform.spec_for(content)` takes the spec of the MAIN OS it gets. A modded MAIN OS no longer hashes as stock. So the version comes from where the DNFW area starts, or from the stock length when there is no area. A whole firmware file gets its version from its build stamp in section 5 (`versions.of_firmware`).

| | 1.11 | 1.12 | how 1.12's was found |
|---|---|---|---|
| start-up calls | `0x4000053e` | the same, same bytes | read in the image |
| loader cave, link | `0x4028da6e`, `0x4028da70` | `0x4028dfae`, `0x4028dfb0` | 138 zero bytes, +0x540 |
| area | `0x4030b980` | `0x4030c980` | the stock end |
| bus sites | `0x400dc02a`, `0x400dc814`, `0x400dc8f6` | +0x164 each | `osport.addr`, stock bytes equal |
| machine-count bounds | 6 sites | +0x164 each | `osport.addr`, the stock value read there |
| parameter bounds | 55 | 55 | found in the image; each 1.11 bound maps onto one |

The loader is one source for both. `csrc/include/dn2.h` includes `dn2_112.h` when the build defines `DN2_OS_112`, and `dn2_111.h` otherwise. The 1.12 loader differs from 1.11's only in the area's address.

`dnfw check` knows stock 1.12. Sections 2, 4, 7 and 8 of 1.12 hash the same as 1.11's. The check takes stock's DMA end from the image's version.

**Checked on 2026-11-12.** A 1.12 test image holds the platform and a handler on `ev_param_slot` that answers 0. It passes `dnfw check` against stock 1.12. It boots from reset in digikit main's `boot_gate` to the main UI at the same instruction as stock 1.12, with no hit on the fault reporter (`0x4011ed4a` on 1.12). The handler ran on each parameter lookup. Give `boot_gate` only fault PCs in `--watch`: a watched PC counts as a fault the first time it runs.
