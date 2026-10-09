"""Waverider's DSP half: every edit Milestone 5 makes to section 7 (the SHARC boot
stream), applied from committed artefacts. `docs/waverider-m5-dsp.md` has the
evidence for each.

    section7(stock) -> the modified boot stream
    section7_idle_only(stock) -> stock plus the idle-time stub alone (patch 4), for
                       measuring the stock engine with nothing of Waverider in it
    placements()    -> what goes where, for a report or a mod's extents

**What it does to DN2 1.11's section 7:**

1. **Adds boot blocks** in L1 block 1's free tail, byte `0x2dd600..0x2e7000`
   (Milestone 5c; M5 used L1 block 2, which silenced the instrument --
   `docs/waverider-dsp-silence.md`): `reader_m5.asm` (sw `0x16eb00`),
   `machine5_live.asm` (sw `0x16ed00`), a zeroed state block (save area, counters,
   16 reader blocks), the 129-entry increment table, the wavetable directory, and
   two original 16 x 512 int16 tables. Every payload is zero-padded to the next
   span, so the region is written end to end: each code span has >= 64 bytes of
   zeros (NOPs) after it and no byte of the region is left unwritten.
2. **Enters the type-5 loop**: the two instructions at sw `0x1c9448` (after the
   Swarmer render loop in `sw 0x1c8ef1`) become `JUMP 0x16f600` and a 16-bit NOP.
   `block_count.asm` there counts the block into reply word 2 and jumps to the loop
   at `0x16ed00`, which re-executes the two instructions before it jumps back to
   `0x1c944c`. (Until the block counter, the JUMP went straight to `0x16ed00`.)
3. **Lets a type-5 frame through**: the frame-nibble -> machine-type lookup
   `0x25d748[5]` becomes 5 (stock 0, FM Tone).
4. **Times the idle task** (`idle_load.asm`, sw `0x16f500`): the back edge of
   FreeRTOS's idle loop, `jump (pc,-0x10)` at sw `0xb88abb` in L2, becomes
   `JUMP 0x16f500`; the stub adds the idle task's own cycles to a running total in
   reply word 1 and jumps back to `0xb88aab`. The SHARC's load is then
   1 - idle / elapsed (`docs/sharc-load.md`).

**What it does not do, on purpose:**

- It does **not** raise `min(R2, 4)` at `0x1c294c` (Milestones 3-4 did). Measured:
  that clamp's input is the frame's per-track field at offset `84 + 2t`, not the
  machine type, which reaches the record through the lookup alone.
- It does **not** touch the per-type setup table `0x8052db90`: the dispatch indexes
  it only after `compu(type, 5)`, so type 5 already takes the no-setup arm that
  MIDI's entry `[4]` also points to (`0x1c90d4`).

Every stock byte it replaces is checked first, and every added span is checked to
lie outside every block of the stock stream (loaded or filled). This module is pure:
bytes in, bytes out.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import struct

from ..image import bootstream, sharc_object
from . import harmonics, live, mip, reduce, table3, testtable
from . import render as reference

STOCK_SHA256 = "336e340aa0cdcd34e314cfa44849f709a3134f6bd4cd57dfc7e15702c83115e2"
LOAD_ALIAS = 0x28000000          # boot-stream load address = LOAD_ALIAS + DM byte address
CODE = pathlib.Path(__file__).with_name("sharc_code.json")

# L1 block 1's free tail (DM byte addresses). Block 1 is 0x2c0000..0x2f0000; the
# stock stream's last byte in it is 0x2dd52c, and the startup enables the DM cache,
# which is carved from the top of block 1 (16 KB at size code 0, the size the
# startup writes; see docs/waverider-dsp-silence.md). REGION ends 36 KB below the
# block's top, so it stays clear of a 16 KB or a 32 KB DM cache.
REGION = (0x2DD600, 0x2E7000)
STOCK_BLOCK1_END = 0x2DD52C
DM_CACHE_32K = 0x2E8000                      # the lowest byte a 32 KB DM cache would own
CODE_SPAN = 0x400                            # each code object is padded to this
READER_DM = 0x2DD600
LOOP_DM = 0x2DDA00
READER_SW = READER_DM // 2                   # 0x16eb00
LOOP_SW = LOOP_DM // 2                       # 0x16ed00
STATE_DM, STATE_BYTES = 0x2DDE00, 0x400      # save area, counters, 16 reader blocks
READER_BLOCKS_DM, READER_BLOCK_BYTES = 0x2DDF00, 32
INC_TABLE_DM = 0x2DE200
DIRECTORY_DM = 0x2DE600
DIRECTORY_MAGIC = 0x57525431                 # 'WRT1'
# The tables live in the SHARC's DDR, not in L1 (2026-10-03): 32 KB of L1's 43 KB free
# tail is better spent on code and per-voice state, and tables loaded from the +Drive
# at run time will live in DDR anyway. The stock image's last DDR byte is 0x8052fbe0
# (`dnfw ldr`); no aligned data word and no code immediate names DDR above it (the
# scan in docs/waverider-m10-move.md, "The tables in DDR"). DDR_REGION sits 720 KB
# above it and below 0x80a00000, where the Digitakt II, on the same board, keeps its
# sample pool. DDR has no 0x28 load alias: a block's target is the address itself.
STOCK_DDR_END = 0x8052FBE0
DDR_REGION = (0x80600000, 0x80A00000)
TABLE_BYTES = 0x4000                         # 16 frames x 512 int16 (a pool table, without levels)
# The baked tables are mip-mapped (dnfw.waverider.mip): eight levels, 65,024 B each, 64 KB
# apart. TABLES_AT is where their bytes load; TABLES_DM what the directory (and so the reader
# block) holds: the address with bit 0 set, which tells reader_mip.asm to pick a level.
# hermite2's guarded rows (mip.row_points) make a table 65,792 B: its slots are 68 KB apart
MIP_TABLE_BYTES = 0x11000 if mip.guarded() else 0x10000
MIP_FLAG = 1
TABLES_AT = (0x80600000, 0x80600000 + MIP_TABLE_BYTES)
# DNFW_WAVERIDER_NOMIP=1 (the comparison set's control, 2026-10-08): the tables load plain
# (16 KB, no levels) and the directory holds their addresses without the flag, so the reader
# plays them as it plays a pool table: level 0, today's reader on the same table
NOMIP = os.environ.get("DNFW_WAVERIDER_NOMIP", "") == "1"
TABLES_DM = tuple(a | (0 if NOMIP else MIP_FLAG) for a in TABLES_AT)

IDLE_DM = 0x2DEA00                           # idle_load.asm, in the gap before table 0
IDLE_SW = IDLE_DM // 2                       # 0x16f500
IDLE_STATE_DM = 0x2DE100                     # its save area and counters (state block tail)
COUNT_DM = 0x2DEC00                          # block_count.asm, after idle_load.asm
COUNT_SW = COUNT_DM // 2                     # 0x16f600: the entry JUMP's target
EMARK_DM = 0x2DED00                          # entry_mark.asm: EMUCLK as the handler calls 0x1c2712
EMARK_SW = EMARK_DM // 2                     # 0x16f680
MOD_DM = 0x2DEE00                            # modulator.asm (M10a): MOVE, the per-oscillator modulator
MOD_SW = MOD_DM // 2                         # 0x16f700
# the directory block's tail (M9b/M10a): what the loop and the modulator keep there
MOVE_PHASES_DM = 0x2DE700                    # 16 voices x 2 oscillators, a u32 phase each
MOVE_OFFSETS_DM = 0x2DE780                   # per oscillator, 32 bytes: frame offsets of RATE MPOS MLEV MOVE TRIG PRST SYNC
MOVE_RATE_DM = 0x2DE7D8                      # F[0..9], the rate table
SHAPES_DM = 0x2DF000                         # shapes.asm (M10b-4): MOVE's eleven shapes, in L1 the tables left
SHAPES_SW = SHAPES_DM // 2                   # 0x16f800
MOVE_RANDOM_DM = 0x2DF400                    # 16 voices x 2 oscillators: the random shapes' (a, b), a u32 each
MOVE_RANDOM_GEN_DM = 0x2DF500                # their generator's state
MOVE_RANDOM_BYTES = 0x200                    # both, zeros at boot
# Loading tables at run time (load.asm): command 4 copies a chunk of the frame into DDR.
LOAD_DM = 0x2DF600                           # load.asm, after MOVE's random state
LOAD_SW = LOAD_DM // 2                       # 0x16fb00: the command table's entry 4
CMD_TABLE_DM = 0x2DFA00                      # the handler's command table, moved here with 8 entries
LOAD_STATE_DM, LOAD_STATE_BYTES = 0x2DFA20, 8  # the chunk's sequence and checksum while it is copied
LOAD_AREA = (0x807FF000, 0x84800000)         # DDR the ColdFire's chunks may write: the request directory's 4 KB, then 128 raw tables of 512 KiB
LOAD_MAX_WORDS = 668                         # payload words in one 2,688-byte frame, after the 4-word header
POOL_DM = 0x2DFC00                           # pool.asm: a slot past the baked directory, from the load area's pool
POOL_SW = POOL_DM // 2                       # 0x16fe00
POOL_DIR = LOAD_AREA[0]                      # 0x807ff000: the request directory, the area's first 4 KB
POOL_MAGIC = 0x57525033                      # 'WRP3': +4 count, +8 generation, +16 a word per entry (frames | points << 16, 0 none)
POOL_GEOMETRY = POOL_DIR + 0x10
POOL_RAW = POOL_DIR + 0x1000                 # 0x80800000: entry j's table as stored (int16, frame-major) at POOL_RAW + j x 512 KiB
POOL_RAW_BYTES = 0x80000
POOL_SLOTS = (LOAD_AREA[1] - POOL_RAW) // POOL_RAW_BYTES   # 128
POOL_ZEROS = 0x200                           # the directory's first bytes, zeros at boot: no pool yet
# Runtime DDR above the load area, never in the boot stream (docs/sharc-ddr.md: free to 0xa0000000)
BUILD_SCRATCH = 0x84800000                   # build3's arrays, 32 KB apart (aligned for fft3 at N = 4096)
BUILD_ARRAYS = ("src_re", "src_im", "dst_re", "dst_im", "ar", "ai", "br", "bi", "zr", "zi", "discard")
BUILD_STRIDE = 0x8000
LEVELS_AT = 0x84900000                       # entry j's levels (table3's layout) at LEVELS_AT + j x LEVELS_SLOT
LEVELS_SLOT = 0x201000                       # >= table3.size_bytes(64, 4096)
LEVELS_END = LEVELS_AT + POOL_SLOTS * LEVELS_SLOT
DDR_END = 0xA0000000
# Boot-stream data for build3, in DDR_REGION
TEMPLATES_AT = 0x80700000                    # table3.templates(), 1 KB per N = 64 .. 4096
SCALES_AT = 0x80701C00                       # table3.scales(), S for F = 1 .. 64
TWR_AT, TWI_AT = 0x80702000, 0x80706000      # fft3's twiddles at N = 4096 (they serve every smaller M)
STAGE3_DATA_END = 0x8070A000
SYNC_DM = 0x2E0000                           # sync.asm (M10b-2): MOVE locked to the tempo and the song position
SYNC_SW = SYNC_DM // 2                       # 0x170000
SYNC_TABLE_DM = 0x2E0400                     # its table: a word per RATE 0..100 (live.sync_table)
SMOOTH_DM = 0x2E0600                         # smooth.asm (M10b-2): SMTH, the glide on POS
SMOOTH_SW = SMOOTH_DM // 2                   # 0x170300
DCLK_DM = 0x2E0800                           # dclk.asm (M10b-2): DCLK, the crossfade at a jump
DCLK_SW = DCLK_DM // 2                       # 0x170400
SMTH_TABLE_DM = 0x2E0C00                     # SMTH's coefficient per value, 128 float32 (live.smth_table)
DCLK_LENGTH_DM = 0x2E0E00                    # DCLK's length in samples per value, 128 u32 (live.dclk_lengths)
DCLK_INVERSE_DM = 0x2E1000                   # and 1 / length, 128 float32 (live.dclk_inverses)
SMOOTH_STATE_DM = 0x2E1200                   # SMTH's glide per voice and oscillator; DCLK's scratch at + 0x80
DCLK_STATE_DM = 0x2E1400                     # DCLK's state, 64 bytes a voice and oscillator
DCLK_BUFFERS_DM = 0x2E1C00                   # its two scratch buffers of 128 samples
DCLK_STATE_END = 0x2E2000
SUB_DM = 0x2E2000                            # sub.asm (page 3): the sub-oscillator
SUB_SW = SUB_DM // 2                         # 0x171000
SUB_STATE_DM = 0x2E2400                      # its 16 phases, then three words of scratch (sub.asm)
SUB_STATE_BYTES = 0x50
NOISE_DM = 0x2E2600                          # noise.asm (page 3): the noise, after the sub
NOISE_SW = NOISE_DM // 2                     # 0x171300
NOISE_DECAY_DM = 0x2E2C00                    # its envelope factor per DEC, 128 float32 (live.noise_decay_table)
NOISE_STATE_DM = 0x2E2E00                    # 16 voices x 32 bytes (x seeded, live.noise_seeds), then its count
NOISE_STATE_BYTES = 0x210
MIP_LEVELS_DM = 0x2E3100                     # reader_mip.asm's level records, 8 x 32 bytes (mip.level_records)
MIP_DM = 0x2E3400                            # reader_mip.asm: the reader, with mip-mapped tables
MIP_SW = MIP_DM // 2                         # 0x171a00
MIP_END = 0x2E3800                           # the reader's 1 KB
STAGE3 = mip.INTERP == "hermite2"            # the pool's tables get levels built on the DSP (build3.asm)
SHARC_SRC = pathlib.Path(__file__).resolve().parents[3] / "csrc" / "waverider" / "sharc"
# Stage 3 (dnfw.waverider.table3): the pool's levels, built on the DSP in its idle time
FFT3_DM = 0x2E3800                           # fft3.asm
FFT3_SW = FFT3_DM // 2                       # 0x171c00
STAGE3_PARAMS_DM = 0x2E4000                  # fft3's, spec3's and mipb3's parameter blocks and scratch (fixed in them)
BUILT_DM = 0x2E4100                          # build3.asm's directory: pool entry j's table (| 1), or 0
BUILD_STATE_DM = 0x2E4300                    # its state, the level rows' pointers and its save area
BUILD_STATE_END = 0x2E4500
SPEC3_DM = 0x2E4500                          # spec3.asm
SPEC3_SW = SPEC3_DM // 2                     # 0x172280
MIPB3_DM = 0x2E4800                          # mipb3.asm
MIPB3_SW = MIPB3_DM // 2                     # 0x172400
BUILD3_DM = 0x2E4B00                         # build3.asm, the idle loop's back edge jumps here
BUILD3_SW = BUILD3_DM // 2                   # 0x172580
BUILD3_END = 0x2E5600
L2_LOAD, L2_SW = 0x20000000, 0xB80000        # L2 code: load address 0x20000000 is sw 0xb80000

# stock sites
ENTRY_SW = 0x1C9448                          # i5=dm(-0x18,i6); r10=dm(-0x22,i6)
ENTRY_STOCK = bytes.fromhex("089ce80a089c5e05")
NOP16 = bytes.fromhex("0100")                # the firmware's own 16-bit NOP (sw 0x1c9447)
LOOKUP_DM = 0x25D748                         # frame nibble -> machine type, 8 words
LOOKUP_STOCK = (0, 1, 2, 3, 4, 0, 0, 0)
IDLE_SITE_SW = 0xB88ABB                      # prvIdleTask's back edge: jump (pc,-0x10)
IDLE_SITE_STOCK = bytes.fromhex("3e07ff00f0ff")
IDLE_RETURN_SW = 0xB88AAB                    # the loop's top: call prvCheckTasksWaitingTermination
CALL_SITE_SW = 0x1C9FB9                      # the handler's `r4 = 0x268438` before `cjump 0x1c2712`
CALL_SITE_STOCK = bytes.fromhex("040f26003884")
# The per-frame handler's command dispatch (sw 0x1c9d6b): the table's address and the
# bound. Stock: `i4 = 0x268a68` (four entries, the string "Audio Task" after them) and
# `r1 = lshift r2 by -2`, so commands 4 and up take case 0's code (sw 0x1c9daf). Here:
# `i4 = 0x2dfa00` (CMD_TABLE_DM) and `by -3`, commands 0..7, each a 16-bit immediate edit.
TABLE_SITE_SW = 0x1C9D9F
TABLE_SITE_STOCK = bytes.fromhex("140f2600688a")
TABLE_SITE_NEW = bytes.fromhex("140f2d0000fa")
BOUND_SITE_SW = 0x1C9DAA
BOUND_SITE_STOCK = bytes.fromhex("3e02007812fe")
BOUND_SITE_NEW = bytes.fromhex("3e02007812fd")
CMD_STOCK = (0x1C9DC2, 0x1C9E76, 0x1C9EDA, 0x1C9F0F)   # the stock table: cases 0..3


class DspError(ValueError):
    pass


# DNFW_WAVERIDER_BRIGHT=1 (the mip comparison builds, 2026-10-08): table 0's saw end has
# all 255 harmonics a 512-point frame holds instead of 32, so aliasing (and what the levels
# take away) is heard across the keyboard, not only from F#5 up. Original formula as ever.
BRIGHT = os.environ.get("DNFW_WAVERIDER_BRIGHT", "") == "1"
BRIGHT_HARMONICS = 255


def tables() -> list[list[list[int]]]:
    """The two original tables, in slot order: 0 = a 32-harmonic saw darkening to a
    sine (`testtable`'s frames reversed; 255 harmonics with BRIGHT), 1 = the overtone
    series (`harmonics`)."""
    t0 = (reduce.to_int16(testtable.source_frames(harmonics=BRIGHT_HARMONICS)) if BRIGHT
          else testtable.table())
    if NOMIP:
        return [list(reversed(t0)), harmonics.table()]
    return [mip.MipTable(list(reversed(t0))), mip.MipTable(harmonics.table())]


def sw_to_load(sw: int) -> int:
    return LOAD_ALIAS + 2 * sw


def dm_to_load(dm: int) -> int:
    return LOAD_ALIAS + dm


def l2_sw_to_load(sw: int) -> int:
    return L2_LOAD + 2 * (sw - L2_SW)


def _code() -> dict:
    if not CODE.exists():
        raise DspError(f"{CODE.name} is missing: run scripts/gen_waverider_sharc.py")
    return json.loads(CODE.read_text(encoding="utf-8"))


def objects() -> dict[str, bytes]:
    """The committed SHARC objects: reader, loop, entry JUMP, idle stub, idle JUMP."""
    spec = _code()
    return {name: sharc_object.load_bytes(bytes.fromhex(spec[name]["object_parcels_be"]))
            for name in ("reader", "machine5_live", "entry_jump", "idle_load", "idle_jump", "block_count",
                         "entry_mark", "emark_jump", "modulator", "shapes", "load", "pool", "sync",
                         "smooth", "dclk", "sub", "noise", "reader_mip", "reader_miph", "reader_miph2")}


def noise_state() -> bytes:
    """noise.asm's 16 voices at boot: each x seeded (live.noise_seeds), the rest zeros."""
    out = b"".join(struct.pack("<I", s) + bytes(28) for s in live.noise_seeds())
    return out + bytes(NOISE_STATE_BYTES - len(out))


def directory() -> bytes:
    """The directory block from 0x2de600: the magic, the count and the tables; then
    (M10a) the modulator's constants in its tail -- each oscillator's frame offsets
    at MOVE_OFFSETS_DM and the rate table at MOVE_RATE_DM. The words between (M9's
    gain and oscillator flag, the phases) are zeros, as the loop expects."""
    out = bytearray(struct.pack("<II", DIRECTORY_MAGIC, len(TABLES_DM)) + struct.pack(
        "<%dI" % len(TABLES_DM), *TABLES_DM))
    out += bytes(MOVE_RATE_DM + 4 * len(live.MOVE_RATE) - DIRECTORY_DM - len(out))
    for osc, offsets in enumerate(live.move_offsets()):
        at = MOVE_OFFSETS_DM - DIRECTORY_DM + 32 * osc
        out[at:at + 4 * len(offsets)] = struct.pack("<%dI" % len(offsets), *offsets)
    at = MOVE_RATE_DM - DIRECTORY_DM
    out[at:at + 4 * len(live.MOVE_RATE)] = struct.pack("<%dI" % len(live.MOVE_RATE), *live.MOVE_RATE)
    return bytes(out)


def command_table() -> bytes:
    """The handler's command table, moved: the stock four, load.asm at 4, and 5..7 on
    case 0's code, where any command of 4 or more went before."""
    return struct.pack("<8I", *CMD_STOCK, LOAD_SW, CMD_STOCK[0], CMD_STOCK[0], CMD_STOCK[0])


def spans() -> list[tuple[str, int, bytes]]:
    """(what, load address, payload) of every block this adds, in stream order.

    Each payload is zero-padded up to the next span's start (the last to REGION's
    end), so the region is written end to end and every code object is followed by
    at least 64 bytes of zeros (a zero word is a NOP)."""
    obj = objects()
    t = tables()
    raw = [
        ("reader_m5.asm (wr_render5)", READER_DM, obj["reader"]),
        ("machine5_live.asm (wr_type5v)", LOOP_DM, obj["machine5_live"]),
        ("state: save area, counters, 16 reader blocks (zeros)", STATE_DM, bytes(STATE_BYTES)),
        ("increment table, 129 float32", INC_TABLE_DM, live.table_bytes()),
        ("wavetable directory", DIRECTORY_DM, directory()),
        ("idle_load.asm (wr_idle)", IDLE_DM, obj["idle_load"]),
        ("block_count.asm (wr_count)", COUNT_DM, obj["block_count"]),
        ("entry_mark.asm (wr_emark)", EMARK_DM, obj["entry_mark"]),
        ("modulator.asm (wr_mod)", MOD_DM, obj["modulator"]),
        ("shapes.asm (wr_shape)", SHAPES_DM, obj["shapes"]),
        ("MOVE's random state (zeros)", MOVE_RANDOM_DM, bytes(MOVE_RANDOM_BYTES)),
        ("load.asm (wr_load)", LOAD_DM, obj["load"]),
        ("command table, 8 entries", CMD_TABLE_DM, command_table()),
        ("load state (zeros)", LOAD_STATE_DM, bytes(LOAD_STATE_BYTES)),
        ("pool.asm (wr_pool)", POOL_DM, obj["pool"]),
        ("sync.asm (wr_sync)", SYNC_DM, obj["sync"]),
        ("SYNC's note table, a word per RATE", SYNC_TABLE_DM, struct.pack("<101I", *live.sync_table())),
        ("smooth.asm (wr_smooth)", SMOOTH_DM, obj["smooth"]),
        ("dclk.asm (wr_dclk_pre)", DCLK_DM, obj["dclk"]),
        ("SMTH's coefficients, 128 float32", SMTH_TABLE_DM, struct.pack("<128f", *live.smth_table())),
        ("DCLK's lengths, 128 u32", DCLK_LENGTH_DM, struct.pack("<128I", *live.dclk_lengths())),
        ("DCLK's inverses, 128 float32", DCLK_INVERSE_DM, struct.pack("<128f", *live.dclk_inverses())),
        ("SMTH's and DCLK's state (zeros)", SMOOTH_STATE_DM, bytes(DCLK_STATE_END - SMOOTH_STATE_DM)),
        ("sub.asm (wr_sub_ran)", SUB_DM, obj["sub"]),
        ("the sub-oscillator's phases and scratch (zeros)", SUB_STATE_DM, bytes(SUB_STATE_BYTES)),
        ("noise.asm (wr_noise)", NOISE_DM, obj["noise"]),
        ("the noise's decay factors, 128 float32", NOISE_DECAY_DM, struct.pack("<128f", *live.noise_decay_table())),
        ("the noise's state (seeds, then zeros)", NOISE_STATE_DM, noise_state()),
        ("reader_mip.asm's level records", MIP_LEVELS_DM, mip.level_records()),
        {"hermite": ("reader_miph.asm (wr_miph, Hermite)", MIP_DM, obj["reader_miph"]),
         "hermite2": ("reader_miph2.asm (wr_miph2, Hermite, 16-bit taps)", MIP_DM, obj["reader_miph2"]),
         "linear": ("reader_mip.asm (wr_mip)", MIP_DM, obj["reader_mip"])}[mip.INTERP],
    ]
    if STAGE3:
        s3 = stage3_objects()
        raw += [("fft3.asm (wr_fft3)", FFT3_DM, s3["fft3"]),
                ("stage 3 parameter blocks and scratch (zeros)", STAGE3_PARAMS_DM, bytes(BUILT_DM - STAGE3_PARAMS_DM)),
                ("build3's directory and state (zeros: nothing built)", BUILT_DM, bytes(BUILD_STATE_END - BUILT_DM)),
                ("spec3.asm (wr_spec3_split, wr_spec3_join)", SPEC3_DM, s3["spec3"]),
                ("mipb3.asm (wr_mipb3_in, wr_mipb3_out)", MIPB3_DM, s3["mipb3"]),
                ("build3.asm (wr_build3)", BUILD3_DM, s3["build3"])]
    out = []
    for k, (what, at, payload) in enumerate(raw):
        end = raw[k + 1][1] if k + 1 < len(raw) else REGION[1]
        if len(payload) > end - at:
            raise DspError(f"{what} ({len(payload)} bytes) does not fit before {end:#x}")
        if "asm" in what and end - at - len(payload) < 64:
            raise DspError(f"{what} leaves fewer than 64 bytes of NOP padding")
        out.append((what, dm_to_load(at), payload + bytes(end - at - len(payload))))
    for what, at, table in ((f"table 0: saw{' (255 harmonics)' if BRIGHT else ''} -> sine (testtable reversed), mip-mapped", TABLES_AT[0], t[0]),
                            ("table 1: the overtone series (harmonics), mip-mapped", TABLES_AT[1], t[1])):
        payload = table.dsp_bytes() if isinstance(table, mip.MipTable) else reference.dsp_bytes(table)
        if len(payload) > MIP_TABLE_BYTES:
            raise DspError(f"{what} is {len(payload)} bytes, more than {MIP_TABLE_BYTES}")
        out.append((what, at, payload))                  # DDR: the target is the address
    if STAGE3:
        wr, wi = twiddles(table3.MAX_POINTS)
        out += [("build3's templates, 1 KB per N (table3.templates)", TEMPLATES_AT, table3.templates()),
                ("build3's position scales, S per F (table3.scales)", SCALES_AT, table3.scales()),
                ("fft3's twiddles at N 4096, cos", TWR_AT, wr.astype("<f4").tobytes()),
                ("fft3's twiddles at N 4096, -sin", TWI_AT, wi.astype("<f4").tobytes())]
    out.append(("pool directory (zeros: no table loaded yet)", POOL_DIR, bytes(POOL_ZEROS)))
    return out


def twiddles(points: int):
    """fft3.asm's tables: entry h + k = (cos, -sin)(pi k / h) for each half-width h < N
    (a smaller transform reads the same entries)."""
    import numpy as np  # noqa: PLC0415
    wr, wi = np.zeros(points, np.float32), np.zeros(points, np.float32)
    h = 1
    while h < points:
        a = np.pi * np.arange(h) / h
        wr[h:2 * h], wi[h:2 * h] = np.cos(a), -np.sin(a)
        h *= 2
    return wr, wi


def stage3_objects() -> dict[str, bytes]:
    """fft3, spec3, mipb3 and build3 from their committed .json (scripts/build_fft.py),
    each checked against the placement it was assembled for."""
    out = {}
    for name, sw in (("fft3", FFT3_SW), ("spec3", SPEC3_SW), ("mipb3", MIPB3_SW), ("build3", BUILD3_SW)):
        spec = json.loads((SHARC_SRC / f"{name}.json").read_text(encoding="utf-8"))
        if int(spec["load_sw"], 16) != sw:
            raise DspError(f"{name}.json was assembled for sw {spec['load_sw']}, not {sw:#x}")
        out[name] = sharc_object.load_bytes(bytes.fromhex(spec["object_parcels_be"]))
    return out


def build3_jump() -> bytes:
    """The idle loop's back edge to build3.asm: `JUMP 0x172500`, the committed idle JUMP's
    encoding (Type 8a, 063e00 + the address) with build3's address."""
    jump = lambda sw: sharc_object.load_bytes(bytes.fromhex(f"063e00{sw:06x}"))
    if objects()["idle_jump"] != jump(IDLE_SW):
        raise DspError("the committed idle JUMP is not 063e00 + its target")
    return jump(BUILD3_SW)


def placements() -> list[dict]:
    out = [{"what": what, "load_address": f"{at:#010x}", "dm_byte": f"{at - LOAD_ALIAS:#08x}",
            "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
           for what, at, payload in spans()]
    obj = objects()
    out += [{"what": f"patch: entry JUMP {COUNT_SW:#x} (the block counter, then the loop) + NOP at sw 0x1c9448",
             "load_address": f"{sw_to_load(ENTRY_SW):#010x}",
             "bytes": len(obj["entry_jump"]) + len(NOP16),
             "stock": ENTRY_STOCK.hex(), "new": (obj["entry_jump"] + NOP16).hex()},
            {"what": "patch: machine lookup 0x25d748[5] 0 -> 5",
             "load_address": f"{dm_to_load(LOOKUP_DM + 20):#010x}", "bytes": 4,
             "stock": "00000000", "new": "05000000"},
            {"what": f"patch: the idle loop's back edge at sw {IDLE_SITE_SW:#x} -> JUMP {IDLE_SW:#x}",
             "load_address": f"{l2_sw_to_load(IDLE_SITE_SW):#010x}", "bytes": len(obj["idle_jump"]),
             "stock": IDLE_SITE_STOCK.hex(), "new": obj["idle_jump"].hex()}]
    return out


def _check_free(stock: bytes, span_list) -> None:
    blocks = [b for b in bootstream.walk(stock).blocks if b.count]
    for what, at, payload in span_list:
        lo, hi = at, at + len(payload)
        in_l1 = dm_to_load(REGION[0]) <= lo and hi <= dm_to_load(REGION[1])
        in_ddr = DDR_REGION[0] <= lo and hi <= DDR_REGION[1]
        if not (in_l1 or in_ddr):
            raise DspError(f"{what} at {lo:#x} leaves the block-1 region {REGION} "
                           f"and the DDR region {DDR_REGION}")
        for b in blocks:
            if b.target < hi and lo < b.target + b.count:
                raise DspError(f"{what} at {lo:#x}+{len(payload):#x} overlaps the stock "
                               f"block at {b.target:#x}+{b.count:#x}")
    if not (STOCK_BLOCK1_END <= REGION[0] and REGION[1] <= DM_CACHE_32K):
        raise DspError(f"the region {REGION} is not between block 1's last stock byte and a 32 KB DM cache")
    if DDR_REGION[0] < STOCK_DDR_END:
        raise DspError(f"the DDR region {DDR_REGION} starts below the stock image's last DDR byte")
    ordered = sorted((at, at + len(p), w) for w, at, p in span_list)
    for (a0, a1, w0), (b0, b1, w1) in zip(ordered, ordered[1:]):
        if b0 < a1:
            raise DspError(f"{w0} and {w1} overlap")


IDLE_PAD_END = 0x2DF000
IDLE_STATE_BYTES = 0x40                     # idle: saves, LAST, total, passes, BEFORE, AFTER; count: blocks, saves, MARK; MARK0


def idle_spans() -> list[tuple[str, int, bytes]]:
    """The idle stub's own blocks: its zeroed state, and its code padded to 0x2df000
    (where table 0 began until the tables moved to DDR, so this build is unchanged)."""
    code = objects()["idle_load"]
    end = IDLE_PAD_END
    if end - IDLE_DM - len(code) < 64:
        raise DspError("idle_load.asm leaves fewer than 64 bytes of NOP padding")
    return [("idle_load state (zeros)", dm_to_load(IDLE_STATE_DM), bytes(IDLE_STATE_BYTES)),
            ("idle_load.asm (wr_idle)", dm_to_load(IDLE_DM), code + bytes(end - IDLE_DM - len(code)))]


def _check_stock(stock: bytes) -> None:
    digest = hashlib.sha256(stock).hexdigest()
    if digest != STOCK_SHA256:
        raise DspError(f"section 7 sha256 {digest[:12]}... is not stock DN2 1.11's "
                       f"({STOCK_SHA256[:12]}...)")


def _check_idle_site(stock: bytes, obj: dict) -> None:
    if len(obj["idle_jump"]) != len(IDLE_SITE_STOCK):
        raise DspError(f"the idle JUMP is {len(obj['idle_jump'])} bytes, not {len(IDLE_SITE_STOCK)}")
    if bootstream.read_span(stock, l2_sw_to_load(IDLE_SITE_SW), len(IDLE_SITE_STOCK)) != IDLE_SITE_STOCK:
        raise DspError("sw 0xb88abb is not the stock idle loop's `jump (pc,-0x10)`")


# The ColdFire's DSP loader (MAIN OS 0x400cf4f8) reads section 7 into one of two 1 MiB
# buffers and refuses a stored section over 1 MiB (0x400cf5ac) or a boot stream whose
# length + 1 is over 1 MiB (0x400cf5e4): the DSP then never boots -- no audio and no
# sequencer clock (waverider-bigtable2, 2026-10-04: 1,400,876 B, silent). Stock's is
# about 909 KB. Tables therefore load from the +Drive at run time, never in section 7.
STREAM_LIMIT = 0x100000 - 1


def _finish(out: bytearray) -> bytes:
    result = bytes(out)
    if len(result) > STREAM_LIMIT:
        raise DspError(f"section 7 is {len(result):,} B: the ColdFire loads at most {STREAM_LIMIT:,} "
                       "(a 1 MiB buffer), so the DSP would never boot")
    walked = bootstream.walk(result)
    if not walked.complete or walked.stopped_at != len(result):
        raise DspError(f"the result does not walk as a boot stream ({walked.reason})")
    return result


def section7_idle_only(stock: bytes) -> bytes:
    """Stock DN2 1.11's section 7 plus the idle-time stub and nothing else: the stock
    engine, measured. Refuses anything but stock."""
    _check_stock(stock)
    obj = objects()
    _check_idle_site(stock, obj)
    added = idle_spans()
    _check_free(stock, added)
    out = bytearray(bootstream.insert_before_final(
        stock, b"".join(bootstream.block(at, payload) for _, at, payload in added)))
    bootstream.write_span(out, l2_sw_to_load(IDLE_SITE_SW), obj["idle_jump"])
    return _finish(out)


def section7(stock: bytes) -> bytes:
    """DN2 1.11's section 7 -> Waverider's. Refuses anything else."""
    digest = hashlib.sha256(stock).hexdigest()
    if digest != STOCK_SHA256:
        raise DspError(f"section 7 sha256 {digest[:12]}... is not stock DN2 1.11's "
                       f"({STOCK_SHA256[:12]}...)")
    obj = objects()
    entry = obj["entry_jump"] + NOP16
    if len(entry) != len(ENTRY_STOCK):
        raise DspError(f"the entry patch is {len(entry)} bytes, not {len(ENTRY_STOCK)}")
    if bootstream.read_span(stock, sw_to_load(ENTRY_SW), len(ENTRY_STOCK)) != ENTRY_STOCK:
        raise DspError("sw 0x1c9448 is not the stock `i5=dm(-0x18,i6); r10=dm(-0x22,i6)`")
    if len(obj["idle_jump"]) != len(IDLE_SITE_STOCK):
        raise DspError(f"the idle JUMP is {len(obj['idle_jump'])} bytes, not {len(IDLE_SITE_STOCK)}")
    if bootstream.read_span(stock, l2_sw_to_load(IDLE_SITE_SW), len(IDLE_SITE_STOCK)) != IDLE_SITE_STOCK:
        raise DspError("sw 0xb88abb is not the stock idle loop's `jump (pc,-0x10)`")
    if bootstream.read_span(stock, sw_to_load(CALL_SITE_SW), len(CALL_SITE_STOCK)) != CALL_SITE_STOCK:
        raise DspError("sw 0x1c9fb9 is not the stock `r4 = 0x268438`")
    if bootstream.read_span(stock, sw_to_load(TABLE_SITE_SW), 6) != TABLE_SITE_STOCK:
        raise DspError("sw 0x1c9d9f is not the stock `i4 = 0x268a68`")
    if bootstream.read_span(stock, sw_to_load(BOUND_SITE_SW), 6) != BOUND_SITE_STOCK:
        raise DspError("sw 0x1c9daa is not the stock `r1 = lshift r2 by -2`")
    if struct.unpack("<4I", bootstream.read_span(stock, dm_to_load(0x268A68), 16)) != CMD_STOCK:
        raise DspError("the command table at 0x268a68 is not stock")
    if len(obj["emark_jump"]) != len(CALL_SITE_STOCK):
        raise DspError(f"the entry-mark JUMP is {len(obj['emark_jump'])} bytes, not {len(CALL_SITE_STOCK)}")
    lookup = struct.unpack("<8I", bootstream.read_span(stock, dm_to_load(LOOKUP_DM), 32))
    if lookup != LOOKUP_STOCK:
        raise DspError(f"the machine lookup is {lookup}, not stock {LOOKUP_STOCK}")
    added = spans()
    _check_free(stock, added)

    out = bytearray(bootstream.insert_before_final(
        stock, b"".join(bootstream.block(at, payload) for _, at, payload in added)))
    bootstream.write_span(out, sw_to_load(ENTRY_SW), entry)
    bootstream.write_span(out, dm_to_load(LOOKUP_DM + 20), struct.pack("<I", 5))
    bootstream.write_span(out, l2_sw_to_load(IDLE_SITE_SW), build3_jump() if STAGE3 else obj["idle_jump"])
    bootstream.write_span(out, sw_to_load(CALL_SITE_SW), obj["emark_jump"])
    bootstream.write_span(out, sw_to_load(TABLE_SITE_SW), TABLE_SITE_NEW)
    bootstream.write_span(out, sw_to_load(BOUND_SITE_SW), BOUND_SITE_NEW)
    result = bytes(out)
    walked = bootstream.walk(result)
    if not walked.complete or walked.stopped_at != len(result):
        raise DspError(f"the result does not walk as a boot stream ({walked.reason})")
    return result
