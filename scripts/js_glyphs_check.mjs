// The mod glyphs (site/js/mods/glyphs.js) under node: each one's SVG covers exactly its lit
// pixels in currentColor with crisp edges, and the page module fills every data-glyph element
// with a known id and leaves an unknown one empty. Run by test/test_js_glyphs.py.
import { GLYPHS, SIZE, glyphSvg, runs } from "../site/js/mods/glyphs.js";
import { mountGlyphs, stepGlyphs } from "../site/js/app/glyphs-page.js";
import { ANIMS } from "../site/js/mods/glyph-anims.js";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const ok = (name, pass) => { console.log(`${pass ? "OK  " : "FAIL"} ${name}`); if (!pass) process.exitCode = 1; };

function node(tag) {
  return { tag, attrs: {}, children: [],
    setAttribute(k, v) { this.attrs[k] = String(v); },
    append(...kids) { this.children.push(...kids); },
    replaceChildren(...kids) { this.children = kids; } };
}
const doc = { createElementNS: (ns, tag) => ({ ...node(tag), ns }) };

ok("runs merges a row into one rect per lit stretch",
   JSON.stringify(runs(["##..#", ".###."])) === JSON.stringify([[0, 0, 2], [4, 0, 1], [1, 1, 3]]));

let covered = true, styled = true;
for (const [id, rows] of Object.entries(GLYPHS)) {
  const svg = glyphSvg(id, doc);
  styled &&= svg.ns === "http://www.w3.org/2000/svg" && svg.attrs.viewBox === `0 0 ${SIZE} ${SIZE}`
    && svg.attrs["shape-rendering"] === "crispEdges" && svg.attrs.fill === "currentColor";
  const lit = new Set();
  for (const r of svg.children) {
    for (let x = +r.attrs.x; x < +r.attrs.x + +r.attrs.width; x++) lit.add(`${x},${r.attrs.y}`);
  }
  const want = new Set();
  rows.forEach((row, y) => [...row].forEach((c, x) => { if (c === "#") want.add(`${x},${y}`); }));
  covered &&= lit.size === want.size && [...want].every((p) => lit.has(p));
}
ok("every glyph's SVG lights exactly its # pixels", covered);
ok("every glyph is in currentColor on a 16x16 crisp-edged grid", styled);
ok("an id with no glyph gives no SVG", glyphSvg("nosuchmod", doc) === null);

const known = { ...node("span"), dataset: { glyph: "lfo4" } };
const unknown = { ...node("span"), dataset: { glyph: "nosuchmod" } };
mountGlyphs({ ...doc, querySelectorAll: () => [known, unknown] });
ok("the page module draws a known glyph and leaves an unknown one empty",
   known.children.length === 1 && known.children[0].tag === "svg" && unknown.children.length === 0);

// A mod with an animation plays it: frame 0 on mount, the next frame on each step, round again
// at the end; with motion off it shows its still glyph.
const lit = (svg) => { const s = new Set(); for (const r of svg.children) for (let x = +r.attrs.x; x < +r.attrs.x + +r.attrs.width; x++) s.add(`${x},${r.attrs.y}`); return s; };
const want = (rows) => { const s = new Set(); rows.forEach((row, y) => [...row].forEach((c, x) => { if (c === "#") s.add(`${x},${y}`); })); return s; };
const same = (a, b) => a.size === b.size && [...a].every((p) => b.has(p));
const anim = ANIMS.waverider;
ok("waverider has an animation of two frames or more", !!anim && anim.frames.length > 1);
const el = { ...node("span"), dataset: { glyph: "waverider" } };
ok("the page module plays one animated glyph", mountGlyphs({ ...doc, querySelectorAll: () => [el] }) === 1);
let frames = true;
for (let i = 0; i <= anim.frames.length; i++) {
  frames &&= same(lit(el.children[0]), want(anim.frames[i % anim.frames.length]));
  stepGlyphs();
}
ok("each step shows the next frame's exact pixels, and it loops", frames);
const still = { ...node("span"), dataset: { glyph: "waverider" } };
mountGlyphs({ ...doc, querySelectorAll: () => [still] }, false);
ok("with motion off it shows the still glyph", same(lit(still.children[0]), want(GLYPHS.waverider)));


