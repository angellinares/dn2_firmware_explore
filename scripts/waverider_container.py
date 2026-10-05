"""A /waverider/<n> file as a container: wrcontainer.py OUT SLOT NAME SEED [--bad-hash|--lz4|--kind K]."""
import struct, sys
sys.path.insert(0, 'src')
from dnfw.waverider import store as S
exec(open('out/dataapi/mkwrite.py').read().split('def enc')[0])        # TABLE, crc0
def container(body, slot, kind=0x57, version=1, raw=0):
    head = (bytes.fromhex('ac11d303' '02000500' '0f') + b'0059' + struct.pack('>IIII', kind, version, slot, len(body))
            + bytes([raw, 12]))
    assert len(head) == 31
    whole = head + body
    return whole + struct.pack('>II', crc0(whole[0x1f:]), len(body)) + bytes.fromhex('aaa1daaa')
if __name__ == '__main__':
    out, slot, name, seed = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
    table = bytes((i * seed + slot) & 0xFF for i in range(16384))
    th = S.xxh32(table) ^ (1 if '--bad-hash' in sys.argv else 0)
    e = S.Entry(name, 16, 512, S.slot_start(slot), len(table), th, th, len(table))
    kind = int(sys.argv[sys.argv.index('--kind') + 1]) if '--kind' in sys.argv else 0x57
    open(out, 'wb').write(container(e.to_bytes() + table, slot, kind=kind, raw=1 if '--lz4' in sys.argv else 0))
    open(out + '.table', 'wb').write(table)
