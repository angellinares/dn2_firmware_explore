# For DNX: renaming tables and the per-project wavetable pool

What the firmware will add to the Waverider store and the Data API, so that DNX's Library tab
(DNX option 1) and the instrument's PRESET/KIT page 2 (option A) can manage wavetables. Decided
by the owner on 2026-10-06:
- the pool is **per project**: up to 127 tables, chosen from the +Drive store, saved and loaded
  with the project;
- a sound remembers a **pool slot**.

The store itself, the index entry and the `/waverider` route are in `docs/waverider-store.md`; this
builds on them and changes none of it. **Status: revision 3, with DNX's answers of 2026-10-06
folded in (listed at the end). Nothing here is built yet.**

## The numbers (read this first)

One table has several numbers. Every field below says which one it carries.

| name | range | what it is |
|---|---|---|
| **store slot** | 0..255 | the index entry and the `/waverider/<n>` path (`docs/waverider-store.md`) |
| **pool index** | 0..126 | an entry in a project's pool list |
| **shown slot** | 1..127 | what both UIs display: pool index + 1 |
| **coarse** | 0..128 | what a sound stores in TBL1 / TBL2 (the parameter word's high byte) |
| **project slot** | 0..128 | which project a pool list belongs to: 1..128 as `/projects` numbers them, and **0 for the working project**. The only number here where 0 is not "the first": the listing names it `working` |

The conversions:
- coarse 0 and 1 are the built-in tables, Prim. and Harm. They're in no pool and have no shown
  slot;
- coarse c >= 2 is pool index c - 2, and shown slot c - 1;
- a pool entry holds a store slot.

So a sound reaches a table in two steps: its coarse gives a pool index, and the project's pool
list gives the store slot at that index.

Usage is DNX's to compute, with no route for it. Read TBL1 (slot 27) and TBL2 (slot 33) of every
sound whose machine is **5**, never 1. The two TBL saves the owner is making will locate those
bytes in a saved project.

## 1. Rename in place

**A write of the index entry alone.** Use the write you already use (`0x57` open, `0x58` chunks,
`0x59` commit) on `/waverider/<store slot>`, in the same container as a slot file, with a body of
exactly **128 bytes**: an entry, and no table after it. The firmware takes that as a rename.
- **Only the name is read: bytes 32..95.** Every other byte of the body is ignored, so the
  geometry, the hashes and the extent can't change, by construction rather than by comparison.
  A client needn't fetch the stored entry first; zeros are fine everywhere but the name.
- The name is checked as a stored name is: Windows-1252, NUL-terminated inside the 64 bytes.
- The slot must be in use. A free slot is refused.
- Only the index is written (the non-current group, then its superblock, generation + 1), never
  the slot's data. So a rename is one index write: no 512 KiB, and no risk to the samples.
- The refusals answer the way a write's do today: the commit returns an error, and
  `wr_write.last` says why.
- **How to prove it:** a read-back of the file can't match what was sent (the stored file is
  128 + N bytes). Re-list `/waverider` and compare the name at that slot, as a commit that can't
  refuse is proven today.

Today a body of 128 bytes or less is refused ("the file must be a 128-byte entry and a table").
This makes exactly 128 the rename and leaves everything else as it is.

## 2. The pool lists

### On the +Drive

The store region has 2,048 unused sectors between group B and slot 0's data: `0x600800..0x601000`.
Each project slot p (0..128) gets **two sectors**, written alternately like the index groups:
- **A at `0x600800 + p`**;
- **B at `0x600900 + p`**.

The two copies of one record are 256 sectors apart, not neighbours, for the same reason the index
groups are apart. 258 sectors in all, ending at `0x600981`.

The current record is the valid one with the higher generation; on a tie A wins. **If neither is
valid, the project follows the automatic pool** (below), exactly as every project does today.

**A pool record**: 512 bytes, every multi-byte field big-endian, as in the store.

