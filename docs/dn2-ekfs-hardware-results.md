# Native ekFS on DN2: external hardware results and storage overlap

**Tests: 2026-10-08. Report: 2026-10-26.** A separate experimental port of
DT2 OS 1.16 filesystem code into DN2 OS 1.11 retained files across power cycles
and loaded a saved sample into ONESHOT on one Digitone II. This extends the
feasibility evidence in [the drive research](drive-storage-research.md) and
[the DT2 port research](dt2-machine-port.md).

These are contributor-reported hardware measurements, not an upstream build or
an upstream reproduction. The report was checked against the contributor's saved
operation results and capture analyses. Raw captures, firmware images, donor code
and sample audio are not included. The hashes below identify those local test
artifacts; they do not make the experiments reproducible from this repository.
The September 29 decision to keep ONESHOT implementation out of this repository
is unchanged.

## What ran

The filesystem was initialized and formatted in an earlier, explicitly requested
Maintenance-mode trial. The file trials below mounted that existing filesystem;
neither sent a format command. Maintenance mode cannot play audio, so playback
was a separate normal-mode trial with a different firmware image.

| Trial | Before power cycle | After operator-confirmed power cycle |
|---|---|---|
| Synthetic 16-byte file | Created object 3; wrote and read 16 bytes | Mounted afresh; reopened object 3; read the same 16 bytes; file-write count 0 |
| 47,104-byte sample bank | Created object 4; wrote and read all 47,104 bytes | Mounted afresh; reopened object 4; read the same 47,104 bytes; file-write count 0 |

In all four operations, the mount succeeded (`result = 0`, `mounted = 1`),
the reported file size and final offset matched the expected length, and the
EOF/close return codes were zero. The native media-error flag remained clear.
The post-cycle commands requested verification only, without rewriting either
file. This does not establish that mounting performs no metadata writes.

The 16-byte synthetic payload was `444e3246494c453120261008b16b00b5`.
Both readbacks had SHA-256
`f2e1d737fb8f790195a30beee28f576f815f0f0d94205f00a3b4d6e6784ab5e8`.

The larger bank contained 2,708 mono PCM16 frames at 48 kHz, guards and a
deterministic non-audio tail. Its 47,104-byte extent crosses the native 32 KiB
page boundary; the full bank, including the tail, matched after the power cycle.
Its SHA-256 was
`49f680159d2019f5e53e24b013177c5612ebabf5c7e4714ab6d9ef659afff542`.
This was a purpose-built bank, not a general WAV-import test. The licensed source
audio and derived bank are excluded from this contribution.

The captured stock header sector (LBA 0) and ekFS superblock were unchanged
across these file operations. That comparison covers those captured sectors,
not every stock project, preset or filesystem metadata block.

## From disk to DSP

A subsequent normal-mode build reopened object 4, read and verified all 47,104
bytes, then sent the sample to the DSP. All 21 transfer packets were acknowledged;
the diagnostic reported zero timeouts, refusals or errors. EOF and close returned
zero. The host measured 12.32 seconds from the load request to its first success
observation, including verification and transfer; this is not a raw disk-speed
measurement.

ONESHOT produced recorded audio and the operator confirmed the expected snare.
FM Tone was audible before and after loading. The operator also played notes
during the trial, so the first scheduled note was not an isolated audio test.
This establishes a bounded disk-to-playback path. The tested build used one fixed
sample at SAMP 0 and an explicit host load request after boot; it did not establish
automatic project restoration, a general browser or a complete DT2 machine port.

## Firmware identities

Each SHA-256 identifies the complete SysEx file used for that trial, not a stock
image or a release offered by this repository.

| Local experimental build | SysEx SHA-256 |
|---|---|
| `drive_file_v1_MAINTENANCE` | `ad4b8cb397666f70af60aa9e6f489006b929048aa97cc6571e4326ffbd75127b` |
| `drive_sample_v1_MAINTENANCE` | `635dc0b05c743b383571dcfc8e003667d91077c1ac1f7ab7748d9551fb2c3509` |
| `oneshot_drive_v1_EXPERIMENTAL` | `aade2877ae0164d6dc16d09bf941da7409e79bbfcb8ae1dd297b4f8f35743500` |

## Storage compatibility: Waverider overlaps

All addresses here are **512-byte sectors**, with exclusive upper bounds.
The experimental formatter's write guard admitted positive, sector-aligned
requests of at most `0x14000` bytes inside `[0x5D8000, 0x2DF0180)`.
That is the guard's permitted range, not a claim that every sector was written
or that its upper bound is the physical end of every DN2's eMMC. The formatter
MAIN image was identified by SHA-256
`76a2875362a21e9d4dd8c6fb7ffaf60c8e495ba942b9adbe3fe8109edb0af3ee`.

[Waverider format v1](waverider-store.md) places its superblock/index groups at
`0x600000` and `0x600400`, with 256 data slots starting at `0x601000`, each
`0x400` sectors long. Its full store occupies `[0x600000, 0x641000)`:

```text
0x5D8000 < 0x600000 < 0x601000 < 0x641000 < 0x2DF0180
            Waverider start     Waverider end
```

The entire Waverider store lies inside the experimental filesystem write range.
Separately, the [DT2 storage map](drive-storage-research.md) derives file-data
block starts at `0x5EE180` / `0x5EE980`, with allocation continuing toward the
device's end. That derived allocator layout explains why being above ekFS's
initial metadata does not reserve Waverider's sectors. Neither the write guard
nor that static layout proves the trials actually wrote those sectors.
Waverider's fixed slots prevent overlap between its own tables, not overlap with
another allocator.

This is a layout conflict, not a report of Waverider corruption observed on an
upstream device. The experimental formatter has no Waverider-preservation
contract. Do not treat formatting or switching between these storage designs as
a migration procedure. Coexistence needs an explicit shared layout and allocator
reservation or a deliberate export/migration path before either writer is enabled.
No storage implementation or allocation is changed by this report.

## Remaining evidence gaps

The bounded trials establish file persistence and one playback path. They do not
qualify interrupted writes, power loss during writes, full-volume behavior,
directory operations, deletion/reuse, endurance, general sample formats or
concurrent real-time playback and filesystem traffic. Whole-project preservation
and coexistence with Waverider remain untested. Independent upstream reproduction
would need a reviewed implementation and synthetic test content; these results
do not establish that the complete experimental firmware is stable.
