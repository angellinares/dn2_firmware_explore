# LFO4 build plan: saved per preset (route b)

**Owner's decision, 2026-09-15: grow the sound object so LFO4 is saved with the
preset.** This file is the concrete plan, and it opens with the finding that
shapes all of it.

## You cannot grow the strides. So "grow the sound object" is done by extension, not by widening.

The obvious reading of "grow the sound object" is: make the 2,388-byte in-RAM
sound object bigger, or widen the 202-byte per-track value array, so LFO4's eight
parameters become slots inside them. **Measured, that is not buildable.** Each
stride is a bare immediate repeated across the image:

| Constant | Meaning | Sites | Functions |
|---|---|---|---|
| `#2388` (`0x954`) | in-RAM sound object stride | 29 | 21 |
| `#202` | per-track runtime value-array stride | 17 | 16 |
| `#359` | stored sound size | 21 | 21 |
| `#153` | per-track descriptor-record stride | 6 | 6 |
| `#101` / `#100` | value-array element count and loop bound | 500+ | 100+ |

Changing a stride means finding and correcting every one of those, and `#100`
/ `#101` are ordinary small constants used all over for unrelated things — there
is no reliable way to edit only the array ones. **A widening edit would corrupt
the image.** `docs/lfo4-slot-plan.md` §3 reached this for the RAM object; the
survey above extends it to every stride.

**So the design is forced, and it is the same one §3 chose:** LFO4's eight values
live in **extension arrays keyed by the same index the stock code already
computes**, and nothing moves. "Saved per preset" is then achieved not by
widening the stored sound but by **routing LFO4's eight values through the 4th
LFO slot the stored format already reserves** (Elektron left it; DNX confirms).

## The data path, and the four places LFO4's values must appear

LFO4's eight parameters have to exist at four layers, each an extension keyed by
an index stock code already has:

| Layer | Where LFO1–3 live | Where LFO4 goes | Keyed by |
|---|---|---|---|
| **Stored sound** (359 B) | LFO block, reserved 4th slot present | the reserved slot | — (DNX) |
| **In-RAM sound object** (2,388 B) | value field `+0x14 + 2·slot` | `ext_obj[obj][0..7]`, 2,048 B | object index 0..127 (`0x4003e440`) |
| **Runtime per-track value array** (202 B) | words 1–24 | `ext_trk[track][0..7]`, 256 B | track 0..15 |
| **Tick state** (40 B × 3) | `0x4463fc18` + `0x4463f498` | grow to ×4 | track, LFO |

The tick reads LFO4's parameters from the runtime array, applies into it, and the
mirror/serialize path carries the values between the runtime array, the RAM
object, and the stored sound.

## The hooks, located

Every function that has to change is now named. None requires a stride edit.

**1. The generator — both ticks** (`docs/lfo4-distance.md`).
`0x40137726` and `0x401373dc`. **Check 1 (below in `lfo4-distance.md`) shrank
this:** the three stock state arrays are wall-to-wall in BSS with no headroom, so
instead of widening them the tick runs an **appended fourth iteration** over
parallel extension arrays — `ext_state[16][40]` and `ext_trk[16][8]` in the
25 MB. The stock arrays do not move and the `#120`/`0x780` strides do not change;
the loop just does one more pass, reading the fourth LFO's state and params from
the extension. State arrays are referenced only by their getter and tick.

**2. The mirror — control → runtime.** `0x400db092` (the parameter-set apply,
stride 202) and `Sound::updateMirror` populate the runtime value array from the
RAM object. A cave copies LFO4's eight from `ext_obj[obj]` into `ext_trk[track]`
alongside.

**3. The serializers — RAM object ↔ stored sound, both found:**

- **`0x400dde44` — deserialize** (stored → RAM): writes the magic
  `0xBE...` , copies the value header, then loops **stride 359 source / 1163
  dest** calling `0x400dd6a6` per track. Hook: also read the stored 4th-LFO slot
  into `ext_obj[obj]`.
- **`0x400ddc52` — serialize** (RAM → stored): checks version 4 and the magic at
  `+10411`, clamps and copies the value array out. Hook: also write
  `ext_obj[obj]` into the stored 4th-LFO slot.

This is the pair that makes LFO4 **saved**: without them the extension arrays are
runtime-only (route a); with them LFO4 round-trips through the preset.

**4. Enumeration, records, destination masks, p-lock maps** — **already done or a
data edit** (`docs/parameter-set-tables.md`, `docs/modulation-mask.md`,
`docs/lfo4-slot-plan.md`, `scripts/build_lfo4_test.py`).

**5. Page id + UI page-view** — **unbuilt**, and now the largest remaining piece.
The page-id renumber is paused (needs the runtime classifier found); the
`[MOD]` page-view is not started.

## The build order

Each step is verifiable before the next, and the early ones are route (a) — a
running LFO4 — so the generator is proven before the storage work.

1. **Two static checks** (`docs/lfo4-distance.md`): 640-byte BSS headroom after
   the two state arrays; identify `0x401373dc`'s consumer.
2. **Extension arrays + tick cave** → flash a **running track-level LFO4** that
   modulates a destination. Proves the generator. (route a)
3. **Mirror cave** → LFO4 follows the loaded sound in RAM.
4. **Serialize/deserialize hooks** at `0x400dde44` / `0x400ddc52` → **LFO4 saved
   and restored per preset.** Verify by saving on the instrument and reading the
   sound back with DNX: the reserved slot carries LFO4's eight values.
5. **Page id + page-view** → LFO4 has its own `[MOD]` page.

Steps 1–2 are close and need no new reverse engineering. Steps 3–4 are the
"saved per preset" work the owner asked for, and every function is now located.
Step 5 is the open UI/page-id job, unchanged.

## What is still owed before step 4

- The exact **layout of the stored 4th-LFO slot** — DNX's domain; ask which
  bytes of the 359 carry the reserved LFO4 fields, so the serialize hooks write
  the right offsets. **Asked of DNX when step 4 is reached.**
- Confirmation that `0x400dde44`/`0x400ddc52` are the **only** serialize path for
  a sound (there may be a separate kit or project path). Static, cheap.
