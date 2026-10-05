# The Data API's routes on DN2 1.11: how `/projects` is served, and how a route is added

What a new route (`/waverider`, `docs/waverider-store.md`) has to look like. Read
2026-10-05 from the disassembly, and checked where marked in the Rust emulator
through the SysEx bridge (digikit `sysex_bridge`: DNX's own frames into the
firmware's router `0x4012166e`, replies from the sender `0x401233f2`). Builds on
`docs/drive-storage-research.md` §4, which mapped the layers.

## The way in

- **The SysEx router** `0x4012166e(msg, len, source)` hands an Elektron message to
  **the MidiRpc server**, a singleton at `0x446479e0` (0xe8 bytes, built by
  `0x401330c0`). The server is registered at start-up as a SysEx callback
  (`0x4002e9b2`, stored at `0x4002efcc`).
- `0x4013311a` copies the message, parses it into a `MidiRpcMessage` (`0x4013be10`),
  and dispatches it (`0x40125cbe`). Each request type is a `MidiRpc*Request` class
  (RTTI), picked out with `dynamic_cast`. The reply goes back through the SysEx
  sender in 144-byte pieces. **[emulator]**

## The handlers and their registry

- **One registry**, at `0x4059cd24`, set up by `0x400eb040`. It holds the router's
  route vector (28-byte entries at `+12..+20`) and the handlers' vector at
  `+48..+56`.
- **Built once at start-up** in `0x4002b8c8`. For each handler it allocates the
  object, fills its `std::function` callbacks, and calls **`0x400ead92(registry,
  &unique_ptr)`**. That call first runs the handler's `register_route(registry)`
  (vtable slot 3), then appends the handler to the vector, which grows if full.
- **A handler's vtable has four slots:**

| slot | ProjectHandler `0x401feb88` | SoundbankHandler `0x401fef4c` | KitHandler `0x401ff2d8` |
|---|---|---|---|
| 0, 1 | destructors `0x401b2390`, `0x401b23cc` | `0x401b34ac`, `0x401b34e8` | `0x401b397a`, `0x401b39b6` |
| 2 | **root entry** `0x400eb084`: `"projects"`, 128 | `0x400ec5ac`: `"soundbanks"`, 8 | `0x400edb54`: `"kits"`, 8 |
| 3 | **register_route** `0x400ebbe8` | `0x400ed8cc` | `0x400eee7a` |

- **The root entry** takes a hidden result pointer in `a0`, and returns the struct
  `{std::string name, u32 children}`. The name is made with the firmware's string
  constructor `0x401ce69e(dst, cstr, alloc)`.
- **`/` is built from the handlers' vector.** Listing `/` runs the router
  (`0x401b2c38`) and calls slot 2 of each handler. The emulator showed `projects`
  128, `soundbanks` 8, `kits` 8, declared 3, carried 3 (DNX's parser). So **a fourth
  handler added through `0x400ead92` should appear in `/`, with the count matching**.
  Not yet run: that is the first check of the route build.

## A route

`register_route` (`0x400ebbe8` for projects) adds one route per pattern:
1. a `std::string` of the pattern (`/projects` `0x4021ddf6`, `/projects/*`
   `0x4021de00`, `/projects/*/.metadata` `0x4021de0c`);
2. a `std::function`. Its closure is 4 bytes on the heap holding the handler's
   `this`. Its manager is `0x400eb0b6`. Its invoker is per pattern: `0x400ebb54` for
   `/projects`, `0x400eb9b6` for `/projects/*`;
3. `0x400ec394` splits the pattern into components;
4. the route goes into the vector at `registry+12` (28 bytes each, `0x401b276a`, or
   `0x401b2b00` when the vector grows).

## A directory listing: the directory's own callback builds every entry

Listing `/projects` (DNX's frame through the bridge) runs `/projects`'s invoker
`0x400ebb54` **once** and the per-slot invoker `0x400eb9b6` **never**. **[emulator]**
The invoker, called with a hidden result pointer in `a0`:
- calls `0x401b250e(local, arg2)` with its second stack argument (the path
  arguments);
- builds the entries with `0x400eba3e(result_vector, this)`;
- writes the result **`{u8 ok = 1; std::string error = "" (rep 0x44647a74); vector
  entries}`**, the vector copied in with `0x401b26ce`;
- and frees its temporaries (`0x401b247e`, `0x4018dc80`).

**A listing entry, 20 bytes** (`0x400eba3e`, one per project slot, k = 0..127):

| offset | field | /projects |
|---|---|---|
| 0 | u32 index | **k + 1**: the stock slots count from 1 |
| 4 | `std::string` name | `0x4012d63c(fs, k)`, through `0x401cd44e` |
| 8 | u32 size | `0x01000000`, 16 MiB: the allocation, never the length |
| 12 | u16 permissions | `0x12` if write-protected (`0x4012d5a8`), else `0x7e` |
| 14, 15 | u8, u8 | occupied (`0x4012d522`), twice: DNX's `01 01` / `00 00` |
| 16 | u8 | 0 |

The vector grows with `0x401b2584(vec, &entry)` when full; otherwise the entry is
built in place, and the name is moved in with `0x401cdd94`.

The router turns that vector into the reply and does the paging, for every
route alike. The page request is **`(first, end)` over the entries' index values**:
`declared` is the page's count, and `next` is `end` clipped to the directory
(`docs/waverider-store.md` has the measurements). DNX's "a page from 0 for 45
carried 44" is a window `[0, 45)` over slots that start at 1.

## What `/waverider` needs (step 1, read-only)

- A handler object whose vtable is: two destructors (never called, since handlers
  live for the whole run), a root entry giving `"waverider"` and 256, and a
  `register_route` adding the pattern `/waverider`.
- An invoker for `/waverider`, shaped like `0x400ebb54`, whose entry builder fills
  256 entries: index n (0..255), the name from the store's current index (empty
  for a free slot), size 16,384, permissions `0x7e`, occupancy `01 01` or `00 00`.
  The store is read with the block driver `0x4012c59a`.
- One call at the end of `0x4002b8c8`: allocate it, then
  `0x400ead92(0x4059cd24, &ptr)`.
- Reads and writes (`/waverider/*`: open, read, write, commit) come in step 2. They
  need the per-slot `FileStorageInfo` (`0x400eb6d4` for projects: kind 2, the
  permissions, the byte offset, the size, the index). And the bounded writer:
  MmcFs refuses sectors past `0x457FFF`, correctly, so our route can't reuse its
  writer.

**For 1.12** (`os-112-support`): every address above is 1.11's. Each site is recorded
with its shape, so it can be found again: the registry's add `0x400ead92` (calls
slot 3, then pushes onto `+52`), the start-up builder that calls it three times, and
the 20-byte entry loop with its `cmpil #128`.

## A file route: what opening `/projects/<n>` builds (step 2, in progress)

Opening `/projects/1` for reading (`0x54`, through the bridge) answers `ok, handle 1,
length 0x1000` on a blank card. `/waverider/0` answers `Error: Could not resolve
path`, since step 1 registers no file route. **[emulator]**

The per-slot invoker `0x400eb9b6` builds the slot's **`FileStorageInfo`** in
`0x400eb6d4`. It refuses a bad id with `project id` / `project id out of range` /
`Active project not supported`. The fields read so far:

| offset | field | /projects/<id> |
|---|---|---|
| 0 | ok | 1 |
| 4 | kind | 2 |
| 8 | u16 permissions | `0x12` or `0x7e` (`0x4012d5a8`) |
| 12 | byte offset on the eMMC | `(id + 10) << 24` |
| 16 | size | 12,890,116 |
| 20 | index | id − 1 |
| 24 | stored length | `0x4012d6fa` |
| 76 | `std::function` | manager `0x400eb41e`, invoker `0x400eb3d8`: forwards to a captured function |
| 108 | `std::function` | manager `0x400eb4ac`, invoker `0x400eb2f2` |

The open makes one stream: `0x400f0270` is a `make_shared` of a 0x34-byte reader,
constructed by `0x400f0232`, with control-block vtable `0x401ff554` (the
MmcStreamReader of `docs/drive-storage-research.md`, a 32-bit byte offset). Our
region's first byte, 3 GiB, still fits that offset. **Not yet read:** what the
two `std::function`s produce, and whether kind 2 changes the bytes on the way
out. So a `/waverider/<n>` read needs either a kind that streams raw bytes, or a
reader of our own behind those factories. The functions the open runs, found by
counting entries in the emulator: `0x400e9202`, `0x400e9654`, `0x400e9e2c`,
`0x400e9f7a` (the Data API's open), `0x400eb9b6` and `0x400eb6d4` (the slot's info),
`0x400eb41e` (21 calls) and `0x400eb4ac` (10), the managers, and `0x400f0270`.

## Writes, measured (step 2, in progress)

- **A stock write works in the emulator.** The presets project (257,942 bytes,
  DNX's corpus; the owner allowed it for emulator tests) was written to
  `/projects/1` on a formatted +Drive image. The open answered handle 1, the 8
  chunks were each confirmed with the running byte total, and the commit returned the
  total, `0x3ef96`. The chunks collect in a `MemoryStreamWriter`. **[emulator]**
- **A write goes through the same file route as a read.** The write-open runs the
  slot's file invoker. `/waverider/1` answered with our own refusal when slot 1 was
  empty.
- **The write path calls a writer callback in the file info without checking it.** A
  write to a `/waverider` slot whose info has every callback empty ran into
  `0x40138d92`, a `bra.s *` after an `illegal`: the firmware's `abort()`. The call to
  the router never returned. **On the instrument that freezes the UI task.** Until
  step 2 provides a writer, the route answers every slot's info with permissions
  `0x12` (write-protected). The stock path then refuses at the first chunk, with
  `Write: Permission denied`, and the commit with `Footer was not processed`. A read
  only needs bit 1, so reads still work. The listing keeps `0x7e`, the contract.
- `0x400eb2f2`, the `/projects` info's callback at +108, **checks the incoming
  container's header**: its length against the slot's capacity, a format byte equal
  to 1 (+13), and a version at +17 that isn't −1 and is at most 5. It answers
  `Expected<bool>` with the refusals at `0x4021dd64`, `0x40213685`, `0x4021dd79` and
  `0x40213697`.
- **A trap in our own tooling:** Git Bash rewrites a `/projects/1` argument to
  `C:/Program Files/Git/projects/1`. Every write that seemed refused with "Unable to
  handle path" was that. Run the frame builders with `MSYS_NO_PATHCONV=1`.
