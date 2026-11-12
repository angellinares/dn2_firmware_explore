"""Build the 1.11 -> 1.12 code map and check it against addresses already verified by hand (2026-11-12).

    python scripts/osport_check.py OLD_MAIN_OS.bin NEW_MAIN_OS.bin
"""
import sys, time, pickle, pathlib
from dnfw.osport import codemap as C

old_img, new_img = (pathlib.Path(p).read_bytes() for p in sys.argv[1:3])
cache = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else None
t = time.time()
if cache and cache.exists():
    old, new = pickle.loads(cache.read_bytes())
else:
    print("decoding 1.11 ...", flush=True); old = C.decode(old_img, 0x401D0400)
    print(f"  {len(old):,} instructions, {time.time()-t:.0f} s", flush=True)
    print("decoding 1.12 ...", flush=True); new = C.decode(new_img, 0x401D0810)
    print(f"  {len(new):,} instructions, {time.time()-t:.0f} s", flush=True)
    if cache: cache.write_bytes(pickle.dumps((old, new)))
m = C.CodeMap.build(old, new)
print(f"anchored {len(m.pairs):,} of {len(old):,} instructions ({100*m.coverage():.1f} %), {time.time()-t:.0f} s", flush=True)

# (old, expected new, what): checked by hand on the two images, 2026-11-12
CODE = [
    (0x40026980, 0x40026980, "layermidi hook 1"), (0x40026D32, 0x40026D32, "layermidi hook 2"),
    (0x400187F6, 0x400187F6, "midiarp"), (0x4005F9C2, 0x4005F9C2, "midiarp"),
    (0x400D905E, 0x400D91C2, "midiarp"), (0x400D9EDC, 0x400DA040, "midiarp"),
    (0x40121D86, 0x40122066, "midiarp jsr operand"), (0x40121916, 0x40121BF6, "midiarp jsr operand"),
    (0x400268FA, 0x400268FA, "midiarp jsr operand"), (0x4012A408, 0x4012A6E8, "MIDI record allocator"),
    (0x4002E464, 0x4002E464, "redraw test (POLL)"), (0x4012166E, 0x4012194E, "SysEx handler"),
    (0x400EF5D0, 0x400EF734, "LZ4 decompress"), (0x400EFB70, 0x400EFCD4, "LZ4 compress"),
    (0x4012C780, 0x4012CA60, "eMMC write"), (0x4012C59A, 0x4012C87A, "eMMC read"),
    (0x400DBC4C, 0x400DBDB0, "upgrade validator"),
    (0x4002A5C2, 0x4002A5C2, "voice setup loader"), (0x40025B80, 0x40025B80, "voice setup call"),
    (0x4003FAA4, 0x4003FAA4, "voice setup call"), (0x4002B12E, 0x4002B12E, "voices-in-use getter"),
    (0x40027092, 0x40027092, "voices-in-use call"),
]
DATA = [
    (0x401F7F94, 0x401F83A4, "parameter table base"), (0x4464ABF0, 0x4464BBF0, "heap start"),
    (0x4664ABF0, 0x4664BBF0, "heap end"), (0x466B74D0, 0x466B84D0, "reset clear end"),
    (0x42C4BACC, 0x42C4CACC, "intro pointer"), (0x4059CAFC, 0x4059DAFC, "voices-in-use BSS word"),
    (0x4012B8B0, 0x4012BB90, "midiarp old jsr target"), (0x400DB524, 0x400DB688, "midiarp old jsr target"),
    (0x4E6F1300, 0x4E6F9300, "bounce buffer"),
]
bad = 0
for old_a, want, what in CODE:
    got, how = m.translate(old_a)
    ok = got == want
    bad += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} code {old_a:#x} -> {got and hex(got)} ({how}), want {want:#x}  {what}")
for old_v, want, what in DATA:
    got, how = m.data(old_v)
    ok = got == want
    bad += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} data {old_v:#x} -> {got and hex(got)} ({how}), want {want:#x}  {what}")
print(f"{len(CODE)+len(DATA)-bad} of {len(CODE)+len(DATA)} known addresses right")
print("OSPORT CHECK DONE")
