// The glyph animator's model (site/js/glyph-tools/glyph_anim_core.js) under node: the knob picks the frame
// by the stock formula, the firmware format encodes a hand-made 17x17 frame to the words
// worked out by hand and decodes back, and the animation file round-trips byte for byte.
// Run by test/test_glyph_animator.py.
import { readFileSync } from "node:fs";
import vm from "node:vm";

const ROOT = new URL("../", import.meta.url);
const ctx = {};
vm.runInNewContext(readFileSync(new URL("site/js/glyph-tools/glyph_anim_core.js", ROOT), "utf8"), ctx);
const G = ctx.GlyphAnim;
const ok = (name, pass) => { console.log(`${pass ? "OK  " : "FAIL"} ${name}`); if (!pass) process.exitCode = 1; };

// 1. The knob: index = round(value x (frames - 1) / range), value = knob x 256.
let knobOk = true;
for (const range of [0x7f00, 0x8000]) {
  for (const n of [2, 13, 60, 96]) {
    for (const knob of [0, 1, 64, 126, 127]) {
      const want = Math.round((knob * 256 * (n - 1)) / range);
      if (G.knobFrame(knob, n, range) !== Math.min(n - 1, want)) knobOk = false;
    }
  }
}
ok("the knob picks round(value x (frames - 1) / range) at 0, 1, 64, 126, 127 for 2, 13, 60, 96 frames", knobOk);
ok("knob 127 at range 0x7f00 is the last frame, knob 0 the first",
   G.knobFrame(127, 96, 0x7f00) === 95 && G.knobFrame(0, 96, 0x7f00) === 0 && G.knobFrame(64, 13, 0x7f00) === 6);

// 2. The firmware format, against a 17x17 frame worked out by hand.
const hand = G.blank(17, 17).map((r) => [...r]);
hand[0][0] = "#";                                        // column 0: top row only -> 0x80000000
hand[16][2] = "#";                                       // column 2: row 16 -> bit 31-16 -> 0x00008000
for (let y = 0; y < 17; y++) hand[y][3] = "#";           // column 3: all 17 rows -> 0xffff8000
hand[1][16] = "#"; hand[8][16] = "#";                    // column 16: rows 1 and 8 -> 0x40800000
const frame = hand.map((r) => r.join(""));
const want = Array(17).fill(0);
want[0] = 0x80000000; want[2] = 0x00008000; want[3] = 0xffff8000; want[16] = 0x40800000;
const bytes = G.encode([frame], 17, 17);
const words = [...Array(17)].map((_, i) => ((bytes[i * 4] << 24) | (bytes[i * 4 + 1] << 16) | (bytes[i * 4 + 2] << 8) | bytes[i * 4 + 3]) >>> 0);
ok("a 17x17 frame encodes to 17 big-endian words, top row in the most significant bit",
   bytes.length === 68 && words.every((w, i) => w === want[i]));
ok("the words decode back to the same frame", JSON.stringify(G.decode(bytes, 17, 17)) === JSON.stringify([frame]));
const hex = G.toHex(bytes, 17, 17);
ok("hex text has one line per frame and reads back to the same bytes",
   hex.split("\n").length === 1 && hex.startsWith("80000000 00000000 00008000 ffff8000")
   && JSON.stringify([...G.fromHex(hex)]) === JSON.stringify([...bytes]));

let seed = 7;
const rand = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
let rt = true;
for (const [w, h, n] of [[17, 17, 13], [19, 17, 3], [11, 11, 2], [128, 64, 2], [5, 33, 4]]) {
  const fs = [...Array(n)].map(() => [...Array(h)].map(() => [...Array(w)].map(() => (rand() < 0.4 ? "#" : ".")).join("")));
  const b = G.encode(fs, w, h);
  rt &&= b.length === n * w * Math.ceil(h / 32) * 4 && JSON.stringify(G.decode(b, w, h)) === JSON.stringify(fs);
}
ok("random frames of 17x17, 19x17, 11x11, 128x64 and 5x33 encode and decode unchanged", rt);
let refused = false;
try { G.decode(new Uint8Array(70), 17, 17); } catch { refused = true; }
ok("bytes that are not whole frames are refused", refused);

