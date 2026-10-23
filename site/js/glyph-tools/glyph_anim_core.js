/**
 * The model behind site/glyph-animator.html: animated 1-bit glyphs as lists of frames.
 *
 * One subject: frames as data. A frame is `height` strings of `width` characters,
 * `#` lit and `.` dark, as in site/js/mods/glyphs.js. This file reads and writes
 * the animation file (site/js/mods/glyph-anims.js), the firmware storage format,
 * and picks the frame for a knob value the way the stock firmware does.
 *
 * A classic script, so the page also works when opened from disk: in a browser it
 * sets `GlyphAnim`; under node, scripts/js_glyph_anim_check.mjs loads it with vm.
 */
(function (root) {
  "use strict";

  const LIMITS = { width: 128, height: 64, frames: 128 };
  const RANGES = { "0x7f00": 0x7f00, "0x8000": 0x8000 };
  /** The frame sizes the pickers offer, [width, height]: common sizes of the unit's frames. */
  const SIZES = [[17, 17], [19, 17], [11, 11], [128, 64]];
  /** The size of a mod glyph on the site (site/js/mods/glyphs.js). */
  const GLYPH_SIZE = 16;

  /** Whether a frame size is one the tools take: 1 to 128 wide, 1 to 64 high. */
  const sizeOk = (w, h) => Number.isInteger(w) && Number.isInteger(h) && w >= 1 && w <= LIMITS.width && h >= 1 && h <= LIMITS.height;

  /** The frame the stock picker shows: round(value x (frames - 1) / range), value = knob x 256. */
  function knobFrame(knob, frames, range = 0x7f00) {
    if (frames <= 1) return 0;
    const value = knob * 256;
    return Math.min(frames - 1, Math.floor((value * (frames - 1) + range / 2) / range));
  }

  function blank(width, height) {
    return Array.from({ length: height }, () => ".".repeat(width));
  }

  function valid(anim) {
    const { width, height, frames } = anim;
    if (!(width >= 1 && width <= LIMITS.width && height >= 1 && height <= LIMITS.height)) return false;
    if (!(frames.length >= 1 && frames.length <= LIMITS.frames)) return false;
    return frames.every((f) => f.length === height && f.every((r) => r.length === width && /^[.#]*$/.test(r)));
  }

  /* ---- the animation file ---- */

  const HEADER = `/**
 * Animated 1-bit glyphs, by name. Written by site/glyph-animator.html.
 *
 * Each animation has a frame size and a list of frames. A frame is \`height\`
 * rows of \`width\` characters, \`#\` lit and \`.\` dark. A knob value picks a
 * frame: round(value x (frames - 1) / range). Original art.
 */

export const ANIMS = {
`;

  function serialise(anims) {
    let out = HEADER;
    for (const [name, a] of Object.entries(anims)) {
      out += `  ${name}: {\n    width: ${a.width}, height: ${a.height},\n    frames: [\n`;
      for (const f of a.frames) out += "      [\n" + f.map((r) => `        "${r}",\n`).join("") + "      ],\n";
      out += "    ],\n  },\n";
    }
    return out + "};\n";
  }

  const ANIM_RE = /\n  ([A-Za-z0-9_]+): \{\n    width: (\d+), height: (\d+),\n    frames: \[\n([\s\S]*?)\n    \],\n  \},/g;

  function parse(text) {
    const out = {};
    for (const m of text.matchAll(ANIM_RE)) {
      const frames = m[4].split(/\n      \],?\n?/).filter((s) => s.includes('"'))
        .map((s) => s.match(/"([.#]*)"/g).map((q) => q.slice(1, -1)));
      out[m[1]] = { width: +m[2], height: +m[3], frames };
    }
    return out;
  }

  /** JSON in, the same model out: {name: {width, height, frames: [[rows]]}}. */
  function fromJSON(text) {
    const data = JSON.parse(text);
    for (const [name, a] of Object.entries(data)) {
      if (!valid(a)) throw new Error(`animation ${name} is not valid`);
    }
    return data;
  }

  /* ---- the firmware storage format ---- */

  /** 32-bit words per column: one up to 32 rows, the stock format; more for taller frames. */
  const wordsPerColumn = (height) => Math.ceil(height / 32);

  /** Frames as bytes: per frame, `width` columns left to right; per column, big-endian
   *  32-bit words, the most significant bit at the top row. */
  function encode(frames, width, height) {
    const wpc = wordsPerColumn(height);
    const bytes = new Uint8Array(frames.length * width * wpc * 4);
    let o = 0;
    for (const f of frames) {
      for (let x = 0; x < width; x++) {
        for (let w = 0; w < wpc; w++) {
          let word = 0;
          for (let b = 0; b < 32; b++) {
            const y = w * 32 + b;
            if (y < height && f[y][x] === "#") word |= 1 << (31 - b);
          }
          bytes[o++] = (word >>> 24) & 255; bytes[o++] = (word >>> 16) & 255;
          bytes[o++] = (word >>> 8) & 255; bytes[o++] = word & 255;
        }
      }
    }
    return bytes;
  }

  function decode(bytes, width, height) {
    const wpc = wordsPerColumn(height);
    const size = width * wpc * 4;
    if (!bytes.length || bytes.length % size) {
      throw new Error(`${bytes.length} bytes is not a whole number of ${width}x${height} frames (${size} bytes each)`);
    }
    const frames = [];
    for (let o = 0; o < bytes.length; o += size) {
      const grid = Array.from({ length: height }, () => Array(width).fill("."));
      for (let x = 0; x < width; x++) {
        for (let w = 0; w < wpc; w++) {
          const p = o + (x * wpc + w) * 4;
          const word = ((bytes[p] << 24) | (bytes[p + 1] << 16) | (bytes[p + 2] << 8) | bytes[p + 3]) >>> 0;
          for (let b = 0; b < 32; b++) {
            const y = w * 32 + b;
            if (y < height && (word >>> (31 - b)) & 1) grid[y][x] = "#";
          }
        }
      }
      frames.push(grid.map((r) => r.join("")));
    }
    return frames;
  }

  /** Hex text: one line per frame, one 8-digit word per column (and word). */
  function toHex(bytes, width, height) {
    const words = [];
    for (let p = 0; p < bytes.length; p += 4) {
      words.push([...bytes.slice(p, p + 4)].map((v) => v.toString(16).padStart(2, "0")).join(""));
    }
    const perFrame = width * wordsPerColumn(height);
    const lines = [];
    for (let i = 0; i < words.length; i += perFrame) lines.push(words.slice(i, i + perFrame).join(" "));
    return lines.join("\n");
  }

  function fromHex(text) {
    const digits = text.replace(/0x/gi, "").replace(/[^0-9a-f]/gi, "");
    if (digits.length % 8) throw new Error("the hex text is not a whole number of 32-bit words");
    return Uint8Array.from(digits.match(/../g) || [], (h) => parseInt(h, 16));
  }

  /* ---- edits ---- */

  const OPS = {
    up: (f) => [...f.slice(1), ".".repeat(f[0].length)],
    down: (f) => [".".repeat(f[0].length), ...f.slice(0, -1)],
    left: (f) => f.map((r) => r.slice(1) + "."),
    right: (f) => f.map((r) => "." + r.slice(0, -1)),
    flipx: (f) => f.map((r) => [...r].reverse().join("")),
    flipy: (f) => [...f].reverse(),
    invert: (f) => f.map((r) => r.replace(/./g, (c) => (c === "#" ? "." : "#"))),
    clear: (f) => blank(f[0].length, f.length),
  };

  /* ---- morph: dissolve and move, with easing ---- */

  /** An 8x8 Bayer matrix: 64 thresholds spread evenly over the frame. */
  const BAYER8 = (() => {
    const m = [0];
    for (let n = 1; n < 8; n *= 2) {
      const next = Array(4 * n * n);
      for (let y = 0; y < n; y++) {
        for (let x = 0; x < n; x++) {
          const v = 4 * m[y * n + x];
          const w = 2 * n;
          next[y * w + x] = v; next[y * w + x + n] = v + 2;
          next[(y + n) * w + x] = v + 3; next[(y + n) * w + x + n] = v + 1;
        }
      }
      m.length = 0; m.push(...next);
    }
    return m;
  })();

  /** A pixel's own threshold in (0, 1): ordered (Bayer 8x8) or seeded (an integer hash). */
  function threshold(x, y, spread = "ordered", seed = 1) {
    if (spread !== "seeded") return (BAYER8[(y % 8) * 8 + (x % 8)] + 0.5) / 64;
    let h = (Math.imul(x + 1, 0x9e3779b1) ^ Math.imul(y + 1, 0x85ebca77) ^ Math.imul(seed | 0, 0xc2b2ae3d)) >>> 0;
    h = Math.imul(h ^ (h >>> 16), 0x7feb352d) >>> 0;
    h = Math.imul(h ^ (h >>> 15), 0x846ca68b) >>> 0;
    return (((h ^ (h >>> 16)) >>> 0) + 0.5) / 4294967296;
  }

  const sineIn = (t) => 1 - Math.cos((t * Math.PI) / 2);
  /** Easing curves: the frame position t in 0..1 to the blend amount, 0 at 0 and 1 at 1. */
  const EASE = {
    linear: (t) => t,
    "quad-in": (t) => t * t,
    "quad-out": (t) => 1 - (1 - t) * (1 - t),
    "quad-inout": (t) => (t < 0.5 ? 2 * t * t : 1 - 2 * (1 - t) * (1 - t)),
    "cubic-in": (t) => t * t * t,
    "cubic-out": (t) => 1 - (1 - t) ** 3,
    "cubic-inout": (t) => (t < 0.5 ? 4 * t * t * t : 1 - 4 * (1 - t) ** 3),
    "sine-in": sineIn,
    "sine-out": (t) => Math.sin((t * Math.PI) / 2),
    "sine-inout": (t) => (1 - Math.cos(t * Math.PI)) / 2,
  };

  /** A dissolve from frame a to frame b at amount t in 0..1: each pixel that differs flips
   *  when t passes its own threshold, so the same inputs always give the same frame. */
  function dissolve(a, b, t, { spread = "ordered", seed = 1 } = {}) {
    if (t <= 0) return a.slice();
    if (t >= 1) return b.slice();
    return a.map((row, y) => [...row].map((c, x) =>
      (c !== b[y][x] && threshold(x, y, spread, seed) < t ? b[y][x] : c)).join(""));
  }

  const lit = (f) => f.flatMap((row, y) => [...row].flatMap((c, x) => (c === "#" ? [[x, y]] : [])));
  const nearest = (p, list) => {
    let best = list[0], d = Infinity;
    for (const q of list) {
      const e = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2;
      if (e < d) { d = e; best = q; }
    }
    return best;
  };

  /** A move from frame a to frame b at amount t: each lit pixel of a slides toward its nearest
   *  lit pixel of b, and each lit pixel of b that nothing reached comes from its nearest one in a.
   *  With no lit pixel on one side it falls back to the dissolve. */
  function move(a, b, t, opts = {}) {
    if (t <= 0) return a.slice();
    if (t >= 1) return b.slice();
    const la = lit(a), lb = lit(b);
    if (!la.length || !lb.length) return dissolve(a, b, t, opts);
    const pairs = la.map((p) => [p, nearest(p, lb)]);
    const reached = new Set(pairs.map(([, q]) => q[0] + "," + q[1]));
    for (const q of lb) if (!reached.has(q[0] + "," + q[1])) pairs.push([nearest(q, la), q]);
    const grid = a.map((r) => Array(r.length).fill("."));
    for (const [p, q] of pairs) grid[Math.round(p[1] + (q[1] - p[1]) * t)][Math.round(p[0] + (q[0] - p[0]) * t)] = "#";
    return grid.map((r) => r.join(""));
  }

  /** `count` frames from a toward b at t = i / (count + 1), eased; a and b are not included. */
  function morph(a, b, count, { method = "dissolve", ease = "linear", spread = "ordered", seed = 1 } = {}) {
    const blend = method === "move" ? move : dissolve, curve = EASE[ease] ?? EASE.linear;
    return Array.from({ length: count }, (_, i) => blend(a, b, curve((i + 1) / (count + 1)), { spread, seed }));
  }

  /** The frames between `from` and `to` replaced by `count` morph frames (by default as many
   *  as there were, at least one); returns the new list. The key frames stay as they were. */
  function tween(frames, from, to, { count = Math.max(1, to - from - 1), ...opts } = {}) {
    return [...frames.slice(0, from + 1), ...morph(frames[from], frames[to], count, opts), ...frames.slice(to)];
  }

  /* ---- shapes: integer pixel algorithms, as hand-drawn 1-bit art ---- */

  /** Bresenham's line from (x0, y0) to (x1, y1), both ends included. */
  function line(x0, y0, x1, y1) {
    const pts = [], dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx + dy;
    for (;;) {
      pts.push([x0, y0]);
      if (x0 === x1 && y0 === y1) return pts;
      const e2 = 2 * err;
      if (e2 >= dy) { err += dy; x0 += sx; }
      if (e2 <= dx) { err += dx; y0 += sy; }
    }
  }

  function rect(x0, y0, x1, y1, filled = false) {
    const pts = [];
    const [l, r] = [Math.min(x0, x1), Math.max(x0, x1)], [t, b] = [Math.min(y0, y1), Math.max(y0, y1)];
    for (let y = t; y <= b; y++) {
      for (let x = l; x <= r; x++) if (filled || y === t || y === b || x === l || x === r) pts.push([x, y]);
    }
    return pts;
  }

  /** The midpoint (Bresenham) ellipse that fits the box from (x0, y0) to (x1, y1), any size,
   *  after A. Zingl's integer form. Filled: every row spans its outline. */
  function ellipse(x0, y0, x1, y1, filled = false) {
    const pts = [];
    const put = (x, y) => pts.push([x, y]);
    let a = Math.abs(x1 - x0), b = Math.abs(y1 - y0), b1 = b & 1;
    let dx = 4 * (1 - a) * b * b, dy = 4 * (b1 + 1) * a * a, err = dx + dy + b1 * a * a;
    if (x0 > x1) { x0 = x1; x1 += a; }
    if (y0 > y1) y0 = y1;
    y0 += (b + 1) >> 1; y1 = y0 - b1;
    a *= 8 * a; b1 = 8 * b * b;
    do {
      put(x1, y0); put(x0, y0); put(x0, y1); put(x1, y1);
      const e2 = 2 * err;
      if (e2 <= dy) { y0++; y1--; err += dy += a; }
      if (e2 >= dx || 2 * err > dy) { x0++; x1--; err += dx += b1; }
    } while (x0 <= x1);
    while (y0 - y1 <= b) {
      put(x0 - 1, y0); put(x1 + 1, y0++); put(x0 - 1, y1); put(x1 + 1, y1--);
    }
    const seen = new Map();                      // one point once; and, filled, each row's span
    for (const [x, y] of pts) {
      const s = seen.get(y);
      seen.set(y, s ? [Math.min(s[0], x), Math.max(s[1], x), s[2].add(x)] : [x, x, new Set([x])]);
    }
    const out = [];
    for (const [y, [l, r, xs]] of [...seen].sort((p, q) => p[0] - q[0])) {
      if (filled) for (let x = l; x <= r; x++) out.push([x, y]);
      else for (const x of [...xs].sort((p, q) => p - q)) out.push([x, y]);
    }
    return out;
  }

  /** Shift: a line in steps of 45 degrees, a square box for a rectangle or an ellipse. */
  function constrain(tool, x0, y0, x1, y1) {
    const dx = x1 - x0, dy = y1 - y0, ax = Math.abs(dx), ay = Math.abs(dy);
    if (tool === "line") {
      if (ay * 2 < ax) return [x1, y0];
      if (ax * 2 < ay) return [x0, y1];
    }
    const d = Math.max(ax, ay);
    return [x0 + (dx < 0 ? -d : d), y0 + (dy < 0 ? -d : d)];
  }

  /** The pixels of a shape tool dragged from (x0, y0) to (x1, y1). */
  function shape(tool, x0, y0, x1, y1, { filled = false, shift = false } = {}) {
    if (shift && tool !== "pencil") [x1, y1] = constrain(tool, x0, y0, x1, y1);
    if (tool === "rect") return rect(x0, y0, x1, y1, filled);
    if (tool === "ellipse") return ellipse(x0, y0, x1, y1, filled);
    return line(x0, y0, x1, y1);
  }

  /** The frame with the points set lit (or dark); points off the frame are dropped. */
  function plot(frame, points, on = true) {
    const rows = frame.map((r) => [...r]);
    for (const [x, y] of points) if (rows[y] && x >= 0 && x < rows[y].length) rows[y][x] = on ? "#" : ".";
    return rows.map((r) => r.join(""));
  }

  /* ---- selection: a 1-bit mask the size of the frame, `#` selected ---- */

  const maskNone = (w, h) => blank(w, h);
  const maskAll = (w, h) => Array.from({ length: h }, () => "#".repeat(w));
  const maskEmpty = (m) => !m || m.every((r) => !r.includes("#"));
  const maskRect = (w, h, x0, y0, x1, y1) => plot(blank(w, h), rect(x0, y0, x1, y1, true));
  const maskInvert = (m) => m.map((r) => r.replace(/./g, (c) => (c === "#" ? "." : "#")));

  /** Combine a new selection with the old: replace, add (or) or subtract (and not). */
  function maskCombine(old, next, mode = "replace") {
    if (mode === "replace" || !old) return next.slice();
    return old.map((r, y) => [...r].map((c, x) => {
      const n = next[y][x] === "#";
      return (mode === "add" ? c === "#" || n : c === "#" && !n) ? "#" : ".";
    }).join(""));
  }

  /** The connected pixels with the same value as (x, y), 4- or 8-connected, as a mask. */
  function wand(frame, x, y, { connect = 4 } = {}) {
    const h = frame.length, w = frame[0].length, want = frame[y][x];
    const seen = Array.from({ length: h }, () => Array(w).fill(false));
    const steps = connect === 8 ? [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]]
      : [[1, 0], [-1, 0], [0, 1], [0, -1]];
    const stack = [[x, y]];
    seen[y][x] = true;
    while (stack.length) {
      const [px, py] = stack.pop();
      for (const [dx, dy] of steps) {
        const nx = px + dx, ny = py + dy;
        if (nx >= 0 && ny >= 0 && nx < w && ny < h && !seen[ny][nx] && frame[ny][nx] === want) {
          seen[ny][nx] = true; stack.push([nx, ny]);
        }
      }
    }
    return seen.map((r) => r.map((s) => (s ? "#" : ".")).join(""));
  }

  /** `result` inside the mask, `frame` outside it; with no selection, all of `result`. */
  function within(frame, result, mask) {
    if (maskEmpty(mask)) return result.slice();
    return frame.map((r, y) => [...r].map((c, x) => (mask[y][x] === "#" ? result[y][x] : c)).join(""));
  }

  /** The bounds of a mask, [x0, y0, x1, y1]; the whole frame for no selection. */
  function maskBounds(m, w, h) {
    if (maskEmpty(m)) return [0, 0, w - 1, h - 1];
    let x0 = w, y0 = h, x1 = -1, y1 = -1;
    m.forEach((r, y) => [...r].forEach((c, x) => {
      if (c === "#") { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    }));
    return [x0, y0, x1, y1];
  }

  /** Bucket: the region of (x, y)'s colour set to `on`, kept inside the mask if there is one. */
  function flood(frame, x, y, on = true, { connect = 4, mask = null } = {}) {
    const region = wand(frame, x, y, { connect });
    const limit = maskEmpty(mask) ? region : maskCombine(region, maskInvert(mask), "subtract");
    return within(frame, frame.map((r) => (on ? "#" : ".").repeat(r.length)), limit);
  }

  /** Lift the selected pixels: the layer (rows and mask) and the frame they leave behind
   *  (dark where they were, or the same frame for a copy). */
  function lift(frame, mask, { copy = false } = {}) {
    const layer = { rows: frame.map((r, y) => [...r].map((c, x) => (mask[y][x] === "#" ? c : ".")).join("")), mask: mask.slice() };
    const base = copy ? frame.slice() : within(frame, blank(frame[0].length, frame.length), mask);
    return { layer, base };
  }

  /** The layer stamped on the frame at an offset in whole cells: inside its mask it covers
   *  the frame, lit and dark alike. Returns the frame and the moved mask. */
  function stamp(frame, layer, dx = 0, dy = 0) {
    const h = frame.length, w = frame[0].length;
    const rows = frame.map((r) => [...r]), mask = blank(w, h).map((r) => [...r]);
    layer.mask.forEach((r, y) => [...r].forEach((c, x) => {
      const nx = x + dx, ny = y + dy;
      if (c === "#" && nx >= 0 && ny >= 0 && nx < w && ny < h) { rows[ny][nx] = layer.rows[y][x]; mask[ny][nx] = "#"; }
    }));
    return { frame: rows.map((r) => r.join("")), mask: mask.map((r) => r.join("")) };
  }

  /* ---- fills: patterns and gradients, the same pixels for the same settings ---- */

  // interleaved gradient noise (Jimenez 2014): a threshold with an even, blue-noise-like spread
  const ign = (x, y) => { const v = 52.9829189 * ((0.06711056 * x + 0.00583715 * y) % 1); return v - Math.floor(v); };

  const FILLS = ["bayer", "checker", "hatch", "crosshatch", "halftone", "noise", "blue", "linear", "radial"];

  /** Whether a pattern lights (x, y). `p`: density 0..1, angle in degrees, spacing, size,
   *  cell, seed, offset (moves the pattern along x), and for gradients the bounds. */
  function patternAt(kind, x, y, p) {
    const d = p.density ?? 0.5, off = Math.round(p.offset ?? 0);
    const X = x - off;
    switch (kind) {
      case "bayer": return threshold(((X % 8) + 8) % 8, y, "ordered") < d;
      case "checker": { const s = Math.max(1, p.size ?? 1); return (Math.floor(X / s) + Math.floor(y / s)) % 2 !== 0; }
      case "hatch": case "crosshatch": {
        const sp = Math.max(2, Math.round(p.spacing ?? 4));
        const one = (deg) => {          // distance across the lines, in steps of one pixel row or column
          const a = (deg * Math.PI) / 180, nx = -Math.sin(a), ny = Math.cos(a);
          const d = Math.round((X * nx + y * ny) / Math.max(Math.abs(nx), Math.abs(ny)));
          return ((d % sp) + sp) % sp === 0;
        };
        const ang = p.angle ?? 45;
        return kind === "hatch" ? one(ang) : one(ang) || one(ang + 90);
      }
      case "halftone": {
        const c = Math.max(2, Math.round(p.cell ?? 4)), r = Math.sqrt(d / Math.PI) * c;
        const cx = (Math.floor(X / c) + 0.5) * c - 0.5, cy = (Math.floor(y / c) + 0.5) * c - 0.5;
        return (X - cx) ** 2 + (y - cy) ** 2 <= r * r;
      }
      case "noise": return threshold(X & 0xffff, y, "seeded", p.seed ?? 1) < d;
      case "blue": return ign(X, y) < d;
      case "linear": case "radial": {
        const [x0, y0, x1, y1] = p.bounds;
        let v;
        if (kind === "linear") {
          const a = ((p.angle ?? 0) * Math.PI) / 180, ux = Math.cos(a), uy = Math.sin(a);
          const cs = [[x0, y0], [x1, y0], [x0, y1], [x1, y1]].map(([cx, cy]) => cx * ux + cy * uy);
          const lo = Math.min(...cs), hi = Math.max(...cs);
          v = hi > lo ? (x * ux + y * uy - lo) / (hi - lo) : 1;
        } else {
          const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, R = Math.hypot((x1 - x0) / 2, (y1 - y0) / 2) || 1;
          v = 1 - Math.hypot(x - cx, y - cy) / R;
        }
        if (p.invert) v = 1 - v;
        return v > threshold(((x % 8) + 8) % 8, y, "ordered");
      }
      default: return false;
    }
  }

  /** A fill of the selection (all of the frame with none): pattern pixels lit, others dark. */
  function fill(frame, kind, params = {}, mask = null) {
    const h = frame.length, w = frame[0].length;
    const p = { ...params, bounds: params.bounds ?? maskBounds(mask, w, h) };
    const result = Array.from({ length: h }, (_, y) => Array.from({ length: w }, (_, x) =>
      (patternAt(kind, x, y, p) ? "#" : ".")).join(""));
    return within(frame, result, mask);
  }

  /** The settings for frame i of n in a range: each number in `to` eased from its value in `from`. */
  function rangeParams(from, to, i, n, ease = "linear") {
    const t = n > 1 ? i / (n - 1) : 1, e = (EASE[ease] ?? EASE.linear)(t);
    const out = { ...from };
    for (const [k, v] of Object.entries(to ?? {})) if (typeof v === "number" && typeof from[k] === "number") out[k] = from[k] + (v - from[k]) * e;
    return out;
  }

  /** Change the frame size, keeping the top-left pixels. */
  function resize(frame, width, height) {
    return Array.from({ length: height }, (_, y) =>
      (frame[y] ?? "").slice(0, width).padEnd(width, "."));
  }

  /* ---- the still glyphs (site/js/mods/glyphs.js) ---- */

  const STILL_RE = /\n  (?:\/\/[^\n]*\n  )?([a-z0-9]+): \[\n((?:    "[.#]+",\n)+)  \],/g;

  /** The still glyphs by mod id, read from the text of glyphs.js. */
  function parseStill(text) {
    const at = text.indexOf("export const GLYPHS = {");
    const body = at < 0 ? "" : text.slice(at);
    const out = {};
    for (const m of ("\n" + body).matchAll(STILL_RE)) out[m[1]] = m[2].match(/[.#]+/g);
    return out;
  }

  /** A frame as hex for a URL: each row as hex digits of 4 pixels, rows joined by "-". */
  function rowsToHex(rows) {
    return rows.map((r) => r.padEnd(Math.ceil(r.length / 4) * 4, ".").match(/.{4}/g)
      .map((q) => parseInt(q.replace(/#/g, "1").replace(/\./g, "0"), 2).toString(16)).join("")).join("-");
  }

  function hexToRows(hex, width) {
    const rows = hex.split("-").map((h) => [...h].map((d) => parseInt(d, 16).toString(2).padStart(4, "0")).join("")
      .replace(/1/g, "#").replace(/0/g, ".").slice(0, width));
    return rows.every((r) => r.length === width && /^[.#]+$/.test(r)) ? rows : null;
  }

  /* ---- rows as text, for copy and paste ---- */

  /** Text to blocks of rows: blocks are separated by blank lines. Only `#` and `.` are
   *  allowed; anything else gives {error} naming the line and the character. */
  function parseBlocks(text) {
    const blocks = [];
    let block = [];
    const lines = text.replace(/\r/g, "").split("\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (!line) { if (block.length) blocks.push(block); block = []; continue; }
      const bad = line.match(/[^.#]/);
      if (bad) return { error: `Line ${i + 1} has "${bad[0]}". Use only # and .` };
      block.push(line);
    }
    if (block.length) blocks.push(block);
    if (!blocks.length) return { error: "There are no rows to use." };
    return { blocks };
  }

  /** Rows of any size to a width x height frame at the top left; `trimmed` when some did not fit. */
  function fitRows(rows, width, height) {
    const trimmed = rows.length > height || rows.some((r) => r.length > width);
    return { frame: resize(rows, width, height), trimmed };
  }

  const framesText = (frames) => frames.map((f) => f.join("\n")).join("\n\n");

  /* ---- animated GIF ---- */

  const GIF_COLOURS = { light: { bg: [0xf6, 0xf5, 0xf2], ink: [0x16, 0x18, 0x1c] },
                        dark: { bg: [0x0c, 0x0d, 0x0f], ink: [0xe8, 0xe6, 0xe1] } };

  /** GIF89a delay in hundredths of a second for a speed in frames a second (browsers slow down below 2). */
  const gifDelay = (fps) => Math.max(2, Math.round(100 / Math.max(1, fps)));

  /** LZW of 2-colour indices, code size 2, cut into sub-blocks of 255 bytes. */
  function lzw(indices) {
    const MIN = 2, CLEAR = 4, EOI = 5;
    const out = [];
    let acc = 0, bits = 0, size = MIN + 1, next = EOI + 1, table = new Map();
    const emit = (code) => {
      acc |= code << bits; bits += size;
      while (bits >= 8) { out.push(acc & 255); acc >>>= 8; bits -= 8; }
    };
    emit(CLEAR);
    let prefix = indices[0];
    for (let i = 1; i < indices.length; i++) {
      const k = indices[i], key = (prefix << 8) | k, code = table.get(key);
      if (code !== undefined) { prefix = code; continue; }
      emit(prefix);
      if (next === 4096) { emit(CLEAR); table = new Map(); next = EOI + 1; size = MIN + 1; }
      else { if (next >= 1 << size) size++; table.set(key, next++); }
      prefix = k;
    }
    emit(prefix);
    emit(EOI);
    if (bits > 0) out.push(acc & 255);
    const blocks = [MIN];
    for (let p = 0; p < out.length; p += 255) {
      const chunk = out.slice(p, p + 255);
      blocks.push(chunk.length, ...chunk);
    }
    blocks.push(0);
    return blocks;
  }

  /** The frames as an animated GIF: 2 colours, each pixel `scale` x `scale`, looping forever. */
  function gif(frames, width, height, { scale = 1, theme = "light", delay = 8 } = {}) {
    const W = width * scale, H = height * scale, c = GIF_COLOURS[theme];
    const le = (v) => [v & 255, (v >> 8) & 255];
    const bytes = [..."GIF89a"].map((ch) => ch.charCodeAt(0));
    bytes.push(...le(W), ...le(H), 0x80, 0, 0, ...c.bg, ...c.ink);
    bytes.push(0x21, 0xff, 11, ...[..."NETSCAPE2.0"].map((ch) => ch.charCodeAt(0)), 3, 1, 0, 0, 0);
    for (const f of frames) {
      bytes.push(0x21, 0xf9, 4, 0x04, ...le(delay), 0, 0);
      bytes.push(0x2c, 0, 0, 0, 0, ...le(W), ...le(H), 0);
      const idx = new Uint8Array(W * H);
      for (let y = 0; y < H; y++) {
        const row = f[(y / scale) | 0];
        for (let x = 0; x < W; x++) idx[y * W + x] = row[(x / scale) | 0] === "#" ? 1 : 0;
      }
      const data = lzw(idx);
      for (let i = 0; i < data.length; i++) bytes.push(data[i]);
    }
    bytes.push(0x3b);
    return Uint8Array.from(bytes);
  }

  const api = { SIZES, GLYPH_SIZE, sizeOk, gif, gifDelay, GIF_COLOURS, parseBlocks, fitRows, framesText, LIMITS, RANGES, knobFrame, blank, valid, serialise, parse, fromJSON, wordsPerColumn,
    encode, decode, toHex, fromHex, OPS, dissolve, tween, resize, parseStill, rowsToHex, hexToRows,
    threshold, EASE, move, morph, line, rect, ellipse, constrain, shape, plot,
    maskNone, maskAll, maskEmpty, maskRect, maskInvert, maskCombine, maskBounds, wand, within, flood,
    lift, stamp, FILLS, patternAt, fill, rangeParams };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GlyphAnim = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
