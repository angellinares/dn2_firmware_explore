# Waverider: the wavetable page of the PRESET/KIT menu

Page 2 of PRESET/KIT, layout A of the design review (the owner, 2026-10-06): a copy of the
PRESET column for wavetables, with the pool at a glance on the right. The pool lists it
edits are in `docs/for-dnx-waverider-pool.md`. **Status: built and checked in the emulator,
2026-10-06. Not on the instrument yet.**

## On the panel

| press | does |
|---|---|
| PRESET/KIT | page 1, stock |
| PRESET/KIT again | page 2: WAVETABLE (LOAD, MANAGE, POOL) and POOL (in pool, free, +Drive) |
| PRESET/KIT or NO on page 2 | closes the menu, as stock does; the next open is page 1 |
| UP / DOWN | the highlighted item |
| YES | opens its list |
| in a list: NO | back to page 2 |
| in MANAGE or POOL: YES | ticks or unticks the highlighted row (a check mark at its left) and moves down one, as stock's preset manager does |
| in a list: RIGHT | the list's operations in a side panel on the right, as stock's PRESET OPERATIONS; UP/DOWN choose, YES runs, NO or LEFT closes. They act on the ticked rows, or on the highlighted row when none is ticked |
| in a list: LEFT | nothing yet (stock's SORTING menu) |

**Since 2026-10-07 (owner: "behave like stock"):** ticks and the RIGHT panel, in place of the FUNC popup. Measured on stock 1.11 in the emulator, PRESET > MANAGE: YES ticks and moves down; RIGHT opens COPY TO BANK, EDIT TAGS, DELETE, SELECT ALL, DESELECT ALL, TOGGLE, SEND SYSEX on the right half, and the highlighted row is outlined. The tick is stock's: 4 × 3 pixels, before the row's text.

The lists:
- **LOAD**: this project's pool, slots 001..128. YES puts the slot on the active track's
  TBL, for the oscillator of the SYN page last shown (TBL1 from pages 1 and 3, TBL2 from
  page 2). On a track that isn't Waverider, or an empty slot, it says so and changes
  nothing. RIGHT: LOAD TO TBL1, LOAD TO TBL2.
- **MANAGE**: every table on the +Drive, a `+` on those in this project's pool. RIGHT: ADD TO
  POOL (every ticked table, in row order, each into the first empty slot left, a cleared one
  first, in one write: "3 ADDED TO THE POOL";
  ALREADY IN THE POOL; POOL FULL: n ADDED), DELETE (asked first: DELETE n? YES / NO), SELECT
  ALL, DESELECT ALL.
- **POOL**: this project's pool, as LOAD. RIGHT: CLEAR SLOT (every ticked slot, in one
  write), SELECT ALL, DESELECT ALL.

A slot whose table was deleted reads **MISSING**: it plays Prim., isn't free, LOAD refuses
it, and only CLEAR SLOT frees it. DELETE changes no pool list, so a later ADD TO POOL can't
fill the slot under sounds still pointing at it.

A result worth saying replaces the list's title until the next key.

## How it is built

The stock `PresetKitMenuView` (vtable `0x401e6da0`) stays the view. Three of its vtable
slots point at our code, which falls through to stock on page 1:

| slot | stock | ours | why |
|---|---|---|---|
| `0x401e6db0` | `0x4008c78e(view, event)`, the key handler | `wr_wt_key` | stock answers the PRESET/KIT release by closing; ours opens page 2 instead |
| `0x401e6db8` | `0x4008a5ec(view, canvas)`, the redraw | `wr_wt_draw` | page 2 and its lists |
| `0x401e6e54` | `0x4008abec`, the LedHandler thunk, every frame while open | `wr_wt_led_hook` | a gap in it means the menu was closed, so the next open is page 1 |

Measured with panel_drive (`--regs-at`): the key handler gets a press and a release per tap,
and not the release of the press that opened the menu; the redraw runs at open and after
each key that calls `0x4011c7ba(view)`; the LED thunk runs once a frame.