// 3. The animation file.
const text = readFileSync(new URL("site/js/mods/glyph-anims.js", ROOT), "utf8");
const anims = G.parse(text);
ok("the shipped file reads back and writes the same text", G.serialise(anims) === text);
ok("the shipped example is valid: 13 frames of 17x17",
   anims.sinesquare && G.valid(anims.sinesquare) && anims.sinesquare.frames.length === 13
   && anims.sinesquare.width === 17 && anims.sinesquare.height === 17);
const two = { a: { width: 3, height: 2, frames: [["#..", ".#."], ["...", "###"]] }, b: { width: 1, height: 1, frames: [["#"]] } };
ok("several animations round-trip through the file", JSON.stringify(G.parse(G.serialise(two))) === JSON.stringify(two));
ok("JSON reads to the same model", JSON.stringify(G.fromJSON(JSON.stringify(two))) === JSON.stringify(two));

// 4. The still glyphs, and the URL form the still editor sends.
const stillText = readFileSync(new URL("site/js/mods/glyphs.js", ROOT), "utf8");
const still = G.parseStill(stillText);
const ids = [...stillText.split("export const GLYPHS = {")[1].matchAll(/\n  ([a-z0-9]+): \[/g)].map((m) => m[1]);
ok("every still glyph in glyphs.js reads as 16 rows of 16, and nothing else does",
   JSON.stringify(Object.keys(still)) === JSON.stringify(ids) && ids.length > 0
   && Object.values(still).every((r) => r.length === 16 && r.every((row) => row.length === 16)));
ok("a glyph goes to hex for the URL and back unchanged",
   Object.values(still).every((r) => JSON.stringify(G.hexToRows(G.rowsToHex(r), 16)) === JSON.stringify(r))
   && G.rowsToHex(["#..." + ".".repeat(12)]) === "8000" && G.hexToRows("zz", 16) === null);

// 5. Rows as text: paste, blocks, refusal, fit.
const pb = G.parseBlocks("#.#\n.#.\n\n\n###\r\n  ...  \n");
ok("pasted text splits into blocks at blank lines", pb.blocks?.length === 2 && pb.blocks[1][1] === "...");
ok("a character other than # and . is refused, with its line",
   /Line 2 has "x"/.test(G.parseBlocks("##\n#x\n").error ?? "") && !G.parseBlocks("##\n#x\n").blocks);
const small = G.fitRows(["##", "#"], 4, 3), big = G.fitRows(["#####", "#", "#", "#"], 4, 3);
ok("small rows land at the top left, large rows are cut and say so",
   JSON.stringify(small.frame) === JSON.stringify(["##..", "#...", "...."]) && !small.trimmed
   && JSON.stringify(big.frame) === JSON.stringify(["####", "#...", "#..."]) && big.trimmed);
ok("all frames copy as blocks with blank lines between", G.framesText([["#."], [".#"]]) === "#.\n\n.#");

// 6. GIF, decoded by a reader written here, not the encoder's code.
function readGif(b) {
  let p = 0;
  const u16 = () => { const v = b[p] | (b[p + 1] << 8); p += 2; return v; };
  const sig = String.fromCharCode(...b.slice(0, 6)); p = 6;
  const W = u16(), H = u16(), packed = b[p++]; p += 2;
  const gct = []; const n = 2 << (packed & 7);
  for (let i = 0; i < n; i++) { gct.push([b[p], b[p + 1], b[p + 2]]); p += 3; }
  const frames = []; let delay = null, loop = false;
  for (;;) {
    const t = b[p++];
    if (t === 0x3b) break;
    if (t === 0x21) {
      const label = b[p++];
      if (label === 0xf9) { delay = b[p + 2] | (b[p + 3] << 8); }
      if (label === 0xff && String.fromCharCode(...b.slice(p + 1, p + 12)) === "NETSCAPE2.0") loop = b[p + 14] === 0 && b[p + 15] === 0;
      while (b[p]) p += b[p] + 1;
      p++;
      continue;
    }
    if (t !== 0x2c) throw new Error("bad block " + t);
    p += 4; const fw = u16(), fh = u16(); p++;
    const min = b[p++]; const data = [];
    while (b[p]) { data.push(...b.slice(p + 1, p + 1 + b[p])); p += b[p] + 1; }
    p++;
    // LZW, after the GIF89a specification
    const clear = 1 << min, eoi = clear + 1;
    let size = min + 1, next = eoi + 1, dict = [], prev = null, bit = 0;
    const reset = () => { dict = [...Array(clear)].map((_, i) => [i]); dict.push(null, null); size = min + 1; next = eoi + 1; prev = null; };
    reset();
    const out = [];
    for (;;) {
      let code = 0;
      for (let i = 0; i < size; i++, bit++) code |= ((data[bit >> 3] >> (bit & 7)) & 1) << i;
      if (code === clear) { reset(); continue; }
      if (code === eoi) break;
      let entry;
      if (prev === null) entry = dict[code];
      else {
        entry = code < next ? dict[code] : [...dict[prev], dict[prev][0]];
        if (next < 4096) dict[next++] = [...dict[prev], entry[0]];
      }
      out.push(...entry);
      prev = code;
      if (next === 1 << size && size < 12) size++;
    }
    frames.push({ fw, fh, delay, pixels: out });
  }
  return { sig, W, H, gct, frames, loop };
}
function gifMatches(anim, scale, theme, delay) {
  const g = readGif(G.gif(anim.frames, anim.width, anim.height, { scale, theme, delay }));
  const W = anim.width * scale, H = anim.height * scale, c = G.GIF_COLOURS[theme];
  return g.sig === "GIF89a" && g.W === W && g.H === H && g.loop && g.frames.length === anim.frames.length
    && JSON.stringify(g.gct) === JSON.stringify([c.bg, c.ink])
    && g.frames.every((fr, i) => fr.fw === W && fr.fh === H && fr.delay === delay && fr.pixels.length === W * H
      && fr.pixels.every((v, j) => v === (anim.frames[i][((j / W) | 0) / scale | 0][(j % W) / scale | 0] === "#" ? 1 : 0)));
}
ok("the 13-frame example as a 3x GIF: 13 frames of 51x51, delay 8, pixels equal, loops", gifMatches(anims.sinesquare, 3, "light", 8));
const noise = { width: 128, height: 64, frames: [0, 1].map(() => [...Array(64)].map(() => [...Array(128)].map(() => (rand() < 0.5 ? "#" : ".")).join(""))) };
ok("two noisy 128x64 frames as an 8x GIF (1024x512, the code table fills and clears) decode the same", gifMatches(noise, 8, "dark", 2));
ok("a 1x GIF of one 11x11 frame, and the delay from the speed", gifMatches({ width: 11, height: 11, frames: [G.blank(11, 11)] }, 1, "light", G.gifDelay(12))
   && G.gifDelay(12) === 8 && G.gifDelay(60) === 2 && G.gifDelay(1) === 100);

// 7. The tween is plain frames: its ends are the key frames.
const tw = G.tween([G.blank(4, 4), G.blank(4, 4), G.blank(4, 4), G.OPS.invert(G.blank(4, 4))], 0, 3);
ok("a dissolve fills the frames between, from one key frame toward the other",
   tw[1].join("").split("#").length < tw[2].join("").split("#").length && G.valid({ width: 4, height: 4, frames: tw }));
