// The Text and Controls tools of the glyph editor and animator under node: text layout in the
// two built-in fonts (widths, glyph placement, missing characters, font files), the core's
// paste at the canvas edges, and the control generators against small hand-checked goldens.
// Run by test/test_glyph_text_controls.py.
import { readFileSync } from "node:fs";
import vm from "node:vm";

const ROOT = new URL("../", import.meta.url);
const ctx = {};
for (const f of ["glyph_anim_core.js", "glyph_font3x5.js", "glyph_text.js", "glyph_controls.js", "glyph_icons.js", "glyph_tools.js"]) {
  vm.runInNewContext(readFileSync(new URL(`site/js/glyph-tools/${f}`, ROOT), "utf8"), ctx);
}
const G = ctx.GlyphAnim, T = ctx.GlyphText, C = ctx.GlyphControls, TOOLS = ctx.GlyphTools;
const ok = (name, pass) => { console.log(`${pass ? "OK  " : "FAIL"} ${name}`); if (!pass) process.exitCode = 1; };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const lit = (rows) => rows.reduce((n, r) => n + (r.match(/#/g)?.length ?? 0), 0);

// 1. The fonts.
const [f3, f4] = T.builtInFonts();
const json = JSON.parse(readFileSync(new URL("src/dnfw/font3x5.json", ROOT), "utf8"));
ok("the 3 x 5 font is font3x5.json, with 1 as # and 0 as .",
   f3.id === "3x5" && f3.width === 3 && f3.height === 5 && same(Object.keys(f3.glyphs), Object.keys(json.glyphs))
   && Object.entries(json.glyphs).every(([ch, rows]) => same(f3.glyphs[ch], rows.map((r) => r.replace(/1/g, "#").replace(/0/g, ".")))));
const wanted = [..."ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:;!?-+=/'\"()[]<>_%*#"];
const g4 = Object.entries(f4.glyphs);
ok("the 4 x 5 font has uppercase, digits and punctuation, each 5 rows of 4",
   f4.id === "4x5" && wanted.every((ch) => f4.glyphs[ch]) && g4.length === wanted.length
   && g4.every(([, rows]) => rows.length === 5 && rows.every((r) => /^[.#]{4}$/.test(r))));
const looks = new Map();
for (const [ch, rows] of g4) { const k = rows.join(""); looks.set(k, [...(looks.get(k) ?? []), ch]); }
ok("no two 4 x 5 glyphs are the same", [...looks.values()].every((chs) => chs.length === 1));

// 2. Layout: widths, placement, lines, missing characters.
ok("width: letters plus 1 dark column between them, none after the last",
   T.layout("AB", f3).width === 7 && T.layout("AB", f4).width === 9 && T.layout("AB", f4, { spacing: 0 }).width === 8
   && T.layout("A", f4).width === 4 && T.layout("AB", f4).height === 5);
ok("placement: each glyph at its column, the gap dark",
   same(T.layout("HI", f4).rows, f4.glyphs.H.map((r, y) => r + "." + f4.glyphs.I[y])));
ok("a new line starts at the left, 1 dark row down",
   same(T.layout("A\nBC", f4).rows, [...f4.glyphs.A.map((r) => r + "....."), ".........", ...f4.glyphs.B.map((r, y) => r + "." + f4.glyphs.C[y])]));
const miss = T.layout("a~é~1", f4);
ok("lowercase uses uppercase; a missing character keeps a space's room and is listed once",
   same(miss.missing, ["~", "é"]) && same(miss.rows, T.layout("A   1", f4).rows) && miss.width === 24);
ok("no text gives no rows", same(T.layout("", f3), { rows: [], width: 0, height: 0, missing: [] }));

// 3. Font files from the user's computer.
const file = T.parseFont(JSON.stringify({ height: 2, glyphs: { A: ["10", "11"], B: ["#.#", "..#"] } }), "mine.json");
ok("a font file in the JSON shape reads, each glyph at its own width",
   file.name === "mine" && file.height === 2 && same(T.layout("AB", file).rows, ["#..#.#", "##...#"]));
const refused = (text) => { try { T.parseFont(text); return false; } catch (e) { return e.message.length > 0; } };
ok("a file that is not JSON, has no glyphs, or has bad rows is refused with a message",
   refused("{") && refused("{}") && refused('{"height": 2, "glyphs": {"A": ["10"]}}')
   && refused('{"height": 1, "glyphs": {"A": ["1x"]}}') && refused('{"height": 1, "glyphs": {"AB": ["1"]}}'));

// 4. Placing rows: the core's paste, and where the tools put them.
const box = ["##", "#."];
ok("paste lights the rows' lit pixels and keeps the rest; opaque also darkens the box; off the frame is dropped",
   same(G.paste(["###", "###"], box, 1, 1), ["###", "###"])
   && same(G.paste(["###", "###"], box, 1, 0, { opaque: true }), ["###", "##."])
   && same(G.paste(G.blank(3, 2), box, 2, 1), ["...", "..#"])
   && same(G.paste(["##", "##"], box, 0, 0, { on: false }), ["..", ".#"])
   && same(G.paste(["##", "##"], box, -1, -1, { on: false }), ["##", "##"]));
const wide = T.layout("THE QUICK BROWN FOX JUMPS 0123456789", f4).rows;
const big = G.paste(G.blank(128, 64), wide, 100, 61), one = G.paste(G.blank(1, 1), wide, 0, 0);
ok("text at any canvas size: cut at the edge of 128 x 64, and of 1 x 1",
   big.length === 64 && big.every((r) => r.length === 128) && lit(big) === lit(wide.slice(0, 3).map((r) => r.slice(0, 28)))
   && same(one, [wide[0][0]]));
ok("text has its top left at the pointer, a control its centre",
   same(TOOLS.stampOrigin("text", wide, 5, 6), [5, 6]) && same(TOOLS.stampOrigin("control", G.blank(15, 7), 20, 10), [13, 7])
   && TOOLS.TOOLS.some((t) => t.id === "text" && t.key === "T") && TOOLS.TOOLS.some((t) => t.id === "control" && t.key === "K"));
ok("the two new tools have 16 x 16 icons", ["text", "control"].every((k) => ctx.GlyphIcons.ICONS[k]?.length === 16
   && ctx.GlyphIcons.ICONS[k].every((r) => r.length === 16)));

// 5. Controls: goldens, checked by hand, at one size and value each.
ok("knob, 9 px, ring and line, value 0: the line points to the lower left", same(C.knob({ size: 9, mark: "line", value: 0 }), [
  "...###...",
  "..#...#..",
  ".#.....#.",
  "#.......#",
  "#...#...#",
  "#..#....#",
  ".##....#.",
  "..#...#..",
  "...###...",
]));
ok("knob, 11 px, line and arc, value 50 %: the line points up, the arc is solid to the top and dotted after it",
   same(C.knob({ size: 11, mark: "both", value: 0.5 }), [
  "...####....",
  "..#........",
  ".#..###....",
  "#..#.#.#...",
  "#.#..#..#.#",
  "#.#..#..#..",
  "#.#.....#.#",
  "#..#...#...",
  ".#..###....",
  "...........",
  "...........",
]));
ok("slider, 12 x 5, fill, 50 %: a frame, a dark gap, 4 of the 8 inner columns lit", same(C.slider({ length: 12, thick: 5, value: 0.5 }), [
  "############",
  "#..........#",
  "#.####.....#",
  "#..........#",
  "############",
]));
ok("slider, 12 x 5, handle, 100 %: the handle at the right end, a dark pixel before it on the track",
   same(C.slider({ length: 12, thick: 5, value: 1, style: "handle" }), [
  ".........###",
  ".........###",
  "########.###",
  ".........###",
  ".........###",
]));
ok("slider upright, 7 x 5, 50 %: filled from the bottom", same(C.slider({ orient: "v", length: 7, thick: 5, value: 0.5 }), [
  "#####",
  "#...#",
  "#...#",
  "#.#.#",
  "#.#.#",
  "#...#",
  "#####",
]));
ok("button, 7 x 5, off: an outline with round corners", same(C.button({ w: 7, h: 5, on: false }), [
  ".#####.",
  "#.....#",
  "#.....#",
  "#.....#",
  ".#####.",
]));
ok("switch, 9 x 5: off has the knob at the left; on fills the track and rings the knob at the right",
   same(C.toggle({ w: 9, h: 5, on: false }), [
  ".#######.",
  "#.......#",
  "#.#.....#",
  "#.......#",
  ".#######.",
]) && same(C.toggle({ w: 9, h: 5, on: true }), [
  ".#######.",
  "#####...#",
  "#####.#.#",
  "#####...#",
  ".#######.",
]));
ok("check box, 7 px, on: a tick inside the box", same(C.toggle({ style: "box", h: 7, on: true }), [
  "#######",
  "#.....#",
  "#...#.#",
  "#.##..#",
  "#.#...#",
  "#.....#",
  "#######",
]));

// 6. Controls: pixel counts and limits over many settings.
ok("button: on lights w x h - 4 pixels, off 2 (w + h) - 8, square corners add 4",
   [[3, 3], [11, 7], [64, 64]].every(([w, h]) => lit(C.button({ w, h, on: true })) === w * h - 4
     && lit(C.button({ w, h, on: false })) === 2 * (w + h) - 8 && lit(C.button({ w, h, on: true, round: false })) === w * h));
ok("slider fill: the frame plus round(value x inner columns) columns of the inner rows",
   [0, 0.25, 0.5, 1].every((v) => lit(C.slider({ length: 40, thick: 7, value: v })) === 2 * (40 + 7) - 4 + Math.round(36 * v) * 3));
ok("an upright slider has the same pixels as one across, turned",
   [0, 0.3, 1].every((v) => ["fill", "handle"].every((style) => {
     const h = C.slider({ length: 20, thick: 6, value: v, style }), u = C.slider({ orient: "v", length: 20, thick: 6, value: v, style });
     return u.length === 20 && u[0].length === 6 && lit(u) === lit(h) && u.every((r, y) => [...r].every((c, x) => c === h[x][19 - y]));
   })));
const arcs = [0, 0.25, 0.5, 0.75, 1].map((v) => {
  const k = C.knob({ size: 21, mark: "arc", value: v });
  return k.reduce((n, r, y) => n + [...r].filter((c, x) => c === "#" && ((x + y) % 2 === 1)).length, 0);
});
ok("knob arc: the solid part grows with the value", arcs.every((n, i) => i === 0 || n > arcs[i - 1]));
const all = [];
for (const [kind] of C.KINDS) for (const v of [0, 0.5, 1]) for (const size of [1, 5, 9, 33, 200]) {
  all.push(C.control(kind, { value: v, size, length: size, thick: size, w: size, h: size }));
}
ok("every control, at any setting, is a box of rows of # and . within 128 x 64, and the same settings give the same rows",
   all.every((r) => r.length >= 3 && r.length <= 128 && r.every((row) => row.length === r[0].length && /^[.#]+$/.test(row)))
   && same(C.knob({ size: 64 }).length, 64) && same(C.control("knob", { value: 0.3 }), C.control("knob", { value: 0.3 })));