| offset | field |
|---|---|
| 0 | magic `"WRPL"` |
| 4 | version u16 = 1 |
| 6 | **project slot** u16: 0..128, and it must equal the record's place |
| 8 | generation u32: 1 or more in a stored record; 0 only in a read with no record behind it |
| 12 | entries in use u16: **the count of entries that are not `0xFFFF`** (not the highest used index + 1) |
| 14 | flags u16: bit 0 = **automatic**; every other bit 0 |
| 16 | 127 × u16: entry j is the **store slot** at **pool index** j, or `0xFFFF` for none |
| 270..507 | zero |
| 508 | xxHash32, seed 0, over bytes 0..507 |

**Automatic** means "this project plays every stored 16 × 512 table, in store-slot order, the
first 127 of them": today's pool. With the flag set, the entries are not used. A stored automatic
record and no record at all play the same; the flag exists so the instrument can make a project
automatic in a single sector write (LOAD below).

An entry may name a store slot that is free, or whose table the DSP can't play (not 16 × 512).
That pool slot then plays the built-in Prim., as an unknown slot does today. The record is valid
anyway: deleting a table must not break every project that uses it. DNX should warn about it,
not repair it on its own.

**What a record can't see.** An entry holds a store slot and nothing else. If a table is deleted
and a different one uploaded into the same store slot, every pool naming that slot plays the new
table, and nothing can tell. Carrying each entry's hash would take 127 × 6 bytes, which doesn't
fit in 512, so this is documented rather than widened.

**What the automatic pool can't hold steady.** Its order is store-slot order, so an upload into a
free store slot below the others shifts every later pool index, and sounds in an automatic
project then play other tables. That is today's behaviour, unchanged; writing an explicit record
pins a project.

### The route

**A new root entry, `wavepool`**, listing 129 entries, **0..128 = project slot**, with the same
long-form layout as `/waverider`'s:
- the name: `working` for 0, and the decimal project slot for 1..128 (`1`..`128`). DNX joins 1..128
  to the `/projects` names itself; the record holds no project name, because the stock project
  operations don't carry pools along (below), so only a join can be truthful;
- occupancy `01 01` when that project slot has a valid stored record (automatic or not, empty or
  not), `00 00` when it has none and follows the automatic pool;
- the size is 512; permissions `0x007e`.

**Occupancy says "a record exists", never "the user chose this pool".** A backup and restore of a
slot that had no record leaves a stored automatic record there: it plays the same, but occupancy
flips from `00 00` to `01 01`. Nothing downstream should read intent into it.

The `/` reply then declares and carries 5 entries.

**The file**, both ways, is the same container as a `/waverider` file (31-byte header, payload,
12-byte trailer) around a 512-byte payload, the record:
- content kind **`0x50`** ('P'), not `0x57`, so a pool file sent to `/waverider` or read as a
  table is refused rather than misread;
- object version 1;
- index (`0x15`) = the project slot, byte `0x18` = p;
- uncompressed length 512;
- **raw** (`0x1D` = 0), as `/waverider`.

- **Read:** `/wavepool/<project slot>`, as `/waverider/<n>` is read. It returns the current
  record. A project slot with no valid record returns what that project plays: the right magic,
  version and project slot, **generation 0**, the automatic flag set, the entries filled with the
  automatic pool as it stands now, the count to match, and a correct hash. So a read always says
  what plays, and generation 0 is how to tell "no record" from a stored automatic one. A stored
  automatic record reads the same way, with its own generation.
  **A record read from an automatic slot describes what plays; it is not a template for a
  write.** Written back unchanged it is refused (below). To edit such a pool, clear the flag,
  keep or change the entries, and write an explicit record.
- **Write:** `/wavepool/<project slot>`, the whole record.
  - **Checked:** the container (kind `0x50`, version 1, raw, length 512), the magic, the
    version, the project slot against the path, the flags (only bit 0), and the hash.
  - **Without the automatic flag, also checked:** every entry `0xFFFF` or 0..255, and the count
    against the entries.
  - **With the automatic flag, also checked:** every entry `0xFFFF` and the count 0. **An
    automatic write that carries entries is refused, not ignored**: otherwise read whole, edit
    entry j, write whole on a project with no record would report success, verify clean and
    discard the edit.
  - **Ignored:** only the generation you send. The firmware writes the non-current sector with
    the current generation + 1.
  - **No partial writes:** the record is small, so it's always whole.
  - **How to prove it, one rule for both kinds:** read before, write, read after. **The
    generation advanced, and the fields the writer set came back.** For an explicit record those
    are the flags and the entries; for an automatic one, only the flag, since it reads back with
    the entries filled, so the generation is the evidence that anything happened.
