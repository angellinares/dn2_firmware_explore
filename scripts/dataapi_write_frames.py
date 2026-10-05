"""Build Data API write frames: mkwrite.py FILE PATH [first_msgid] -> hex lines (open, chunks, commit)."""
import struct, sys
TABLE = []
for i in range(256):
    c = i
    for _ in range(8): c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
    TABLE.append(c)
def crc0(data):
    c = 0
    for b in data: c = (c >> 8) ^ TABLE[(c ^ b) & 0xFF]
    return c ^ 0xFFFFFFFF
def enc(payload):
    out = bytearray()
    for i in range(0, len(payload), 7):
        ch = payload[i:i+7]; hi = 0
        for j, b in enumerate(ch):
            if b & 0x80: hi |= 1 << (6 - j)
        out.append(hi); out += bytes(b & 0x7F for b in ch)
    return out
def frame(msgid, code, body):
    p = bytes([(msgid >> 7) & 0x7F, msgid & 0x7F, 0, 0, code]) + body
    return (b'\xf0\x00\x20\x3c\x10\x00' + enc(p) + b'\xf7').hex().upper()
def main():
    data = open(sys.argv[1], 'rb').read(); path = sys.argv[2]
    m = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    handle = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    print(frame(m, 0x57, struct.pack('>I', len(data)) + path.encode('cp1252') + b'\0')); m += 1
    for k, at in enumerate(range(0, len(data), 32768)):
        ch = data[at:at + 32768]
        print(frame(m, 0x58, struct.pack('>IIII', handle, k, crc0(ch), len(ch)) + ch)); m += 1
    print(frame(m, 0x59, struct.pack('>II', handle, 1)))
main()
