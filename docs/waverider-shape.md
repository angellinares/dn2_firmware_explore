# Waverider page 5, "Shape": the controls reserved for the sound features

Owner's order (2026-10-12): wavefolder, phase warp, ring and AM, osc 2 modulates osc 1, noise
into POS, formant or comb bank. The layout is option 4 of the layout page: four live knobs and
one typed shaper slot. This page reserves its eight records before any of the features land,
so a saved sound's record layout does not move when they do. Waverider is an alpha: a layout
that proves wrong in testing can still change.

## The page

| A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|
| FOLD | WARP | FM | NPOS | TYPE | AMT | P1 | P2 |

- **A to D** are live knobs: wave fold, phase warp, FM depth from osc 2 into osc 1, noise into POS.
- **E to H** are one shaper slot. TYPE picks Off, Ring or AM. Formant and Comb come later: the list
  grows without a new record. AMT is the shaper's amount, and P1 and P2 are its two parameters.
- **The scope** is drawn in the wave's place, as on page 4, so a fold is seen while it turns.
- **Values** store and p-lock like every other Waverider control. They ride stock records, as
  the sub and noise do. All but TYPE, P1 and P2 are LFO destinations.

## What plays (Waverider 0.3.0, 2026-10-16)

FOLD, TYPE, AMT, WARP and FM change the sound. NPOS, P1 and P2 do not, yet. `csrc/waverider/sharc/page5.asm`
and `csrc/waverider/sharc/phase.asm` do the work on the DSP. `dnfw.waverider.live` (`fold`, `shaper`,
`warp_phase`, `fm_offsets`, `read_phases`, `phase_sel`) is their model.

