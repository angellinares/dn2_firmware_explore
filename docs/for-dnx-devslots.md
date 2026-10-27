# `/devslots`: the device settings slots, for DNX

**Rev 1, 2026-10-27. Diagnostic builds only (`scripts/build_devslots.py`). Released builds do not have this route. Checked in the emulator (`scripts/emu_devslots.py`). Not checked on the instrument yet.**

**Why it exists.** Some faults stay on a unit after a new project, and after a change of OS. The device settings block is one place that keeps state through both. This route lets DNX read that block as the unit stores it. Then we can compare a reporter's block with the block from a clean unit.

## Where the settings live (DN2 1.11)

At start-up, the firmware reads 256 bytes from raw sector `0x40000` into RAM at `0x405cd85c` and checks them. If the check fails, it tries sector `0x48000`. Each slot starts with the 272-byte settings block (magic `COKi`, MIDI CONFIG among it). The working project follows the block. The slots are outside the file system, so no other route reaches them.

## The routes

| path | answers |
|---|---|
| `/` | `devslots` listed after `modinfo`, with three children |
| `/devslots` | three entries, used, 272 bytes each, write-protected (permissions 0x12): 0 `slot-40000`, 1 `slot-48000`, 2 `ram` |
| `/devslots/0` | sector `0x40000`'s first 272 bytes |
| `/devslots/1` | sector `0x48000`'s first 272 bytes |
| `/devslots/2` | the running copy, RAM `0x405cd85c`, 272 bytes |
| a write to any of them | refused by the session: `Write: Permission denied` |
| `/devslots/3` and up | refused: `devslots: the files are 0, 1 and 2` |

Each file is in the transfer container: content kind **0x53**, object version **1**, raw. The firmware reads the sector or copies the RAM when DNX opens the file. Nothing in the route writes the +Drive or the settings block.

## What DNX does with it

DNX's probe page reads any path today, with no change to DNX (DNX, 2026-10-27):
1. Open the probe page (`web/probe.html`).
2. Type `/devslots/0` in the file box.
3. Press Read.
4. Do the same for `/devslots/1` and `/devslots/2`.
5. DNX saves each file under `probe/` in the DNX folder, as `devslots_<n>_<bytes>B.bin`.

DNX saves the whole transfer stream: a 31-byte header, the 272-byte body, and a 12-byte trailer (315 B). The body is at +31..+302. DNX does not interpret the bytes. We compare them with a clean unit's files.

Block offsets measured in the emulator: CLOCK RECEIVE is block byte +0x3e, CLOCK SEND +0x45. The checksum at +4..+7 changes with each of them.

## Stock firmware

Stock 1.11 has no `devslots` among the roots. The open of `/devslots/0` gets the session's `Error: Could not resolve path` (measured in the emulator).
