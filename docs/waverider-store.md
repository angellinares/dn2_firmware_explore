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
| `0x601000`.. | data: **slot n lives at `0x601000 + n × 1024`**, its own 512 KiB, fixed. 256 slots end at `0x641000`, 130 MiB into the region. The pSLC ends at `0x618000`: slots 0..91 are in it, and the rest run on into the slower TLC (only load speed differs) |

**Fixed extents (agreed with DNX, 2026-10-05).** Every slot has the same place for
ever, `start = 0x1000 + n × 1024` sectors from the region's start, at most 512 KiB.
There is no allocator, so overlap is impossible, nothing moves, and nothing is
compacted. Deleting a table frees its slot and touches nothing else.

**512 KiB, so a Tonverk table fits at its native resolution (owner, 2026-10-05).**
Tonverk's largest table is 64 waves × 4,096 points of int16, 512 KiB (its default,
64 × 2,048, is 256 KiB; today's DSP geometry is 16 KiB). DNX stores tables at full
resolution. What the DSP can hold and play at once is a separate limit: its load area
is 2 MB, four of the largest tables. It is decided when tables are loaded, not here.
128 KiB slots were agreed first and replaced before anything was written.

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
| 28 | data start sector u32: `0x1000` |
| 32 | data end sector u32, exclusive: `0x41000`, the end of slot 255 (130 MiB). (Earlier drafts: `0x21000`, then `0x11000`.) |
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
| 12 | start sector u32: always `0x1000 + n × 1024` for the entry's own slot n; the device refuses anything else |
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
- **DNX validates the index before writing it**, and the firmware checks each entry
  on its own: start equals slot n's, length within 512 KiB, geometry against length.
  A bad index is exactly what a bounded reader exists to survive.

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

**`/waverider` lists 256 slots, numbered 0..255**: the path `/waverider/<n>` and
the listing's index field are both index entry n. **This differs from `/projects`
on purpose.** The stock handlers number slots from 1 (`/projects` lists 1..128,
measured in the emulator on 2026-10-05), and copying that would leave a permanent
off-by-one between the path and the index entry. Each entry is long form:
- kind `00`, layout `02`, then u32 index, u32 size, u16 permissions, then 2 bytes of
  occupancy;
- **permissions `0x007e`**, as a user slot reads, once writes work. DNX writes only
  when `(permissions & 0x6c) == 0x6c`. **Until the writer exists, the listing and the
  file info both say `0x0012`** (write-protected), so no client offers a write that
  can't complete;
- **occupancy `01 01` used, `00 00` free.** DNX refuses to treat "unknown" as empty;
- **size is the slot's allocation** (524,288: the fixed 512 KiB extent), the same on
  used and free slots, never the file length;
- names are Windows-1252, NUL-terminated;
- **paging is the router's, the same for every route** (measured in the emulator,
  2026-10-05). A request's two numbers are **`(first, end)`, a half-open window over
  the entries' index values**, not a start and a count. The router keeps the entries
  whose index is in `[first, end)`, sets `next` to `end` clipped to the directory,
  and `declared` to the number in this page. Without the numbers, it sends all of
  them in one reply. `/projects (0, 45)` carries 1..44 because its indexes start at
  1. `/projects (100, 145)` carries 100..128. `/waverider (0, 45)` carries 0..44 and
  `(250, 300)` carries 250..255. The handler only builds the vector and never sees
  the window, so `/waverider` can't declare the directory's total on a page. A
  caller that pages should go on until a page comes back empty, or list unpaged as
  DNX does. Unpaged, all 256 arrive in one reply (3,853 bytes with empty names).
- the `/` reply that lists `waverider`: `waverider `, kind `01`, layout `01`, child
  count 256. The stock `/` lists `projects` (128), `soundbanks` (8) and `kits` (8): the
  count is whatever the next level down holds.

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

## A slot as it reads back (measured in the emulator, 2026-10-05)

`/waverider/<n>` reads as Elektron's transfer container: a 31-byte header, the payload,
and a 12-byte trailer. The header from `0x0D` is four big-endian words (DNX, from 140
containers):

| offset | field | /waverider/<n> |
|---|---|---|
| `0x0D` | content kind | `0x57` ('W'), ours. Stock: 1 project, 3 sound, 5 kit |
| `0x11` | object version | 1: **the store format's version**, its own namespace. Elektron's project object versions (1.11 writes 5, and `/projects` refuses above 5) say nothing about it |
| `0x15` | index, bank × 256 + slot | n: the bank byte is 0, and byte `0x18` is the slot, stamped by the device |
| `0x19` | uncompressed length | the payload's byteLength |
| `0x1D` | 1 = LZ4, 0 = raw | 0 |
| `0x1E` | the trailer's length | 12 |

A byte-exact verify expects `0x18` = n and kind `0x57`, then compares the payload with
the table hash.

**Writes use the same form as reads: raw** (`0x1D` = 0). The `/waverider` writer is
ours, and it takes what a read returns, so a slot round-trips unchanged. A client
checks `0x1D` per route: 1 for the stock roots, which store LZ4, and 0 for
`/waverider`.

## Writing a slot (measured in the emulator, 2026-10-05)

**A `/waverider/<n>` file is `[128-byte index entry][table]`, both ways.** A write
sends it, a read returns it, inside the container above (kind `0x57`, version 1,
raw). The entry is exactly the index entry the device will store.

Through the stock write session (`0x57`, `0x58`, `0x59`), on a formatted +Drive image,
with build `wrroute9`:

| what | what the device does |
|---|---|
| a valid file to an empty store | the commit writes the table to slot n's extent, then group A's index, then its superblock (generation 1). The listing shows the slot, and a read returns the same bytes, with byte `0x18` stamped n |
| a second slot | the index and superblock go to the other group (generation 2), and the first slot carries over |
| the same slot again | generation 3, back into group A: the slot reads back the new table, and the other slots are kept |
| a table whose hash doesn't match the entry's | **the commit still answers ok** (the stock session decides the reply before our callback runs), and **nothing is written**: the slot doesn't appear |
| container kind not `0x57`, version not 1, `0x1D` not 0, or a length outside 129 .. 128 + 512 KiB | refused at the first chunk: `slot N: the file is not a Waverider table (container kind)`, `... unknown store format version`, `... the body must be raw, not LZ4`, `... the file must be a 128-byte entry and a table of at most 512 KiB`. The commit then answers `Header was not processed` |
| `0x1D` = 1 on a raw body | the stock decompressor refuses first: `Failed to write data: Error decompressing stream; invalid buffer length` |

**Checked at the commit** (silently refused, as above): the entry is used, kind 1,
format 1; its start is slot n's own; its length is the table's, and is waves ×
points × 2; and the table's xxHash32 equals the entry's table hash. **So a write is
confirmed only by reading back:** list the slot, read it, and compare. The device's
last outcome is also in `wr_write` (probe PEEK): commits, last (1 written,
2 aborted, 3 entry, 4 hash, 5 drive, 6 range), slot, generation.

**How (docs/data-api-routes.md):** kind 1, a memory stream over one RAM stage of
128 + 512 KiB + 512. The info's callbacks are a pre-check (+28), the commit (+76) and
the header check (+108). The pre-check tells a read open from a write by its return
address (`0x400e9fc2`, the read open's: 1.11 only, to be found again for 1.12). One
transfer at a time.
