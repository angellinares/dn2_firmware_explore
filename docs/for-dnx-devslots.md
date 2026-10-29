# `/devslots`: the saved state slots, for DNX

**Rev 2, 2026-10-29. Diagnostic builds only (`scripts/build_devslots.py`). Released builds do not have this route. Checked in the emulator (`scripts/emu_devslots.py`, 22 checks). Rev 1 (the three 272-byte files) was read on the instrument on 2026-10-29.**

**Why it exists.** Some faults stay on a unit after a new project, and after a change of OS. The two saved state slots are one place that keeps state through both. This route lets DNX read them as the unit stores them. Then we can compare a reporter's slots with the slots of a clean unit.

## What the slots hold (DN2 1.11)

The two slots are raw sectors `0x40000` and `0x48000`, outside the file system. Each holds the unit's saved working state: a 256-byte header (magic `COKi`), then the working project. The whole state is 12,890,388 bytes, RAM `0x405cd85c..0x41218970`.

Measured on the instrument on 2026-10-29:
- A save writes the whole state to the slot not in use. Then it zeroes the first byte of the other slot's `COKi`. Stock 1.11 does this at `0x400f1e26`.
- A menu change alone does not save. The power cycle saved, and the slots changed places.
- CLOCK SEND is not in the 256-byte header. The header stayed the same when CLOCK SEND changed and the unit saved.

At start-up, the firmware takes the first slot with `COKi` (`0x400f1d3e`) and loads the state into RAM at `0x405cd85c`.

## The files

| path | answers |
|---|---|
| `/` | `devslots` listed after `modinfo` |
| `/devslots` | six entries, used, write-protected (permissions 0x12) |
| `/devslots/0` `slot-40000` | sector `0x40000`'s first 272 bytes |
| `/devslots/1` `slot-48000` | sector `0x48000`'s first 272 bytes |
| `/devslots/2` `ram` | the running copy, RAM `0x405cd85c`, 272 bytes |
| `/devslots/3` `crc-40000` | 197 big-endian CRC-32s, one for each 64 KiB block of slot `0x40000`'s whole state (788 bytes) |
| `/devslots/4` `crc-48000` | the same for slot `0x48000` |
| `/devslots/5` `crc-ram` | the same for the running copy in RAM |
| `/devslots/N`, N = 1000 + source x 256 + block | one block of the whole state: source 0 (slot `0x40000`), 1 (slot `0x48000`) or 2 (RAM), block 0 to 196. Blocks 0 to 195 are 65,536 bytes, and block 196 is 45,332. Not listed |
| a write to any file | refused: `Write: Permission denied` |
| any other number | refused: `devslots: the files are 0 to 5, or 1000 + source x 256 + block` |

The CRC is the standard CRC-32, the same as Python's `zlib.crc32`. Each file is in the transfer container: content kind **0x53**, object version **1**, raw. The firmware reads the sectors or copies the RAM when DNX opens the file. Nothing in the route writes the +Drive or the state.

The file protocol returns 16 bytes a request, so the whole state of one slot would take about 800,000 requests. The CRC files let DNX fetch only the blocks that differ.

## What DNX does with it

DNX's probe page reads any path, with no change to DNX:
1. Open the probe page (`web/probe.html`).
2. Read `/devslots/0`, `/1` and `/2`, as before.
3. Read `/devslots/3`, `/4` and `/5`, the CRC files.
4. Compare each CRC list with the same list from a clean unit. Also compare the three lists with each other.
5. For each block that differs, read `/devslots/1000 + source x 256 + block`. For example, `/devslots/1196` is slot `0x40000`'s last block.
6. DNX saves each file under `probe/` in the DNX folder, as `devslots_<n>_<bytes>B.bin`.

DNX saves the whole transfer stream: a 31-byte header, the body, and a 12-byte trailer. The body starts at +31.

Each CRC file is computed when DNX opens it: 12.9 MB read from the +Drive, or copied from RAM. Expect the open to take a few seconds.

## Stock firmware

Stock 1.11 has no `devslots` among the roots. The open of `/devslots/0` gets the session's `Error: Could not resolve path` (measured in the emulator).