| Control | What the DSP does | Where |
|---|---|---|
| FOLD | A triangle fold of the two oscillators' mix, at one oscillator's peak (LEV 100, TRIM -11 dB), driven by 1 + 7 FOLD / 127 | after osc 2, before the sub |
| TYPE, AMT | Ring (osc 1 x osc 2) or AM (osc 2 sets osc 1's level), mixed in by AMT | after osc 2, before FOLD |
| WARP | Each oscillator reads its wave at a bent phase: two lines that meet where the wave's middle is read, the first with slope 1 + 9 WARP / 127 | before each reader call |
| FM | Osc 2 plays first. Its samples move osc 1's phase by o2 x FM / 127 / T cycles (one cycle at FM 127 and LEV2 100) | before osc 1's reader call |

- **How WARP and FM reach the reader:** `wr_p5_phase` writes each sample's phase to a buffer (PH). Copies of
  the two readers in phase.asm read PH in place of the running phase. The phase that the reader keeps for the
  next block does not change. DCLK's two reads of a crossfade take the same PH.
- **The mip level** under WARP and FM: the reader selects it for the fastest phase, (inc + 2 pi FM / 127 x
  inc2) x k1. The aim is that a warp's steep part and FM's peaks alias about as much as a plain note. We did
  not measure the aliasing.
- **FM's order:** osc 2 plays into its own buffer (FMB), then osc 1, then FMB is added. The mix is o1 + o2 as
  before. MOVE's random shapes then step osc 2 before osc 1 in a block. When both oscillators wrap in one
  block, the two random values change places.
- **Taming (Waverider 0.3.5, owner 2026-10-19: "go with taming"):** WARP and FM scale down at high notes,
  once a block, before the phases are written (`wr_ph_tame` in phase.asm, `live.tame`). The form is the
  eurorack reference's Tame (MIT; our own code): t = clamp(A - B f h, 0, 1)^3, with f the oscillator's
  increment in cycles, h the speed-up (WARP: k1; FM: 1 + 2 pi FM / 127), A = 8/7 and B = 16/7 (order 8).
  - WARP plays at v t, read between two table entries. Blending the slopes toward 1 was tried first and
    rejected: at t = 0.9 it dropped harmonics 5 and up by 3 to 10 dB, where a plain WARP 100 keeps them.
  - FM's depth goes to t c, with f from the faster of the two oscillators (osc 2's increment is read from
    the voice's own reader block).
  - The mip level is chosen from the untamed WARP and FM. With the tamed values it picks a brighter level
    and aliases more: WARP 127 at C6 measured -26 dB against -41 in the model study.
  - At t = 1 the code skips taming, so a note below the start sounds bit for bit as in 0.3.4.
  - Alias against 0.3.4 (`live.render_two`, both oscillators on Prim. at POS 0, the measure of the
    integrated-wavetable study): WARP 127 at C5 -37 dB (-33), C6 -43 (-31), F#6 -49 (-22), C7 -61 (-17).
    FM 127 at F#6 -36 (-19), C7 -68 (-16). Brightness (spectral centroid) under WARP 127: 0.94 at C5,
    0.70 at C6.
  - Cost: +75 instructions per voice and block with all of page 5 on at C4 (no taming), +115 at C7.
  - Checks: the shape gate's four tamed cases (G4, C6, C7) and `scripts/sharc_waverider_tame_voices.py`
    (WARP and FM 127 at C6 on all 16 voice slots) are bit for bit the model, and taming changes the samples.
- **FM and LEV2 (Waverider 0.3.6, a user via the owner, 2026-10-20: "modulator level and fm amount as 2 totally
  independent parameters"):** under FM, osc 2 plays into FMB at a fixed gain G, LEV 100 at the default TRIM
  (`wr_ph_gain`), so FM alone sets the depth, and osc 2 plays at LEV2 0 too. Osc 2's own gain (LEV2, TRIM and
  MOVE) over G is the ratio r it is mixed in at: b = o1 + r FMB (`wr_ph_fmmix`). r glides toward it by 1/32 a
  sample (about 3 ms), per voice at DM 0x2e6040, so a LEV2 step does not click. DCLK sees G as osc 2's gain while
  FM is on, so it fades table and POS jumps as before, and LEV2 changes go through r.
  - Three mixes, chosen once a block: while r glides, the loop above (4 instructions a sample more than a plain
    add); once r is within 2^-17 of its target, it takes the target and the mix is one multiply and an add
    (page5.asm); at LEV2 0, osc 2 is not added at all.
  - Cost (`scripts/sharc_waverider_p5_cost.py`, FM 64 at LEV2 100, per voice and block): +517 once r has settled
    (blocks 16 to 40; 0.3.5: +482), +609 while it glides (about 12 blocks after a LEV2 change). FM above 0 at LEV2 0
    runs osc 2's whole pass, about 2,800 instructions, in a case that was silent before.
  - The shaper (Ring, AM) still takes o2 from the mix, so it follows LEV2.
  - Checks: the shape gate's FM 127 cases at LEV2 0, at LEV2 50 and across a LEV2 jump from 100 to 0, bit for
    bit; `test_fm_plays_at_lev2_0_and_its_depth_does_not_follow_lev2` in the model.
- **WARP and FM at 0** skip their code: the reader is the reader of 0.2.0 and the voice is bit for bit the
  same.
- **Checks:** `scripts/sharc_waverider_shape.py` runs 21 cases in digikit's SHARC runner, and each is bit for bit the
  model. `test/test_waverider_shape.py` checks the model.
- **Cost** (`scripts/sharc_waverider_p5_cost.py`, instructions per voice and block): FOLD 369, Ring 363, AM 431,
  WARP 710, FM 482, WARP and FM 1,138. All of AM, FOLD, WARP and FM: 1,898, about 4.6 % of a block on 16 voices.
  With page 5 at 0 the voice costs 87 more than in 0.2.0: the read of WARP's word and the tests before each reader call.
- **Plain tables:** with DNFW_WAVERIDER_NOMIP=1, the WARP and FM cases also pass bit for bit. That run plays
  phase.asm's copy of the plain reader, which a pool table uses before build3 has its levels.
- **NPOS is out, for now** (owner, 2026-10-16: the load must stay near 70 % and the factory machines' load).
  Branch `wip/waverider-npos` has it: a random POS offset per block, before MPOS. Above NPOS 46, DCLK crossfades
  its jumps. At NPOS 64 with both oscillators at POS 64, that adds 5,557: a second table read on each oscillator
  in almost every block (24 blocks, 2026-10-16). It comes back once its load is balanced.
- **Defaults, measured 2026-10-16 in the emulator:** when you select Waverider, MACHINE SEL sets sound slots 58
  to 64 to 0. So every Waverider sound since 0.1.0 has FOLD, NPOS and TYPE at 0. Slot 48 (AMT, the MAST record) keeps
  0x4000, so AMT reads 64. With TYPE Off, AMT changes nothing.
- **Not measured yet:** whether the ColdFire adds MAST, and so AMT, to the note. The DSP side does not
  (`scripts/sharc_waverider_inert.py`). The instrument test turns AMT with TYPE Off and listens for a pitch change.

## Where the eight records sit

A WaveTone-type sound has sound slots 25 to 64. Waverider uses 238 to 260 (slots 25 to 47) and
FM Tone's 227 to 234 (slots 50 to 57, page 3). The rest:

| Control | Record | Sound slot | Borrowed from |
|---|---|---|---|
| FOLD | 208 | 58 | FM Tone |
| WARP | 209 | 59 | FM Tone |
| FM | 210 | 60 | FM Tone |
| NPOS | 211 | 61 | FM Tone |
| TYPE | 235 | 62 | FM Tone |
| P2 | 236 | 63 | FM Tone |
| P1 | 237 | 64 | FM Tone |
| AMT | 261 | 48 | WaveTone's master tuning (MAST) |

Record 262 (FINE, slot 49) stays free for a later control.

**Why MAST is free:** the Waverider voice never reads frame parameters 48, 49 or 58 to 64. The
DSP's render is bit-identical with each at its default and at its extremes, and TUN1 (parameter
25) as the control does change it (`scripts/sharc_waverider_inert.py`, 2026-10-12). Not checked:
whether the ColdFire folds MAST into the note before the frame is built.

**The stock answer table** (`param_set_slot_to_id`, `0x400dc02a`) gives, for FM Tone, slots 58
to 61 the ids 208 to 211 and 62 to 64 the ids 235 to 237 (read in the emulator, 2026-10-12).
`wr_slot_id` answers these for a Waverider sound, as it does 227 to 234 for page 3.

## What is still open

- **Defaults of an old sound.** A sound created before this page holds FM Tone's stock values
  in slots 58 to 61 (0x4000, read from the live frame), so FOLD, WARP, FM and NPOS read 64 on
  it. A feature wired to them must not read 64 as "on", or must re-default them. FOLD, WARP and FM
  play at 64 on such a sound. The manual tells the user to set them to 0. A new Waverider sound has
  them at 0 (MACHINE SEL, measured above).
- **The labels** are fixed text. A label that follows TYPE needs a knob label that follows a
  value, which has not been shown to be possible.
- **Changing TYPE under a held note** must crossfade, or it clicks.
- **How many SYN pages a machine can show:** five now (page count `wr_count`); more is
  unmeasured.

## Where it is in the code

- `src/dnfw/waverider/pages.py`: `SHAPE`, `SHAPE_LABELS`, `SHAPE_RUNS`, `SHAPE_PLAIN`,
  `PAGES[4]`, `slot_id_runs()` (the `wr_slot_id` search), `C_LOAD` moved to `LOAD + 0x1000`
  (the pages assembly is 3,484 B).
- `csrc/waverider/page.c`: `SHAPE_PAGE` draws the scope.
- Generated: `src/dnfw/mods/waverider_code.json` (`scripts/gen_waverider_code.py`).

## LFO destinations (measured 2026-10-12, emulator, the LFO's DEST list on a Waverider track)

The list opens with a tap on DEST and shows two groups both headed SYN: first FM Tone's
records (Wave Fold, Phase Warp, FM Depth, Noise to Pos, Sub Level, Sub Octave, Sub Wave, Sub
Source, Noise Level, Noise Type, Noise Colour, Noise Decay), then WaveTone's (Osc1 Tune, Osc1
Position, ... Osc2 M.Sync, Shaper P2, Level Trim). The order inside a group is the record id,
not the page.

**Shaper Type, Shaper Amount and Shaper P1 (records 235, 236, 237) are not in the list.**
Records 235 to 237 hold zero in the 60-byte record's word at +36 (all of ours that do appear
hold 0x1e00; FM Tone's 226, which is not a destination either, holds zero too). So TYPE, AMT
and P1 cannot be LFO destinations as the records stand; P2 (261, MAST) and the four live knobs
can. Whether they can be p-locked is what the instrument says (owner's test, 2026-10-12).
Changing the field would change FM Tone's own parameters 235 to 237 as well, so it is not done.
