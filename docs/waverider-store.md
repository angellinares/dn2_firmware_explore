# The Waverider store on the +Drive (format v1)

**What it is.** Waverider's wavetables, written to the +Drive by DNX and read by the
firmware at run time (`docs/waverider-tables.md`: the goal and Tonverk's procedure;
`docs/drive-load-command.md`: how a table reaches the DSP). Agreed with the DNX
session on 2026-10-05. DNX is the master copy and the format authority for what it
writes; this file is the shared definition. Nothing here has run on the instrument
yet.

## Where

- **The region starts at sector `0x600000` (3,072 MiB).** The firmware hard-codes every
  stock slot and has no partition table, and nothing in normal-mode code reads or
  writes above 2,224 MiB (`docs/drive-storage-research.md` §3, read from the code).
  Format and factory reset erase only their own slots. Not traced: whether an OS
  update touches it **[unverified]**. DNX's verify path, which compares content hashes
  against its own manifest, covers that, and ships with the write path.
- It sits inside the pSLC region, which ends at `0x618000` (3,120 MiB). Data may run
  past that end, onto slower TLC.
- It is not at the Digitakt II's `0x5D8000`, where Elektron would put a sample store on
  this family.

## Layout (sectors of 512 bytes; every multi-byte field big-endian)

| sectors | what |
|---|---|
| `0x600000` | **group A** (its own 512 KiB erase group): superblock A in sector 0, index A in sectors 1..64 |
| `0x600400` | **group B**: superblock B in sector 0, index B in sectors 1..64 |
| `0x601000`.. | data: extents, each starting on an 8-sector (4 KiB) boundary |

**Writes go data first, then index, then superblock.** A change writes the new data,
then the index of the group that is **not** current, then that group's superblock with
generation + 1. A failed or cancelled write costs that attempt only; the other group
still describes the store as it was.

**The current group** is the valid superblock with the higher generation. A superblock
is valid when its magic, version, own hash and index hash all check. If both are valid
with the same generation, **group A wins**. If neither is valid, the store is empty.

## Superblock (64 bytes, then zeros to the end of the sector)

| offset | field |
|---|---|
| 0 | magic `"WRTB"` |
| 4 | version u16 = 1 |
| 6 | header bytes u16 = 64 |
| 8 | generation u32 |
| 12 | entry count u32: entries in use |
| 16 | index entries u32 = 256: the fixed maximum |
| 20 | entry bytes u32 = 128 |
| 24 | index hash: xxHash32, seed 0, over the whole fixed index (256 × 128 = 32 KiB) |
| 28 | data start sector u32 |
| 32 | data end sector u32 |
| 36..59 | zero |
| 60 | superblock hash: xxHash32, seed 0, over bytes 0..59 |

The magic is in the first 16 bytes of the region's sector 0, so a single short read
finds it. **DNX writes only after reading a valid superblock**: the route name says
where to look, and the magic is what authorises the write. The index hash sits inside
the superblock hash's range, so a torn superblock can't point at a stale index. Keep
it there if the fields are ever reordered.

**The hash is the firmware's own.** xxHash32 is the DN2 image's routine at
`0x4014be0e`, `XXH32(data, len, seed)`. Its result is the definition, and DNX follows
it. Run on its own code in Unicorn (2026-10-05): the empty input gives `0x02cc5d05`,
the 39 bytes `Nobody inspects the spammish repetition` give `0xe2293b2f`, and 16,384
bytes of `(i * 7) & 0xff` give `0x831953bc`. All seed 0, at even and odd addresses
alike, and the same from an independent implementation. xxHash32 reads its input as
little-endian 32-bit words, while every field here is big-endian. That mixture is
correct, not a bug.

## Index entry (128 bytes; a free entry is all zeros)

| offset | field |
|---|---|
| 0 | flags u16: bit 0 used, bit 1 no interpolation between waves |
| 2 | kind u16: 1 = wavetable |
| 4 | waves u16 |
| 6 | points per wave u16 |
| 8 | sample format u16: 1 = int16 big-endian (see below) |
| 10 | reserved u16, zero |
| 12 | start sector u32 |
| 16 | byte length u32 |
| 20 | table hash: xxHash32, seed 0, of the payload |
| 24 | source hash: xxHash32 of the source audio file, **then** |
| 28 | source size u32 (the order is hash, then size) |
| 32 | name: 64 bytes, Windows-1252, NUL-padded. For display only: nothing reads meaning from it |
| 96 | applied gain u32, 16.16 fixed point: the level change the conversion applied, `1 / peak` (1.0 for a full-scale source, 4.0 for one peaking at -12 dBFS). It is not the float-to-int16 scale. A source peaking below 1/65536 is refused, never clamped |
| 100..127 | reserved, zero |

