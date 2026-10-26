# The stall probe: what the SHARC+ charges for an instruction pair

`stallprobe` is a diagnostic build. It times instruction pairs and two versions of the Waverider reader loop on the instrument's SHARC+. It changes no sample. It is not a release.

## Why

Batch A of the Waverider load plan (PR #265) saved about 4.5 points of a frame on the unit in its plain-reader part (load plan #2). digikit's cycle model (`tools/sharc_dev/sharc_cpi.py`) prices the stalls in the SHARC+ Programming Reference's tables, and it sees 0.4 points for the same change (2026-10-25, the Waverider calibration runs). So the chip charges about 29 cycles more a sample for the old loop than any listed stall explains.

The old loop has three places where a value read from memory feeds the next instruction. The PRM lists no stall for that on a data register. The probe measures it, and the other pairs batch A changed.

## The build: `stallprobe1-usbprobe`

`scripts/build_stallprobe.py` makes it from stock 1.11:

- Section 3: the USB probe on stock (`dnfw.mods.usbprobe`). It is the same as `accelprobe1-usbprobe`, but for the tag.
- Section 7: stock, the idle stub (`dsp.section7_idle_only`), `csrc/waverider/sharc/stall.asm`, its state block, two guarded rows in DDR, and the reader's three words at their Waverider addresses.

No Waverider code is in either processor.

`dnfw.waverider.stallprobe.asm()` generates `stall.asm`. To change it, edit the generator. Then run `python scripts/build_stallprobe.py --assemble`.

## How it works

The idle loop's back edge jumps to `stall.asm`, which goes on to the idle stub. On the first call, and then once every 262,144 calls until 16 runs, it runs the suite:

- **Pairs.** A test is a DO loop of 64 passes over 8 copies of a pair. Each pair has a control with the same instructions, where the second instruction reads nothing the first wrote. The difference over 512 pairs is the stall of one pair. `nop` gives the loop's own cost.
- **Readers.** The sample loop of `reader_miph2.asm` before batch A (fmdepth2, 0.3.6) and after it (batcha1, 0.3.7), copied without change. Each runs 32 samples over two guarded 2,048-sample rows in DDR, as the instrument plays a table.

Each test runs 8 trials in a row, and EMUCLK times each trial. The probe keeps each test's least and most cycles over every trial of every run. Interrupts stay on. An interrupt inside a trial only raises that trial, so the least is the cost.

Every other call publishes one more half of the 67 words, every 64th call, through reply word 2. The words are the runs done, and each test's least and most.

| Pair | Instructions | From |
|---|---|---|
| `ld_add` | `R0 = DM(2, I4); R9 = R9 + R0` | the old loop's last two instructions |
| `abs_fmul` | `R1 = DM(0x2de6c0); F0 = F1 * F3` | the old loop's gain |
| `abs_pass` | `R1 = DM(0x2de6c4); R1 = PASS R1` | the old loop's mix flag |
| `idx_fmul` | `R1 = DM(I1, M5); F0 = F1 * F3` | the same with an index register |
| `ld_floatby` | `R8 = DM(I0, M5); F4 = FLOAT R4 BY R8` | a loaded shift |
| `imm_floatby` | `R8 = -15; F4 = FLOAT R4 BY R8` | the old loop's scale |
| `fadd_fadd` | `F0 = F5 - F6; F1 = F0 + F0` | PRM Table 4-36 row 1 (1 cycle): the method's check |
| `fadd_fmul`, `fmul_fadd` | a float result into a multiply or an add | the cubic |
| `fadd_store` | `F0 = F5 + F6; DM(I2, M5) = F0` | the sample's store |
| `pass_ifne` | `R3 = PASS R3; IF NE F0 = F5 + F2` | the conditional add |
| `f0_single` | `F0 = FLOAT ..; F1 = FLOAT ..` | silicon anomaly 20000072 |
| `fix_fix` | `R0 = R1 + R2; R3 = R0 + R4` | expected 0: the method's check |
| `ddr_swse`, `ddr_use` | a 16-bit load from DDR (a cache hit), alone and feeding an add | the taps |

## Checked in the emulator

```
python scripts/sharc_stall_check.py
```

This runs the stream in digikit's Rust engine from the idle loop's top. On 2026-10-25 all ten checks passed:

- The idle loop went round 24,093 times, through `stall.asm` each time.
- R0 to R15 and I0 to I4 held at every exit what they held at the entry.
- The suite ran once, and every test was timed.
- The old and the new reader wrote the same 32 samples, bit for bit, none 0 or not finite.
- Reply word 2 was the same on both pages, and all 134 halves rebuilt the words in memory.

The engine's step mode does not advance EMUCLK, so every time there is 0. The instrument gives the cycles.

The image: integrity 21/21, `boot_gate` from reset booted with 0 hits at `0x4011ea6a` (the fault reporter) and at `0x400cf678` (the uploader's refusal). Section 7 unpacks to 858,096 bytes.

## Read it

```
python tools/dn2stall.py --save out/stall_reading.json
```

Quit Transfer first. The tool reads reply word 2 until it has every half twice with the same value. It prints each pair's stall and each reader's cycles a sample.

## A selas bug this found

selas's 48-bit `Rn = <system register>` (Type 5a) puts the wrong code in the source field, for every register from PC up. `R0 = EMUCLK` came out as `R0 = LCNTR`. The compressed forms are right, and every committed object uses them, so no build that ran on the unit was affected.

`scripts/sharc_waverider_m3.fix_sysreg_read` writes the PRM's codes. They agree with digikit's decoder and with stock code. DN2 1.11 saves and restores MODE1 with 48-bit reads, and DT2 1.16 reads its cycle count as EMUCLK2, then EMUCLK. A 48-bit move of a system register in any other form is refused. `test/test_sharc_sysreg_fix.py` covers the fix. With it, all 37 other committed objects reassemble to the same bytes.
