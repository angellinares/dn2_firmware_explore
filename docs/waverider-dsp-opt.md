# Waverider's DSP code, optimised: opt1 and opt2 (2026-10-08)

Two test builds from the SHARC study (https://claude.ai/artifact/MUeWU36DQsQ3RqZCnjwWYz), for the owner to compare on the instrument against `scope2`. Every change keeps the arithmetic in the same order, so the sound is bit-identical: the runner gates compare every sample with the reference.

| build | branch | on top of | what changes |
|---|---|---|---|
| `waverider-scope2-usbprobe` | `feature/waverider-scope` | | the control |
| `waverider-opt1-usbprobe` | `feature/waverider-dsp-opt1` | scope2 | O1, O2, O3: no instruction form stock doesn't use |
| `waverider-opt2-usbprobe` | `feature/waverider-dsp-opt2` | opt1 | O4, O5, O6: eight encodings stock never uses (the table below) |

## opt1: three changes in forms the stock firmware uses

- **O1 (study A3): the reader's table taps without the index-load stall.**
  - Before, each of the four taps was `I0 = Rn`, then `Rm = DM(0, I0)` at once. The SHARC+ PRM (table 4-38) gives a DAG register's load-to-use 4 stall cycles; whether a move from a data register costs as much isn't in the tables.
  - Now each address goes into I0 or I1 at least four instructions before the read through it: R4..R7 hold the four addresses until the samples replace them. I1 is free in the reader (dclk.asm reloads it after each call; machine9_live.asm doesn't rely on it).
  - The runner counts instructions, not cycles, so this saves nothing there by design: the instrument's load is its only measure.
- **O2 (A1): the sub and noise loops count in registers.** Each loop counted its samples in a memory word (load, constant, subtract, store each sample). Now the sub loop counts in R8 and the noise loop in R10, registers neither loop uses, with `Rn = Rn - 1` (the stock `dec`, whose exact encoding stock has).
- **O3 (A10): the two per-sample anomaly-20000072 sites.** A float compute into F0, then a single-operand compute, stalls on this silicon (both revisions). noise.asm now floats `w` into F1 and copies it to R0; sub.asm puts the `R12 = 1` data move between the two.

**Tried and dropped:** the reader's count in R12, by turning its four `ASHIFT … BY R12` into immediates. selas mis-encodes `ASHIFT` by an immediate (`docs/sharc-selache.md`): the runner stopped on it, though the decode check had passed.

## opt2: three more, which need the silicon to prove them

- **O4 (A4): the reader's sample loop as a hardware loop**, `LCNTR = R0, DO wr5_last UNTIL LCE`.
  - E2-active (selas writes mode 0), the kind the PRM makes the default and stock uses for loops with a branch in the body (the osc-2 mix test stays inside).
  - **The PRM requires a hardware loop's last 11 instructions to be 48-bit ISA, never compressed VISA** (4-42). Stock follows it: 287 of its 289 DO loops end in 11 full-width instructions (the two others decode as nonsense trip counts: data). The loop's tail sits under `.NOCOMPRESS`; selas in fact writes the whole body at full width. The M5-era DO loop (2026-09) had a compressed tail: in hindsight it broke this rule, whatever else was wrong then.
  - The phase step moves to the loop's last instruction (it is used only at the next iteration's start).
- **O5 (A5): four loads paired with independent computes** in one Type-4a instruction (`compute ; Rn = DM(k, Ia)`): f0's row with `R1 = R9 + R13`, f1's row with `R5 = R2 + R1` (the add reads R2 before the load replaces it, as stock's `R0 = R8 * R2; R2 = DM(I4 + 2)` does), and the four taps with the shift and FLOAT that follow the previous ones.
- **O6 (A2): the sub loop unswitched by WAVE.** WAVE can't change within a block, but every sample walked the compare chain (up to three compares and branches). Now WAVE is tested once and each shape has its own loop; SQR's and PLS's loops skip `h`, which they never used. sub.asm grows to 666 B of its 1 KB span. (The study's A2 proper, the reader's mix test, needs a second copy of the reader's loop: its span has 110 B left after O4.)

### What opt2 uses that stock doesn't

The encoding audit (`scripts/sharc_encoding_audit.py`, sharcdb databases of stock 1.11 and of each build's section 7) counts, per instruction, whether stock has the same opcode (the form plus the mnemonic, data registers masked, DAG registers kept). The baseline (scope2) has 50 such instructions, all of which ran on the instrument for weeks. opt1 has the same 50. opt2 adds 12:

| instruction | form | why it's unseen | read |
|---|---|---|---|
| `I0 = R4`, `I1 = R5`, `I0 = R6`, `I1 = R7` | 5a (48-bit) | stock writes I-registers from data registers in the 32-bit 5b form only; inside the DO loop selas writes everything at 48 bits | **unproven** |
| `R2 = R2 - R3 ; R4 = DM(I0 + 0)`, `R4 = LSHIFT R4 BY R2 ; R5 = DM(I1 + 0)`, `F4 = FLOAT R4 BY R8 ; R6 = DM(I0 + 0)`, `F5 = FLOAT R5 BY R8 ; R7 = DM(I1 + 0)` | 4a | stock pairs through I0 and I1 with other offsets (`DM(I1 + 7)`) or post-modify | **unproven** |
| `R4..R7 = ASHIFT Rn BY R12` | 2a (48-bit) | stock uses this compute standalone only in its 16-bit form | **checked**: the compute field (`0x20444C`: shifter `0x200000`, ASHIFT `0x4000`, the registers) is the one stock's 48-bit pairs carry (`R12 = ashift(R2, R0)` = `…204C20`) |

So **eight encodings in opt2 have never run on this DSP**. If opt2 stops the DSP (silence from the first note, everything else working: the M5 failure's shape), these eight are the suspects, and opt1 stands alone.

## Gates

| | opt1 | opt2 |
|---|---|---|
| decode (digikit and selmap read every instruction as its source) | PASS | PASS |
| encoding audit: opcodes stock never uses | 50 (= baseline) | 62 (the table above) |
| every branch on an instruction boundary | yes (3 go to stock, as before) | yes |
| `sharc_waverider_sub.py` | 7/7 | 7/7 |
| `sharc_waverider_noise.py` | 5/5 | 5/5 |
| `sharc_waverider_dclk_hold.py` | 4/4 | 4/4 |
| `sharc_waverider_m5.py` (bit for bit, the whole Waverider path) | PASS | PASS |
| build: integrity 21/21, boot_gate, check_coldfire, projects, pool 10/10, modinfo, wavepool | all pass | all pass |

## Cost

The runner counts instructions (`scripts/sharc_waverider_p3_cost.py`, per voice and block):

| path | scope2 | opt1 | opt2 |
|---|---|---|---|
| sub SIN | +742 | +678 | +586 |
| noise WHT, DEC Inf | +905 | +809 | +809 |
| noise PNK, DEC 40 | +2,022 | +1,926 | +1,926 |
| both | +2,764 | +2,604 | +2,512 |

The control row (a Waverider voice on osc 1, sub and noise off) is the whole block: 624,836 instructions in opt1, 623,444 in opt2 (−1,392: the reader's hardware loop and pairs).

The reader, per sample per oscillator (instructions in the loop, read from the source): 60 in scope2 and opt1 (O1 moves instructions, it doesn't remove any), 49 in opt2 (O4 removes the counter, O5 folds four loads into computes), plus the DO's set-up and its termination once a block (counted from the sources, every line of the loop body, the osc-2 add included).

## On the instrument: the comparison

Instructions aren't cycles: O1 and O4 save stalls and branch flushes the runner doesn't model. The measure is the SHARC's whole load from its idle task (`tools/dn2sharc_load.py LABEL --idle`, reply word 1), the same on each build:

1. A NEW project. Track 1 Waverider; page 2 LEV 100 (osc 2 on); page 3 SUB 100 SIN, NOIS 100 PNK, DEC 40; voices as the track allows.
2. Nothing playing: `silent`. Then hold a chord of four notes on track 1: `chord`.
3. The same on each of scope2, opt1, opt2, one after another; the difference `chord - silent` is Waverider's share.

A pass: opt1 and opt2 sound exactly as scope2 (same patch, same notes), and their `chord - silent` is lower. A failure: any difference in sound, a stuck or silent DSP, or a load no lower than scope2's.