- **The geometry lives in the index**, never in the name. DNX may write Tonverk's
  `_wt<size>` / `r` convention into the name for people to read; nothing reads it back.
- **No sample rate.** A wavetable is a shape indexed by phase.
- **DNX validates the index before writing it:** extents in bounds, not overlapping,
  aligned. The firmware still bounds-checks each extent on its own, because a bad
  index is exactly what a bounded reader exists to survive.

## Payload, sample format 1

- int16 big-endian, wave after wave, sample after sample.
- Peak-normalised to ±32767, symmetric, rounded half away from zero, as
  `dnfw.waverider.reduce` does. The gain applied is stored at +96.
- v1 geometry: 16 waves × 512 points (16 KiB), what the DSP plays today.

**Why big-endian [S].** The firmware reads sectors straight into the DSP load
command's payload with no conversion. The ColdFire sends 16-bit words big-endian, and
the DSP pairs words 2k and 2k+1 as the low and high halves of its 32-bit word. So
sample n should land at DDR byte 2n as the little-endian int16 the DSP's reader takes.
That chain comes from the DSP gate's frame layout, not from the instrument. **Format 1
stays a hypothesis until a loaded table sounds right**, and that is the acceptance test
for the first written table, not a byte comparison. A wrong guess costs a new value of
the sample format field, not a format revision.

## The `/waverider` route (DNX's Data API, as DNX parses it)

From DNX's `parseListing` and its write path, traced off Elektron Transfer's traffic.

**`/` must list it,** in short form, like `projects`, `soundbanks` and `kits`:
- the entry: `waverider\0`, then kind `01`, layout `01`, then a u32 child count (not
  read by DNX);
- **the `/` reply header must declare 4 entries and carry 4.** The header is `01`,
  u32 first, u32 next, u32 count. A count above the entries sent fails DNX's
  `requireWholeListing` on purpose.

**`/waverider` lists 256 slots,** and `/waverider/<n>` is index entry n, as
`/projects/<n>` is. Each entry is long form:
- kind `00`, layout `02`, then u32 index, u32 size, u16 permissions, then 2 bytes of
  occupancy;
- **permissions `0x007e`**, as a user slot reads. DNX writes only when
  `(permissions & 0x6c) == 0x6c`;
- **occupancy `01 01` used, `00 00` free.** DNX refuses to treat "unknown" as empty;
- **size is the slot's allocation** (16,384), the same on used and free slots, never
  the file length;
- names are Windows-1252, NUL-terminated;
- the listing is paged: honour `first`, send what fits, and declare the true total.
  `/projects` fits 45 entries in 885 bytes.

**Read:** open `0x54` with the path ending in the index, no trailing slash. `0x55`
reads by sequence number, at 2,048 bytes; then close `0x56`.

**Write:** open `0x57` (u32 total length, then the path, NUL-terminated, no trailing
slash). Then `0x58` chunks (u32 handle, u32 **chunk index** from 0, u32 checksum, u32
**this chunk's** length, data), at 32,768 bytes. Then commit `0x59`: nothing lands
before it. The chunk checksum is **CRC-32 with a zero initial value**, over that
chunk's slice. It is not xxHash32: that one is only for the content.

**Mutations** `0x5a`, `0x5b` and `0x5c` take paths with a trailing slash. Which code is
delete is ours to pick, and we tell DNX.

## Order of work (each step on the instrument only with the owner's go)

1. **Firmware:** a read-only `/waverider` route with one synthetic entry. DNX lists `/`
   and `/waverider` and reports field by field what its parser saw.
2. **Firmware:** the bounded writer, behind the magic check. **DNX:** xxHash32, lifting
   its raw-form refusal for non-stock roots, the write path behind its WRITE gate with
   backup-and-verify, and a manifest (source hash, table hash, extent).
3. **One table**, written, read back and hash-compared, then **heard** on a Waverider
   track, before any second table is written.
