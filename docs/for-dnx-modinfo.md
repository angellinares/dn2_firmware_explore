# `/modinfo`: what an image is modded with, for DNX

**Rev 2, 2026-10-07 (DNX's review of rev 1: the hash at `bytes - 4`, the name lengths, `delete` dropped, the root listing as the primary signal). Built and checked in the emulator only, not on the instrument yet.**

**Why it exists.** DNX's wavetable view must appear only on firmware that supports it (owner, 2026-10-07). It must decide from the device's own answer, never from an OS version or a route that fails.

## The gate, in three states

DNX's rule, adopted here. **The root listing is the primary signal; the error string only corroborates it,** since it's stock firmware's English text and may change.
- **Supported:** `/` lists `waverider`, and `/modinfo/0` reads a valid record whose capabilities DNX needs.
- **Not supported:** `/` answers and doesn't list `waverider`. The open of `/modinfo/0` then corroborates it with the session's own **`Error: Could not resolve path`**, stock 1.11's exact answer (measured in the emulator, `scripts/emu_modinfo.py`).
- **Could not ask:**
  - a timeout, a busy port or any other answer;
  - **a contradiction:** `/` lists `waverider` while `/modinfo/0` is refused, which a Waverider build from before rev 1 would also give.
  DNX says so; it never resolves a contradiction or silence into "stock".

**The coarse gate needs no new firmware.** Every Waverider build since the store landed lists `waverider` among the roots, and stock doesn't. Use `/modinfo` for everything the listing can't say: which capabilities, which image.

**Never gate on the OS version.** The OS string is information only: a mod on 1.12 would still carry these routes.

## The routes

| path | answers |
|---|---|
| `/` | `modinfo` listed after `wavepool`, with one child |
| `/modinfo` | one entry: index 0, `info`, used, 256 bytes, write-protected (permissions 0x12) |
| `/modinfo/0` | the record, in the transfer container: content kind **0x4D**, object version **1**, raw, 256 bytes |
| a write to `/modinfo/0` | refused by the session itself: `Write: Permission denied` |
| `/modinfo/1` and up | refused: `modinfo: the only file is 0` |

## The record (256 bytes, big-endian)

| at | bytes | field |
|---|---|---|
| 0 | 4 | magic `DNMI` |
| 4 | 2 | record version, 1 |
| 6 | 2 | record bytes, 256 |
| 8 | 4 | capabilities (below) |
| 12 | 2 | pool slots: **128**. Draw the grid from this before any pool record is read |
| 14 | 2 | pool record version written: 2. Versions 1 and 2 are both read |
| 16 | 2 | store slots: 256 |
| 18 | 1 | a table name's characters the pool keeps: 15 (the store holds 64) |
| 19 | 1 | the characters TBL's header shows after `T:126 `: 14. A longer name shows its first 12, then `..`, trailing spaces trimmed |
| 20 | 4 | **image id**: xxHash32 of the whole MAIN OS payload, computed with this field and the hash zeroed |
| 24 | 8 | OS the image was built from, e.g. `1.11` (information only) |
| 32 | 24 | build tag, e.g. `wr-modinfo` |
| 56 | 12 | commit, e.g. `a97b3ca08f`; a trailing `+` means it was built with uncommitted changes |
| 68 | 1 | mod count, then 3 zero bytes |
| 72 | 16 each | a mod: its id (12 bytes, NUL-padded), then the xxHash32 of its code (4 bytes; 0 when it has none). Up to 11 |
| 248 | 4 | reserved, zero |
| `bytes - 4` | 4 | xxHash32 of everything before it, seed 0 (the hash the store and the pool records use): 252 in version 1 |

**The record grows by appending.** A reader:
- takes the hash from `bytes - 4`;
- accepts a `bytes` larger than it knows;
- reads only the fields it knows.

This is unlike the pool record, whose size is fixed and whose hash sits at a constant.

**The image id answers "which image is this".** Two builds of the same mods and tag differ in it. On 2026-10-06, `tbl128` and `tbl128b` had the same tag and differed only in a loader constant, which a full pool alone would have shown.

## The capabilities

One bit per thing DNX does differently.

| bit | name | DNX |
|---|---|---|
| 0x01 | store | shows the Wavetables tab at all (`/waverider`: list, read, write a table) |
| 0x02 | pool | shows the pool pane, not the store list alone (`/wavepool`) |
| 0x04 | rename | enables Rename (a 128-byte body to `/waverider/<n>` renames in place) |
| 0x08 | (unused) | was `delete` in rev 1: every build with the store has delete, so the flag said nothing. Not to be reused |
| 0x10 | pool_cas | a refused write that sent a generation means "the instrument changed this pool"; without the bit DNX can't say that |
| 0x20 | page | the instrument has its own wavetable page (PRESET/KIT, page 2): DNX's only way to know there is a second writer of the working project's pool, so a refused write can say "the instrument changed this pool" |

**Unknown bits must be ignored.** That's the opposite of the pool record's rule, where an undefined flag is refused, and the difference is deliberate:
- a data record must not be half-understood;
- a capability set grows by design, and an older DNX meeting newer firmware should lose features, not refuse the device.

## Where it comes from

- **The firmware's part:** `csrc/wrstore/modinfo.c` fills the capabilities, the pool and the store from the same defines the routes use, so they can't drift from the code.
- **The build's part:** `dnfw mods apply` writes the mods, the tag, the commit, the image id and the hash, after every mod is applied (`dnfw.mods.modinfo`).
- **An image without Waverider** has neither the record nor the route. For DNX that's "not supported", correctly: there's nothing to manage.

## Checked

| check | result |
|---|---|
| `scripts/emu_modinfo.py` | 15/15 checks, beside stock 1.11 as the control: root listing, the listing, the read byte for byte against the image, container, hash, capabilities, sizes, mods, write refused and the record unchanged, `/modinfo/1` refused, stock lists no `modinfo` and answers `Error: Could not resolve path` |
| `test/test_mods_modinfo.py` | 9/9: fill, image id, two builds differ, unknown bits kept and ignored, a second marker or too many mods refused, a bad hash reads not ok, a 512-byte record reads with its hash at 508 |
