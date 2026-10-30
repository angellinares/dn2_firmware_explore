/**
 * The Text tool's model in site/glyph-editor.html and site/glyph-animator.html: pixel fonts and
 * text laid out as rows.
 *
 * One subject: text to pixels. A font is {name, width, height, glyphs}: each glyph is `height`
 * rows of the same length, `#` lit and `.` dark. The 3 x 5 font comes from
 * glyph_font3x5.js (generated from src/dnfw/font3x5.json); the 4 x 5 font is drawn here, our
 * own art. A font file the user loads has the shape of font3x5.json ("1" lit, "0" dark, or
 * `#` and `.`) and stays in the page. A classic script; it sets `GlyphText`.
 */
(function (root) {
  "use strict";

  /** The 4 x 5 font: uppercase, digits and basic punctuation, drawn for this editor. */
  const FONT4X5_GLYPHS = {
    " ": ["....", "....", "....", "....", "...."],
    A: [".##.", "#..#", "####", "#..#", "#..#"],
    B: ["###.", "#..#", "###.", "#..#", "###."],
    C: [".###", "#...", "#...", "#...", ".###"],
    D: ["###.", "#..#", "#..#", "#..#", "###."],
    E: ["####", "#...", "###.", "#...", "####"],
    F: ["####", "#...", "###.", "#...", "#..."],
    G: [".###", "#...", "#.##", "#..#", ".###"],
    H: ["#..#", "#..#", "####", "#..#", "#..#"],
    I: ["###.", ".#..", ".#..", ".#..", "###."],
    J: ["...#", "...#", "...#", "#..#", ".##."],
    K: ["#..#", "#.#.", "##..", "#.#.", "#..#"],
    L: ["#...", "#...", "#...", "#...", "####"],
    M: ["#..#", "####", "####", "#..#", "#..#"],
    N: ["#..#", "##.#", "#.##", "#..#", "#..#"],
    O: [".##.", "#..#", "#..#", "#..#", ".##."],
    P: ["###.", "#..#", "###.", "#...", "#..."],
    Q: [".##.", "#..#", "#..#", "#.#.", ".#.#"],
    R: ["###.", "#..#", "###.", "#.#.", "#..#"],
    S: [".###", "#...", ".##.", "...#", "###."],
    T: ["###.", ".#..", ".#..", ".#..", ".#.."],
    U: ["#..#", "#..#", "#..#", "#..#", ".##."],
    V: ["#..#", "#..#", "#..#", ".##.", ".##."],
    W: ["#..#", "#..#", "####", "####", "#..#"],
    X: ["#..#", "#..#", ".##.", "#..#", "#..#"],
    Y: ["#.#.", "#.#.", ".#..", ".#..", ".#.."],
    Z: ["####", "...#", ".##.", "#...", "####"],
    0: [".##.", "#.##", "##.#", "#..#", ".##."],
    1: [".#..", "##..", ".#..", ".#..", "###."],
    2: ["###.", "...#", ".##.", "#...", "####"],
    3: ["###.", "...#", ".##.", "...#", "###."],
    4: ["#..#", "#..#", "####", "...#", "...#"],
    5: ["####", "#...", "###.", "...#", "###."],
    6: [".##.", "#...", "###.", "#..#", ".##."],
    7: ["####", "...#", "..#.", ".#..", ".#.."],
    8: [".##.", "#..#", ".##.", "#..#", ".##."],
    9: [".##.", "#..#", ".###", "...#", ".##."],
    ".": ["....", "....", "....", "....", ".#.."],
    ",": ["....", "....", "....", ".#..", "#..."],
    ":": ["....", ".#..", "....", ".#..", "...."],
    ";": ["....", ".#..", "....", ".#..", "#..."],
    "!": [".#..", ".#..", ".#..", "....", ".#.."],
    "?": ["###.", "...#", ".##.", "....", ".#.."],
    "-": ["....", "....", "###.", "....", "...."],
    "+": ["....", ".#..", "###.", ".#..", "...."],
    "=": ["....", "###.", "....", "###.", "...."],
    "/": ["...#", "...#", "..#.", ".#..", "#..."],
    "'": [".#..", ".#..", "....", "....", "...."],
    "\"": ["#.#.", "#.#.", "....", "....", "...."],
    "(": ["..#.", ".#..", ".#..", ".#..", "..#."],
    ")": [".#..", "..#.", "..#.", "..#.", ".#.."],
    "[": [".##.", ".#..", ".#..", ".#..", ".##."],
    "]": [".##.", "..#.", "..#.", "..#.", ".##."],
    "<": ["..#.", ".#..", "#...", ".#..", "..#."],
    ">": ["#...", ".#..", "..#.", ".#..", "#..."],
    "_": ["....", "....", "....", "....", "####"],
    "%": ["#..#", "...#", ".##.", "#...", "#..#"],
    "*": ["....", "#.#.", ".#..", "#.#.", "...."],
    "#": [".#.#", "####", ".#.#", "####", ".#.#"],
  };

  /** A font from JSON-shaped data: {width?, height, glyphs: {char: rows}}, rows of "1"/"0" or
   *  "#"/".". Each glyph may have its own width. Throws an Error that names what is wrong. */
  function makeFont(data, name = "Font") {
    if (!data || typeof data !== "object" || !data.glyphs || typeof data.glyphs !== "object") {
      throw new Error("The file has no \"glyphs\" object.");
    }
    const entries = Object.entries(data.glyphs);
    if (!entries.length) throw new Error("The font has no glyphs.");
    const height = data.height ?? entries[0][1]?.length;
    if (!Number.isInteger(height) || height < 1 || height > 64) throw new Error("The font height is 1 to 64 rows.");
    const glyphs = {};
    for (const [ch, rows] of entries) {
      if ([...ch].length !== 1) throw new Error(`The glyph name "${ch}" is not one character.`);
      if (!Array.isArray(rows) || rows.length !== height) throw new Error(`The glyph "${ch}" does not have ${height} rows.`);
      const w = rows[0]?.length;
      if (!rows.every((r) => typeof r === "string" && r.length === w && /^[01#.]*$/.test(r)) || w > 128) {
        throw new Error(`The glyph "${ch}" has rows of different lengths, or characters other than 1, 0, # and .`);
      }
      glyphs[ch] = rows.map((r) => r.replace(/1/g, "#").replace(/0/g, "."));
    }
    const width = data.width ?? Math.max(...Object.values(glyphs).map((r) => r[0].length));
    return { name, width, height, glyphs };
  }

  /** A font file's text to a font; the file name (without .json) is its name. */
  function parseFont(text, filename = "font.json") {
    let data;
    try { data = JSON.parse(text); } catch { throw new Error("The file is not JSON."); }
    return makeFont(data, filename.replace(/\.json$/i, ""));
  }

  /** The glyph for a character: itself, or its uppercase form; null if the font has neither. */
  function glyphFor(font, ch) {
    return font.glyphs[ch] ?? font.glyphs[ch.toUpperCase()] ?? null;
  }

  /**
   * Text laid out in a font. `spacing`: dark columns between letters; `lineGap`: dark rows
   * between lines ("\n" starts a line). A character the font does not have takes the room
   * of a space (or the font's width) and is listed in `missing`, once each.
   * Returns {rows, width, height, missing}; rows is [] for no text.
   */
  function layout(text, font, { spacing = 1, lineGap = 1 } = {}) {
    const lines = String(text).replace(/\r/g, "").split("\n");
    const missing = [], blankWidth = (font.glyphs[" "]?.[0].length) ?? font.width;
    const placed = lines.map((line) => {
      let x = 0;
      const items = [];
      for (const ch of line) {
        const g = glyphFor(font, ch);
        if (!g && !missing.includes(ch)) missing.push(ch);
        const w = g ? g[0].length : blankWidth;
        items.push({ x, g });
        x += w + spacing;
      }
      return { items, width: Math.max(0, x - spacing) };
    });
    const width = Math.max(0, ...placed.map((l) => l.width));
    if (!width) return { rows: [], width: 0, height: 0, missing };
    const height = lines.length * font.height + (lines.length - 1) * lineGap;
    const grid = Array.from({ length: height }, () => Array(width).fill("."));
    placed.forEach((l, i) => {
      const top = i * (font.height + lineGap);
      for (const { x, g } of l.items) {
        if (!g) continue;
        g.forEach((row, y) => [...row].forEach((c, dx) => { if (c === "#") grid[top + y][x + dx] = "#"; }));
      }
    });
    return { rows: grid.map((r) => r.join("")), width, height, missing };
  }

  /** The fonts the Text tool offers, in order. The 3 x 5 font is there when its script loaded. */
  function builtInFonts() {
    const out = [];
    if (root.GlyphFont3x5) out.push({ id: "3x5", ...makeFont(root.GlyphFont3x5, "3 x 5") });
    out.push({ id: "4x5", ...makeFont({ width: 4, height: 5, glyphs: FONT4X5_GLYPHS }, "4 x 5") });
    return out;
  }

  const api = { FONT4X5_GLYPHS, makeFont, parseFont, glyphFor, layout, builtInFonts };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GlyphText = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
