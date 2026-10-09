# The DSP's DDR: how much there is, and what is free

**Answer (2026-10-09):** 512 MB. Stock uses the first ~5.2 MB; the other ~507 MB
(`0x80531000..0xa0000000`) was never written by anything during boot, a heavy project's
playback, pattern and kit changes, FX at extremes and a project save. It is free for the
wavetable pool, Waverider's current 4 MB (`0x80600000..0x80a00000`) included.

## Size: 512 MB [D], three sources agreeing

| source | reads |
|---|---|
| the board | Kingston `D2516ECMDXGJD` beside the ADSP-21569 (`docs/hardware.md`): 4 Gbit by the part-number convention **[S]** |
| the stock init program's DMC settings (section 7 block 1, bw `0x28242c4c`) | `0x0af00622`: DMC_CFG's low half `0x0622` = EXTBANK 0 (one bank), SDRSIZE 6 (**4 Gbit**), SDRWID 2 (16 bits) (ADSP-2156x HRM, DMC_CFG) **[D]** |
| the same table's TR1 `0x50ea1450` | TREF `0x1450` = 5,200 DCLK = 7.8 µs at the 667 MHz DCLK decoded from the CGU (`docs/sharc-load.md`): DDR3's refresh interval **[D]** |

The DMC's window is 1 GB (`0x80000000..0xbfffffff`, the datasheet's memory map); with a
512 MB part, DDR is `0x80000000..0x9fffffff`. The SHARC image never names the DMC's
registers: the init program reaches them through a base table, as it does the CGU's.

## Use

| what | range | how known |
|---|---|---|
| stock image (code, data, `.bss` fills) | `0x80000000..0x8052fbe0` | the boot stream's blocks **[V]** |
| stock, written at init past the image | up to `0x80530be3` (4 KB) | the emulator's engine-init snapshot: 2.7 MB of DDR written, nothing at or above `0x80531000` **[E]** |
| written at run time above `0x80531000` | **nothing** | the instrument, `ddrscan-usbprobe` (below) **[M]** |

## The playback check: `ddrscan-usbprobe` (9adfeb38)

`scripts/build_ddrscan.py`, `dnfw.waverider.ddrscan`, `csrc/waverider/sharc/ddrscan.asm`.
Stock 1.11 + the USB probe + the idle stub + a scanner; no Waverider. Eight boot-stream
fill blocks write `0xa5c35a3c` over `0x80531000..0xa0000000` before any stock code runs (a
fill block's ARGUMENT is its value, ADSP-2156x HRM; stock's are all 0). The idle loop's back
edge goes through the scanner, 32 words a call, which publishes each pass's changed words,
the first and last, and a sticky 2 MB granule bitmap through reply word 2
(`tools/dn2ddrscan.py`). Checked first in the emulator on an 8 KB span with the same code
(`scripts/sharc_ddrscan_check.py`: planted words found, and only those; the control 0).

On the instrument (owner, 2026-10-09), each reading after ~9 s passes over 132,856,832 words:

| state | passes | words changed | granules ever written |
|---|---|---|---|
| booted, loading a project | 8 | 0 | none |
| a mid-load project, many voices and FX (SHARC 66.4 %) | 21 | 0 | none |
| another pattern | 34 | 0 | none |
| two kit changes | 37 | 0 | none |
| FX at extremes | 49, 55 | 0 | none |
| after a project save | 58 | 0 | none |

The pattern held from the first pass, so the fill landed (a refused value would read as
nearly every word changed).

**Limits.** A path not exercised in those ~10 minutes (the arpeggiator, MIDI tracks'
heavy use, a firmware feature that allocates on demand) could still write there; the
scanner build can be flashed again for any such case. The scanner only sees writes that
leave a word different from the pattern.

## What it means for the pool

A Tonverk-scale pool fits: 127 tables of 64 x 2048 with mip levels (~1 MB each) is about
127 MB; at Tonverk's largest, 64 x 4096 (~2 MB with levels), about 254 MB. The +Drive
store's 512 KiB slots and the load time per table bound it first, not memory.
