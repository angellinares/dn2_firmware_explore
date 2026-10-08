# A cycle estimate for the SHARC, tuned by the instrument

digikit's runner executes the DSP code instruction by instruction and counts instructions. The ADSP-21569 spends cycles, and the two differ by what the pipeline and the memory make each instruction wait. The difference matters: the optimisations in `docs/waverider-dsp-opt.md` save stalls the instruction count can't see, and stock's render code runs at about 9 cycles an instruction on the instrument (`docs/sharc-load.md`).

`dnfw.sharccycles` estimates cycles from a run: it watches every step, counts the events the SHARC+ manuals price, and prices them with a cost table. The instrument's load readings tune the table.

```
python scripts/sharc_cycles.py estimate BUILD.syx [BUILD.syx ...]    # counts and estimate per case
python scripts/sharc_cycles.py fit data/sharc_cycles/measurements.json --free KEY ... [--write]
```

## What it counts

| Event (key) | Rule | Cost, and where it comes from |
|---|---|---|
| `instructions` | one per step | 1 |
| `dag_load_use` | an I register loaded from memory, then used to address (or jump) *d* instructions later | 4 − (*d* − 1) stall cycles; PRM Table 4-38 #1, 4-40 #3 |
| `dag_move_use` | the same, after `Ix = Rn` | not in the tables: counted on the load's scale, priced 1.0 until measured |
| `cjump_i6_use` | CJUMP or RFRAME, then I6/I7 used | 6 − (*d* − 1); PRM 4-40 #1-2 |
| `fwd_float` | a float compute or multiply, then a compute reading its result | 1; PRM 4-36 #1 |
| `fwd_fmul_to_fixed` | a float multiply, then a fixed-point ALU op reading it | 1 (guess: the table's number is lost in the PDF); 4-36 #3 |
| `anomaly_20000072` | a float compute into F0, then a single-operand compute | 1 (guess: the anomaly list says it stalls, not how long) |
| `br_*` | each branch's outcome through a modelled BTB (2 ways × 128 sets, 2-bit counters, masked inside hardware loops) | EE-375 Table 7 and PRM 4-39: right taken 2/0 (DB), wrong 11 or 11/9, unconditional 2/0 hit, 6/4 miss |
| `rti` | RTI | 7; PRM 4-40 |
| `loop_exit` | a hardware loop ends | 11; PRM 4-41 |
| `l1_same_block` | two data accesses to one L1 block in one instruction | 1; PRM 4-35 |
| `pm_conflict_miss` | a PM-bus data access missing the 32-entry conflict cache | 1; PRM 4-35 |
| `l2_*`, `ddr_*` | data accesses through a modelled 16 KB two-way cache, 64-byte lines, LRU (the stock start-up's size; PRM "L1 Cache Parameters") | hit 0, miss 30 (L2) and 100 (DDR): **guesses, to fit** |
| `smmr_rd`, `smmr_wr` | system MMR access | read 43 (EE-412 Table 6); write 1 (guess: posted) |
| `cmmr_*` | core MMR access | 2 (PRM 4-43: 0-4) |
| `icache_miss_*` | code fetched from L2 or DDR missing a 16 KB instruction cache | 30 / 100: guesses |

Every cost has a source in `src/dnfw/sharccycles/costs.py`: `prm`, `ee375`, `ee412`, `guess` or `fit`.

## What it doesn't see

- **Only the per-block routine.** The run is sw `0x1c2712` (frame unpack and machine dispatch), the part the runner executes. The instrument's load is the whole frame: interrupts, DMA, the FX, the idle loop. So compare differences between cases, never one total with the frame.
- **The cache's state between frames.** Each run starts with empty caches; on the instrument the previous frame warms them. `docs/sharc-load.md` found the same instructions costing 33 % or 11 % of a frame depending on what played before: that is this.
- **DMA traffic** competing for L1 blocks and the buses.
- **Steps the runner's fixups replace** (`emulated`) or skip: counted, not priced.
- **Rules not modelled:** dual forwarding to the multiplier, conditional-store-then-load, 64-bit float forwarding, the BTB's masking cases beyond "inside a hardware loop", MODE1 writes.

## Tuning it from the instrument

`tools/dn2sharc_load.py LABEL --idle` reads the SHARC's load (its idle task's share of each frame) through the USB probe. A frame is one 32-sample block, 666,667 cycles.

**Pair builds, not states.** The runner renders a Waverider voice whether or not a note was triggered: with and without the trigger, the reader filled one block every block (2026-10-08). The engine runs every voice each frame, as the instrument's flat stock load already said (`docs/sharc-load.md`). So "silent minus chord" is a small difference on both sides. The clean pair is two builds in the same state: scope2, opt1 and opt2 differ only in section 7, so everything the run doesn't model (the rest of the frame, the ColdFire, the FX) is the same on both sides and cancels.

A measurement file names each pair's two estimate cases and the two readings:

```json
{"free": ["dag_move_use"],
 "pairs": [
  {"name": "opt1 - scope2, chord", "a": "waverider-opt1-usbprobe:osc2+sub+noise", "b": "waverider-scope2-usbprobe:osc2+sub+noise",
   "cycles_a": 0.0, "cycles_b": 0.0, "scale": 4, "sigma": 1300}
 ]}
```

- `a` and `b` name `out/sharc_cycles/<build>.json` cases (from `estimate`). The counts are per block, and a block is a frame.
- `cycles_a`, `cycles_b`: the instrument's load × 666,667.
- `scale`: the runner plays one voice; a held four-note chord is 4.
- `sigma`: the readings' spread, in cycles (0.2 % of a frame is about 1,300).

The fit is non-negative least squares over the `free` keys, pulled toward their current costs (`--lam`), so a few pairs move only what they can tell apart. `--write` saves the result to `data/sharc_cycles/costs.json`, which `estimate` reads, each fitted cost recording the pairs it came from.

## First estimates: scope2, opt1, opt2 (2026-10-08)

`estimate` on the three builds in `00_Resources/02_Builds`, four blocks each, the costs above (nothing fitted yet). Per block (a frame), one voice, over scope2 in the same case:

| case | opt1: instructions | opt1: cycles | opt2: instructions | opt2: cycles |
|---|---|---|---|---|
| untriggered (`silent`) | 0 | −512 (−0.08 %) | −348 | −626 (−0.09 %) |
| osc 2 + sub + noise (the test patch) | −160 | −1,235 (−0.19 %) | −948 | −1,934 (−0.29 %) |

The whole run is about 1.56 cycles an instruction, by the model.

**Where opt1's estimate comes from:** −512 of its −1,235 cycles are `dag_move_use`, the reader's `I0 = Rn` four instructions before the read. That cost isn't in the manual's tables; it's priced like a load until measured. So **opt1 against scope2 measures it**: if the instrument shows opt1 no lower than the instruction savings (about 0.03 % of a frame per voice), a register move into a DAG register costs nothing, and O1 bought nothing.

**Where opt2's comes from:** the instructions (the hardware loop's counter and the paired loads), the reader's branch at the bottom of the software loop (`br_taken_ok`, 2 cycles a sample), less 11 cycles for the loop's exit. The osc-2 test inside the hardware loop falls through, so the branch predictor being masked there costs nothing in this patch.