// The glyph tools' drawing and morph (site/js/glyph-tools/glyph_anim_core.js, site/js/glyph-tools/glyph_tools.js), as the
// two editor pages load them: classic scripts in one global scope.
{
  const ctx = {};
  vm.createContext(ctx);
  for (const f of ["site/js/glyph-tools/glyph_anim_core.js", "site/js/glyph-tools/glyph_tools.js"]) {
    vm.runInContext(readFileSync(new URL(`../${f}`, import.meta.url), "utf8"), ctx);
  }
  const G = ctx.GlyphAnim, T = ctx.GlyphTools;
  const J = JSON.stringify;
  const draw = (pts, w, h) => G.plot(G.blank(w, h), pts);

  // shapes: integer pixels, known cases
  ok("Bresenham lines: shallow, steep, one point and backwards",
     J(G.line(0, 0, 5, 2)) === J([[0, 0], [1, 0], [2, 1], [3, 1], [4, 2], [5, 2]])
     && J(G.line(1, 0, 2, 4)) === J([[1, 0], [1, 1], [2, 2], [2, 3], [2, 4]])
     && J(G.line(3, 3, 3, 3)) === J([[3, 3]])
     && J(draw(G.line(5, 2, 0, 0), 6, 3)) === J(draw(G.line(0, 0, 5, 2), 6, 3)));
  ok("a rectangle outline and a filled one, from either corner",
     J(draw(G.rect(1, 1, 4, 3), 6, 5)) === J(["......", ".####.", ".#..#.", ".####.", "......"])
     && J(draw(G.rect(4, 3, 1, 1, true), 6, 5)) === J(["......", ".####.", ".####.", ".####.", "......"]));
  ok("an 8x5 ellipse outline has the midpoint shape",
     J(draw(G.ellipse(0, 0, 7, 4), 8, 5)) === J(["..####..", ".#....#.", "#......#", ".#....#.", "..####.."]));
  const circle = draw(G.ellipse(0, 0, 8, 8), 9, 9);
  const flipped = circle.map((r) => [...r].reverse().join("")), turned = circle.map((_, y) => circle.map((r) => r[y]).join(""));
  ok("a 9x9 circle is the same mirrored and turned, and touches each side once",
     J(circle) === J(flipped) && J(circle) === J([...circle].reverse()) && J(circle) === J(turned)
     && circle[4] === "#.......#" && circle[0] === "...###...");
  const filled = draw(G.ellipse(1, 1, 10, 6, true), 12, 8);
  ok("a filled ellipse is its outline with every row spanned",
     filled.every((r, y) => { const s = r.indexOf("#"), e = r.lastIndexOf("#"); return s < 0 || !r.slice(s, e + 1).includes("."); })
     && J(filled.map((r) => r.indexOf("#"))) === J(draw(G.ellipse(1, 1, 10, 6), 12, 8).map((r) => r.indexOf("#"))));
  ok("Shift: a line snaps to 0, 45 or 90 degrees, a box to a square",
     J(G.constrain("line", 0, 0, 9, 4)) === J([9, 0]) && J(G.constrain("line", 0, 0, 2, 9)) === J([0, 9])
     && J(G.constrain("line", 0, 0, 5, 4)) === J([5, 5]) && J(G.constrain("rect", 5, 5, 2, 9)) === J([1, 9])
     && J(G.shape("ellipse", 0, 0, 8, 3, { shift: true })) === J(G.ellipse(0, 0, 8, 8)));
  ok("points off the frame are dropped", J(G.plot(G.blank(3, 2), [[-1, 0], [1, 1], [3, 0], [0, 5]])) === J(["...", ".#."]));

  // the shared drag
  const st = { tool: "rect", filled: false, erase: false };
  const d = T.drag(st, G.blank(6, 5), 1, 1);
  d.move(4, 3); d.move(2, 2);
  ok("a shape drag previews from the start each move: moving back shrinks it",
     J(d.frame) === J(["......", ".##...", ".##...", "......", "......"]));
  const full = G.OPS.invert(G.blank(6, 3));
  const er = T.drag({ tool: "line", filled: false, erase: false }, full, 0, 1, { button: 2 });
  er.move(5, 1);
  const pen = T.drag({ tool: "pencil", filled: false, erase: false }, G.blank(6, 3), 0, 0);
  pen.move(5, 2);
  ok("the right button erases; a fast pencil drag leaves no gaps",
     J(er.frame) === J(["######", "......", "######"]) && !er.on
     && J(pen.frame) === J(draw(G.line(0, 0, 5, 2), 6, 3)));

  // easing
  const want = { linear: 0.5, "quad-in": 0.25, "quad-out": 0.75, "quad-inout": 0.5, "cubic-in": 0.125,
    "cubic-out": 0.875, "cubic-inout": 0.5, "sine-in": 1 - Math.SQRT1_2, "sine-out": Math.SQRT1_2, "sine-inout": 0.5 };
  ok("every easing curve gives 0 at t=0, 1 at t=1 and its value at t=0.5",
     Object.keys(G.EASE).length === 10 && Object.entries(want).every(([k, v]) =>
       Math.abs(G.EASE[k](0)) < 1e-12 && Math.abs(G.EASE[k](1) - 1) < 1e-12 && Math.abs(G.EASE[k](0.5) - v) < 1e-12));

  // morph
  const A = draw(G.ellipse(1, 1, 10, 8), 12, 10), B = draw(G.rect(3, 2, 9, 7, true), 12, 10);
  let ends = true;
  for (const blend of [G.dissolve, G.move]) {
    for (const spread of ["ordered", "seeded"]) {
      ends &&= J(blend(A, B, 0, { spread, seed: 3 })) === J(A) && J(blend(A, B, 1, { spread, seed: 3 })) === J(B);
    }
  }
  const tw = G.tween([A, G.blank(12, 10), B], 0, 2, { count: 5, ease: "cubic-inout" });
  ok("the morph's ends are A and B exactly, and the key frames stay as they were",
     ends && tw.length === 7 && J(tw[0]) === J(A) && J(tw[6]) === J(B));
  let same = true, steady = true, grows = true;
  for (const method of ["dissolve", "move"]) {
    for (const spread of ["ordered", "seeded"]) {
      const o = { method, ease: "sine-inout", spread, seed: 7 };
      same &&= J(G.morph(A, B, 6, o)) === J(G.morph(A, B, 6, { ...o }));
    }
  }
  const dis = G.morph(A, B, 9, { ease: "quad-in" });
  const toB = (f) => f.join("").split("").filter((c, i) => c === B.join("")[i]).length;
  for (let i = 0; i < dis.length; i++) {
    steady &&= dis[i].every((r, y) => [...r].every((c, x) => A[y][x] !== B[y][x] || c === A[y][x]));
    if (i) grows &&= toB(dis[i]) >= toB(dis[i - 1]);
  }
  ok("the same inputs always give the same in-betweens, for both morphs and both pixel orders", same);
  ok("a dissolve only flips pixels that differ, and each step is closer to B", steady && grows);
  ok("another seed spreads the flips differently",
     J(G.morph(A, B, 3, { spread: "seeded", seed: 1 })) !== J(G.morph(A, B, 3, { spread: "seeded", seed: 2 })));
}

