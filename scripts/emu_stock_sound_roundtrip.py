"""A sound saved with the mods through stock 1.11's LOAD and SAVE, every write classed.

    python scripts/emu_stock_sound_roundtrip.py

The owner's question, 2026-10-10 (docs/song-rows-report.md): does stock put LFO4's
values or a mod-only LFO destination in the wrong place when it reads and saves a
project? `ui1200M` (stock), a live sound with LFO3's DEST and WAVE set past stock's
lists, LFO4's eight stored ids filled as the mod's save leaves them, then stock's
LOAD and SAVE. The control is the sound as it is.
"""
import sys, struct, collections
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emulib.machine import SNAP, Machine, STACK
LOAD, SAVE = 0x400DD1EA, 0x400DD6A6
SOUND, STORED, VALUES_AT = 1163, 359, 28
IDS = [4, 8, 12, 16, 20, 24, 28, 32]
LFO4 = [0x7000,0x0300,0x4000,0x6e00,0x0900,0x2000,0x0300,0x5000]   # DEST 110, WAVE 9
m = Machine(SNAP)
base = m.long(0x800052A0)
real = bytes(m.read(base + 52, SOUND))
own = []; strays = collections.Counter()
def note(pc, address, value, size):
    if not any(lo <= address < hi for lo, hi in own): strays[(address, pc)] += 1
m.watch_writes(0, 0xFFFFFFFF, note)
def call(fn, *a, bufs):
    own[:] = [(STACK - 0x4000, STACK + 0x1000)] + bufs
    strays.clear(); m.call(fn, *a); return dict(strays)
def vals(b): return [int.from_bytes(b[20+2*i:22+2*i],'big') for i in range(101)]
cases = {"control: the live sound as it is": {},
         "LFO3 DEST 110, WAVE 9": {20: 110<<8, 21: 9<<8},
         "LFO3 DEST 127, WAVE 13": {20: 127<<8, 21: 13<<8},
         "LFO3 DEST 255, WAVE 255": {20: 0xff00, 21: 0xff00}}
for name, edit in cases.items():
    s = bytearray(real)
    for slot, v in edit.items(): s[20+2*slot:22+2*slot] = v.to_bytes(2,'big')
    live = m.alloc(SOUND+16); m.write(live, bytes(s))
    st = m.alloc(STORED+16); x1 = call(SAVE, st, live, 0, bufs=[(st, st+STORED)])
    b = bytearray(m.read(st, STORED))
    for k, v in zip(IDS, LFO4): b[VALUES_AT+2*k:VALUES_AT+2*k+2] = v.to_bytes(2,'big')   # as the mod's save leaves it
    m.write(st, bytes(b))
    back = m.alloc(SOUND+16); m.write(back, bytes(SOUND)); x2 = call(LOAD, back, st, bufs=[(back, back+SOUND)])
    st2 = m.alloc(STORED+16); x3 = call(SAVE, st2, back, 0, bufs=[(st2, st2+STORED)])
    lv, lb = vals(bytes(s)), vals(bytes(m.read(back, SOUND)))
    ch = [(i, hex(lv[i]), hex(lb[i])) for i in range(101) if lv[i] != lb[i]]
    b2 = bytes(m.read(st2, STORED))
    d = [i for i in range(STORED) if b2[i] != b[i]]
    print(name)
    print("   live values changed by stock's load (slot, mod, stock):", ch)
    print("   stored bytes changed by stock's save:", len(d), d)
    print("   LFO4 ids after stock's save:", [hex(int.from_bytes(b2[VALUES_AT+2*i:VALUES_AT+2*i+2],'big')) for i in IDS])
    for tag, x in (("save", x1), ("load", x2), ("save again", x3)):
        print("   writes outside the sound during %s: %d %s" % (tag, sum(x.values()), [("0x%08x"%a, "pc 0x%08x"%p, c) for (a,p),c in sorted(x.items())[:6]]))