The firmware's own routines and constants used, all read from the stock page's redraw:

| what | address |
|---|---|
| key code, press, release of an event | `0x40116018`, `0x40116070`, `0x40116040` |
| redraw the view (as stock after a cursor move) | `0x4011c7ba(view)` |
| clear the canvas | `0x40114d94(canvas, 0, 0)` |
| text | `0x4011545c(canvas, font, x, y, flags, fmt, ...)`, flags 2 = centred on x |
| vertical line | `0x40114066(canvas, x, y0, y1, 1)` |
| rectangle | `0x40114954(canvas, x0, y0, x1, y1, mode)`: border and inside; -1 inverts, 1 sets, 0 clears |
| icon | `0x401157fc(canvas, bitmap, x, y, 0)`: LOAD `0x44646464`, MANAGE `0x44646378`, POOL `0x44646a90` |
| fonts | the menu's `0x44507ef8`; the lists' rows `0x44507ee0` (the stock list's) |
| the stock rows | text at y 44 / 31 / 18 / 6, x 22; icons at x 9; highlight x 7..58, y 41..51 / 28..38 / 15..25 / 3..13; the right column x 70..121 |

Coordinates count up from the bottom edge. The panel codes: PRESET/KIT 7, YES 10, UP 11,
NO 12, LEFT 13, DOWN 14, RIGHT 15, FUNC 17 (LEFT and RIGHT: opened stock's SORTING and
OPERATIONS panels in the emulator).

**Drawing one pixel:** FILL (`0x40114954`) grows a one-pixel rectangle in both its set and
its invert modes, so a tick drawn with it came out 3 × 3 a pixel. Single pixels go through
`0x40113b90` (canvas, x, y, on), as page.c draws its modulation dots.

The code, one subject each, in the +Drive chunk (`dnfw.waverider.drive`):
- `csrc/waverider/wtmenu.c`: page 2's menu and where its keys go;
- `csrc/waverider/wtlist.c`: the lists' rows, keys and drawing;
- `csrc/waverider/wtedit.c`: what the page changes. Pool edits start from what plays, so a
  project on the automatic pool keeps its tables when it first gets a list, and write
  record 0 in one sector (generation + 1). DELETE changes no pool list. LOAD
  writes the kit sound's TBL value word (slot 27 or 33, coarse = pool index + 2).
  `page.c` leaves the SYN page's oscillator in `wr_events.shown_osc` for it.

## Checked (emulator, 2026-10-06)

Each step with panel_drive frames on a card from `scripts/emu_waverider_pool.py`'s store
(three tables, one 32 waves wide), with and without a pool list:
- page 2 opens, the cursor moves, PRESET/KIT closes, the next open is page 1;
- the lists open, scroll and close; the counts follow the edits;
- ADD TO POOL, CLEAR SLOT, ALREADY IN THE POOL;
- DELETE: NO keeps; YES deletes; record 0 still `[3, 5, 0]` gen 1 (read over the Data
  API); the slot reads MISSING, FREE 124, LOAD refuses it, CLEAR SLOT frees it (FREE 125);
- LOAD: TBL1 `0x0300` -> `0x0400` for slot 003; on an FM track nothing changes.

`boot_gate` booted at each step; the `/wavepool` and rename tests still pass.

## Not built yet

- RENAME (needs the stock naming screen).
- The active track's table in the right column (T1 TBL), as the mockup shows.
- A mark on tables the DSP can't play (not 16 x 512): listed, and they play Prim.
- The stock list's checkered scrollbar track.
- **Not measured:** whether anything waits for a change event after LOAD writes the TBL
  value (stock writes one, SoundParamChangedInfo, when it resets a parameter). The SYN page,
  the frame to the DSP and SAVE read the value itself; whether the working copy is saved with
  it without another edit is the instrument test's to show.
