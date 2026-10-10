"""Song 1's storage in decoded project images, side by side: every non-zero run.

    python scripts/song_area_compare.py RIVVI_IMAGE.bin

The first argument is a decoded image (DNX's dn2codec.decodeProjectImage). The owner's
captures come from 00_Resources/07_DataCapture (a capture is the image after 31 bytes).
Blocks are 0xc00 bytes from image 0xc3ee04, 0x200 before the 1.11 song table.
"""
import sys, struct
D = r"D:\01_Code\Z_Personal\dn2_firmware\00_Resources\07_DataCapture"
imgs = {"rivvi AM REBECCA": open(sys.argv[1],"rb").read(),
        "SKETCHPAD 09-26": open(D+r"\projects_4_12890159B.bin","rb").read()[31:],
        "SKETCHPAD 10-05": open(D+r"\projects_4_12890159B (1).bin","rb").read()[31:],
        "control project 11": open(D+r"\projects_11_12890159B.bin","rb").read()[31:]}
BASE, REC = 0xc3ee04, 0xc00
def spans(b):
    out=[]; i=0
    while i < len(b):
        if b[i]:
            j=i
            while j < len(b) and (b[j] or any(b[j:j+8])): j+=1
            out.append((i,j)); i=j
        else: i+=1
    return out
for name, im in imgs.items():
    print("==", name, len(im))
    for s in range(16):
        rec = im[BASE+s*REC: BASE+(s+1)*REC]
        if not any(rec): continue
        cnt = struct.unpack(">H", rec[0x147:0x149])[0]
        print("  song %d: row count field %d (0x%04x), non-zero bytes %d" % (s+1, cnt, cnt, sum(1 for x in rec if x)))
        if s == 0 or cnt > 99:
            for a,b in spans(rec):
                print("     +0x%03x..+0x%03x (%3d B) %s" % (a, b, b-a, rec[a:b].hex()[:150]))
    # what precedes the table
    print("  256 B before the table non-zero:", sum(1 for x in im[BASE-256:BASE] if x))