// The drawing grid's cell: the container's width over the frame's, in whole device pixels, capped.
{
  const ctx = {};
  vm.createContext(ctx);
  for (const f of ["site/js/glyph-tools/glyph_anim_core.js", "site/js/glyph-tools/glyph_tools.js"]) {
    vm.runInContext(readFileSync(new URL(`../${f}`, import.meta.url), "utf8"), ctx);
  }
  const fit = ctx.GlyphTools.fitCell;
  const a = fit(800, 128), b = fit(340, 128, { dpr: 3 }), c = fit(1000, 17), d = fit(340, 128);
  ok("a 128-wide frame fills the width in whole device pixels; a 17-wide one stops at 24 px a cell",
     a.device === 6 && a.width === 768 && b.device === 7 && b.width <= 340 && b.width > 340 - 128 / 3
     && c.css === 24 && c.width === 408 && d.device === 2 && d.width === 256);
}

// Selection and fills (glyph_anim_core.js, glyph_fills_panel.js, glyph_icons.js).
{
  const ctx = {};
  vm.createContext(ctx);
  for (const f of ["site/js/glyph-tools/glyph_anim_core.js", "site/js/glyph-tools/glyph_icons.js", "site/js/glyph-tools/glyph_tools.js", "site/js/glyph-tools/glyph_fills_panel.js"]) {
    vm.runInContext(readFileSync(new URL(`../${f}`, import.meta.url), "utf8"), ctx);
  }
  const G = ctx.GlyphAnim, F = ctx.GlyphFills, T = ctx.GlyphTools, I = ctx.GlyphIcons;
  const J = JSON.stringify;
  const a = G.maskRect(6, 4, 0, 0, 2, 1), b = G.maskRect(6, 4, 2, 1, 4, 2);
  ok("selection masks: add, subtract, invert, all and none",
     J(G.maskCombine(a, b, "add")) === J(["###...", "#####.", "..###.", "......"])
     && J(G.maskCombine(a, b, "subtract")) === J(["###...", "##....", "......", "......"])
     && J(G.maskCombine(a, b, "replace")) === J(b)
     && J(G.maskInvert(a)) === J(["...###", "...###", "######", "######"])
     && G.maskEmpty(G.maskNone(6, 4)) && !G.maskEmpty(G.maskAll(6, 4)) && J(G.maskBounds(b, 6, 4)) === J([2, 1, 4, 2]));
  const ring = G.plot(G.blank(9, 9), G.rect(1, 1, 7, 7));            // a square ring, a hole inside
  const diag = ["#..", ".#.", "..#"];
  const lit = (f) => f.join("").split("#").length - 1;
  ok("the magic wand: a ring's lit pixels, its hole, the outside; 4- and 8-connected diagonals",
     J(G.wand(ring, 1, 1)) === J(ring) && lit(G.wand(ring, 4, 4)) === 25 && lit(G.wand(ring, 0, 0)) === 32
     && J(G.wand(diag, 0, 0, { connect: 4 })) === J(["#..", "...", "..."]) && J(G.wand(diag, 0, 0, { connect: 8 })) === J(diag));
  const top = G.maskRect(9, 9, 0, 0, 8, 3);
  ok("the bucket fills the area it is clicked in, and only inside the selection when there is one",
     J(G.flood(ring, 4, 4, true)) === J(G.plot(G.blank(9, 9), G.rect(1, 1, 7, 7, true)))
     && G.flood(ring, 4, 4, true, { mask: top })[5] === ring[5] && G.flood(ring, 4, 4, true, { mask: top })[2] === ".#######.");
  const blank = G.blank(16, 8);
  const bay = G.fill(blank, "bayer", { density: 0.5 });
  ok("Bayer at 50% is a checker, at 25% a quarter, at 0% none and at 100% all",
     bay.every((r, y) => [...r].every((c, x) => (c === "#") === ((x + y) % 2 === 0)))
     && lit(G.fill(blank, "bayer", { density: 0.25 })) === 32 && lit(G.fill(blank, "bayer", { density: 0 })) === 0
     && lit(G.fill(blank, "bayer", { density: 1 })) === 128);
  ok("checker, hatching and cross-hatching give their known rows",
     G.fill(blank, "checker", { size: 2 })[0] === "..##..##..##..##" && G.fill(blank, "checker", { size: 2 })[2] === "##..##..##..##.."
     && J(G.fill(blank, "hatch", { angle: 45, spacing: 4 }).slice(0, 4)) === J(["#...#...#...#...", ".#...#...#...#..", "..#...#...#...#.", "...#...#...#...#"])
     && G.fill(blank, "hatch", { angle: 0, spacing: 4 })[4] === "#".repeat(16)
     && G.fill(blank, "crosshatch", { angle: 45, spacing: 4 })[1] === ".#.#.#.#.#.#.#.#");
  const big = G.blank(64, 64);
  ok("halftone, noise and even noise come near their density, and the seed moves the noise",
     Math.abs(lit(G.fill(big, "noise", { density: 0.3, seed: 2 })) / 4096 - 0.3) < 0.03
     && Math.abs(lit(G.fill(big, "blue", { density: 0.3 })) / 4096 - 0.3) < 0.03
     && Math.abs(lit(G.fill(big, "halftone", { density: 0.3, cell: 8 })) / 4096 - 0.3) < 0.05
     && J(G.fill(blank, "noise", { density: 0.5, seed: 1 })) !== J(G.fill(blank, "noise", { density: 0.5, seed: 2 })));
  const lin = G.fill(G.blank(32, 4), "linear", { angle: 0 }), rad = G.fill(G.blank(33, 33), "radial", {});
  ok("a linear gradient is dark at its start and lit at its end; a radial one lit at the centre and dark at the corners",
     lin.every((r) => r[0] === "." && r[31] === "#") && rad[16][16] === "#" && rad[0][0] === "." && rad[32][32] === "."
     && G.fill(G.blank(32, 4), "linear", { angle: 0, invert: true }).every((r) => r[0] === "#" && r[31] === "."));
  const box = G.maskRect(16, 8, 4, 2, 11, 5), inside = G.fill(G.OPS.invert(blank), "bayer", { density: 0.5 }, box);
  const lbox = G.fill(blank, "linear", { angle: 0 }, box);
  ok("a fill stays inside the selection, and a gradient runs across the selection's bounds",
     inside.every((r, y) => [...r].every((c, x) => (box[y][x] === "#" ? c === ((x + y) % 2 === 0 ? "#" : ".") : c === "#")))
     && lbox.slice(2, 6).every((r) => r[4] === "." && r[11] === "#") && lbox[0] === blank[0]);
  let same = true;
  for (const k of G.FILLS) same &&= J(G.fill(ring, k, { density: 0.4, angle: 30, seed: 5 })) === J(G.fill(ring, k, { density: 0.4, angle: 30, seed: 5 }));
  ok("every fill gives the same pixels on a second run", same && G.FILLS.length === 9);
  const lifted = G.lift(ring, G.maskRect(9, 9, 0, 0, 4, 4));
  const moved = G.stamp(lifted.base, lifted.layer, 3, 2), back = G.stamp(lifted.base, lifted.layer, 0, 0);
  const layerAt = (f) => f.slice(2, 7).map((r) => r.slice(3, 8));
  const copied = G.lift(ring, G.maskAll(9, 9), { copy: true });
  ok("a move keeps the pixels: the layer lands whole, the frame under it stays until it drops, the mask moves too",
     J(back.frame) === J(ring) && J(layerAt(moved.frame)) === J(ring.slice(0, 5).map((r) => r.slice(0, 5)))
     && J(moved.mask) === J(G.maskRect(9, 9, 3, 2, 7, 6))
     && J(copied.base) === J(ring) && J(G.stamp(G.blank(9, 9), copied.layer).frame) === J(ring));
  const p = G.rangeParams({ density: 0, angle: 0, seed: 3 }, { density: 1, angle: 90 }, 1, 3, "linear");
  const eased = F.results([blank, blank, blank], "bayer", { density: 0 }, null, { ease: "linear", to: { density: 1 } });
  ok("over a range of frames a setting eases with t = i/(n-1): first, middle and last",
     p.density === 0.5 && p.angle === 45 && p.seed === 3 && lit(eased[0]) === 0 && lit(eased[1]) === 64 && lit(eased[2]) === 128);
  ok("every tool and toggle has a 16x16 icon and a one-letter shortcut, and no two share a key",
     [...T.TOOLS, ...T.TOGGLES].every((t) => I.ICONS[t.id]?.length === 16 && I.ICONS[t.id].every((r) => /^[.#]{16}$/.test(r)) && /^[A-Z]$/.test(t.key))
     && new Set([...T.TOOLS, ...T.TOGGLES].map((t) => t.key)).size === T.TOOLS.length + T.TOGGLES.length
     && I.iconSvg("bucket").includes('fill="currentColor"'));
}
