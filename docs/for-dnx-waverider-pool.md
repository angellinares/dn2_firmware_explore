# For DNX: renaming tables and the per-project wavetable pool

What the firmware will add to the Waverider store and the Data API, so that DNX's Library tab
(DNX option 1) and the instrument's PRESET/KIT page 2 (option A) can manage wavetables. Decided
by the owner on 2026-10-06:
- the pool is **per project**: up to 127 tables, chosen from the +Drive store, saved and loaded
  with the project;
- a sound remembers a **pool slot**.

The store itself, the index entry and the `/waverider` route are in `docs/waverider-store.md`; this
builds on them and changes none of it. **Status: a proposal for DNX to check. Nothing here is built
yet.**

## The numbers (read this first)

One table has several numbers. Every field below says which one it carries.

| name | range | what it is |
|---|---|---|
| **store slot** | 0..255 | the index entry and the `/waverider/<n>` path (`docs/waverider-store.md`) |
| **pool index** | 0..126 | an entry in a project's pool list |
| **shown slot** | 1..127 | what both UIs display: pool index + 1 |
| **coarse** | 0..128 | what a sound stores in TBL1 / TBL2 (the parameter word's high byte) |
| **project slot** | 0..128 | which project a pool list belongs to: 1..128 as `/projects` numbers them, and **0 for the working project** |

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
`0x59` commit) on `/waverider/<store slot>`, with a body of exactly **128 bytes**: the entry, and
no table after it. The firmware takes that as a rename.
- The slot must be in use. A free slot is refused.
- Every field of the entry except the name (offsets 32..95) must equal the stored entry, byte for
  byte. Anything else is refused, so a rename can never change the geometry, the hashes or the
  extent.
- Only the index is written (the non-current group, then its superblock, generation + 1), never
  the slot's data. So a rename is one index write: no 512 KiB, and no risk to the samples.
- The refusals answer the way a write's do today: the commit returns an error, and
  `wr_write.last` says why.

Today a body of 128 bytes or less is refused ("the file must be a 128-byte entry and a table"). This
makes exactly 128 the rename and leaves everything else as it is.

## 2. The pool lists

### On the +Drive

The store region has 2,048 unused sectors between group B and slot 0's data: `0x600800..0x601000`.
Each project slot p (0..128) gets **two sectors**, A at `0x600800 + 2p` and B at `0x600801 + 2p`,
written alternately like the index groups. The current record is the valid one with the higher
generation; on a tie A wins; if neither is valid, the pool is empty. 258 sectors in all.

**A pool record**: 512 bytes, every multi-byte field big-endian, as in the store.

| offset | field |
|---|---|
| 0 | magic `"WRPL"` |
| 4 | version u16 = 1 |
| 6 | **project slot** u16: 0..128, and it must equal the record's place |
| 8 | generation u32 |
| 12 | entries in use u32 |
| 16 | 127 × u16: entry j is the **store slot** at **pool index** j, or `0xFFFF` for none |
| 270..507 | zero |
| 508 | xxHash32, seed 0, over bytes 0..507 |

An entry may name a store slot that is free, or whose table the DSP can't play (not 16 × 512).
That pool slot then plays the built-in Prim., as an unknown slot does today. The record is valid
anyway: deleting a table must not break every project that uses it. DNX should warn about it,
not repair it on its own.

### The route

**A new root entry, `wavepool`**, listing 129 entries, **0..128 = project slot**, with the same
long-form layout as `/waverider`'s:
- occupancy `01 01` when that project slot has a valid record with any entry in use, `00 00`
  otherwise;
- the size is 512.

The `/` reply then declares and carries 5 entries.

- **Read:** `/wavepool/<project slot>`, as `/waverider/<n>` is read. It returns the current
  record, 512 bytes. A project slot with no valid record returns an empty record: the right
  magic, version and project slot, generation 0, every entry `0xFFFF`, and a correct hash.
- **Write:** `/wavepool/<project slot>`, 512 bytes, the whole record.
  - **Checked:** the magic, the version, the project slot against the path, every entry
    `0xFFFF` or 0..255, the entries-in-use count against the entries, and the hash.
  - **Ignored:** the generation you send. The firmware writes the non-current sector with the
    current generation + 1.
  - **No partial writes:** the record is small, so it's always whole.
- **Delete:** not offered. An empty record clears a pool.

Every project's list is readable, not only the working project's. That is what lets DNX say
"this table is in three projects' pools" before a delete, with no other verb.

### What the instrument does with them

- **Project slot 0 is the working project's pool**: the one TBL plays and the instrument's pool page
  edits. It is kept with the working project, so it survives a reboot as everything else does
  (the working-project rule).
- **SAVE PROJECT to slot k** copies record 0 to record k.
- **LOAD PROJECT k** copies record k to record 0, then refills the DSP's pool from it.
- **A write to record 0 from DNX** refills the DSP's pool, as a write to the store does today
  (`wr_store.changes`). A write to any other record changes only the +Drive.

**Not covered yet (it needs the stock project operations hooked):** copying, moving, clearing or
deleting a project from the instrument's own project manager doesn't carry its pool list along. The
pool record stays at the old project slot. Until that is built, DNX should treat a pool record as
belonging to whatever project now sits in that slot, and say so when it can tell.

## 3. What changes for the pool you see today

Today's pool is automatic: every stored 16 × 512 table, in store-slot order. With the lists, the
working project's record decides the order instead. The first time a build with this boots,
it **builds record 0 from today's automatic pool**, if record 0 has no valid record yet. That way
TBL values in sounds made since #191 keep playing the same tables.

## Asked of DNX

1. Does a 128-byte write fit your write path as it is, or does it need a refusal lifted on your
   side (a write without a table)?
2. Is the project-slot number for `/wavepool` the one you want: 1..128 as `/projects` lists them,
   0 for the working project?
3. Anything in the record layout you'd rather have differently, before it's built.