- **Delete:** not offered. An automatic record (entries cleared) makes a project follow the store again, and an
  empty, non-automatic record (count 0) is a pool with nothing in it.

Every project's list is readable, not only the working project's. That is what lets DNX say
"this table is in three projects' pools" before a delete, with no other verb.

### What the instrument does with them

- **Project slot 0 is the working project's pool**: the one TBL plays and the instrument's pool page
  edits. It is kept with the working project, so it survives a reboot as everything else does
  (the working-project rule).
- **SAVE PROJECT to slot k** writes record k as record 0 reads: a stored record is copied, and
  with no record 0 an automatic record is written. Either way k then has a record of its own.
- **LOAD PROJECT k** writes record 0 as record k reads, then refills the DSP's pool from it: a
  stored record is copied, and with no record at k an automatic record is written. One sector
  write either way, so an interrupted load leaves the old pool or the new one, never a mix.
- **A write to record 0 from DNX** refills the DSP's pool, as a write to the store does today
  (`wr_store.changes`). A write to any other record changes only the +Drive.
- **While record 0 is automatic** (or absent), a store write refills the pool as today.
- **Editing the pool on the instrument** while record 0 is automatic first writes it out as an
  explicit record (what plays now), then applies the edit.

**Not covered yet (it needs the stock project operations hooked):** copying, moving, clearing or
deleting a project from the instrument's own project manager doesn't carry its pool list along. The
pool record stays at the old project slot. Until that is built, DNX should treat a pool record as
belonging to whatever project now sits in that slot, and say so when it can tell.

## 3. What changes for the pool you see today

Nothing, until something writes a record. A project with no record (every project saved so far,
by stock firmware or by DNX) follows the automatic pool, so it plays what it plays today. A
project DNX writes to slot k plays from the moment it loads; the pool write is not a second
step that has to happen with it. There is no first-boot migration: record 0 absent is the
ordinary case.

## Not in the firmware: DNX's backup

`backup.ts` covers projects, soundbanks and kits, so neither `/waverider` nor `/wavepool` is in a
full backup today: a restored project gets sounds pointing at tables that aren't on the card. That
is DNX's to add; the pool makes it matter more than the store alone did. So does
`STORED_FORM_BY_ROOT`, which needs `wavepool` listed as raw.

## Changes from revision 1 (DNX, 2026-10-06)

1. **Rename reads only the name** (bytes 32..95) and ignores the rest, instead of requiring every
   other byte to equal the stored entry. Same guarantee by construction, no stale-hash input, no
   read before the write.
2. **The project-slot numbering stays** (1..128 as `/projects`, 0 = working); the listing names
   entry 0 `working`.
3. **A and B are 256 sectors apart** (`0x600800 + p`, `0x600900 + p`), not neighbours.
4. **Entries in use** is defined: the count of entries that are not `0xFFFF`. It is now a u16,
   with a flags u16 beside it.
5. **No valid record means the automatic pool**, not an empty one. The automatic flag makes that
   state writable in one sector, and replaces the first-boot migration.
6. **The file form** is stated: the transfer container, kind `0x50`, raw, a 512-byte payload.
7. **Two blind spots documented**: a reused store slot, and the automatic pool's order.

## Changes from revision 2 (DNX, 2026-10-06)

1. **An automatic write with entries is refused** (every entry `0xFFFF`, count 0), not ignored.
   A read of an automatic slot describes what plays and is not a template for a write.
2. **The write proof is one rule**: the generation advanced, and the fields the writer set came
   back.
3. **Occupancy means a record exists**, not a user's choice (a restore can flip it).