**What the instrument should show,** with a four-note chord (×4 if all four voices render as the one does): opt1 about 0.7 % of a frame below scope2, opt2 about 1.2 %. The idle readings are steady to 0.1-0.3 %, so this needs several intervals per build. Fitting: `dag_move_use` from opt1 − scope2, then `br_taken_ok` and `loop_exit` from opt2 − opt1.

## First instrument readings and fit (2026-10-08)

The owner flashed scope2, opt1 and opt2 in turn on one saved project (track 1 Waverider, the test patch, 16 voices taken per the voice screen) and I read `tools/dn2sharc_load.py --idle`, 60 one-second intervals each:

| build | nothing playing | 16-note chord playing |
|---|---|---|
| scope2 | 63.1 % (63.0-63.2) | 63.1 % (63.0-63.2) |
| opt1 | 60.0 % (59.9-60.1) | 59.9 % (59.8-60.0) |
| opt2 | 56.5 % (56.4-56.6) | 57.2 % (57.1-57.3) |

- **All 16 voices render whether they sound or not** (scope2 and opt1 read the same both ways), so the estimate scales the runner's one voice by 16, not by the notes held.
- **opt1 − scope2: −3.1 points**, 20,667 cycles a frame. The estimate before any fit: 16 × 1,235 = 19,760. So `Ix = Rn` then a use stalls like a load does.
- **opt2 − opt1: −3.5 points**, 23,333 cycles; the estimate said 11,184.
- **The fit** (`data/sharc_cycles/measurements.json`, free `dag_move_use` and `br_taken_ok`): `dag_move_use` 1.05 (a register move into a DAG register costs what a load does: ~4 stalls at distance 1); `br_taken_ok` 8.2 cycles, not EE-375's 2. The software loop's branch back is not being predicted as the table assumes: a taken branch costs about a miss, whether because the BTB is masked there (the reader runs inside the voice loop) or disabled by this firmware. Unverified which.
- **This fit is not yet a test of the model.** Two independent differences, two free costs: it matches by construction. The next build measured against its estimate is the test.
- **Not explained: opt2 costs 0.7 points more playing than silent**, scope2 and opt1 nothing. The runner sees the same work either way (triggering adds 212 instructions a block in both opt1 and opt2), so it's timing on the chip. The hypothesis: the tables are in DDR behind the data cache; a chord reads more spread-out addresses than idle voices; opt1 issued each table read four instructions before its use, opt2's paired loads use the value in the next instruction, exposing a miss the earlier spacing hid. A build with O4 and O6 but opt1's tap order would test it.
