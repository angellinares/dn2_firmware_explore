/**
 * The Controls tool's model in site/glyph-editor.html and site/glyph-animator.html: glyphs of
 * hardware-style controls, drawn by code from their settings.
 *
 * One subject: settings to rows. Each generator takes plain numbers and names and gives rows,
 * `#` lit and `.` dark, as small as the control: a knob (a ring or a disc, an indicator line,
 * an arc of the value), a slider (across or upright, a filled bar or a handle on a track), a
 * button (off as an outline, on filled) and a switch (a sliding switch or a check box). The
 * same settings always give the same pixels. No stock glyph is used: the shapes come from the
 * core's line, rectangle and ellipse. A classic script; it sets `GlyphControls`.
 */
(function (root) {
  "use strict";

  const KINDS = [["knob", "Knob"], ["slider", "Slider"], ["button", "Button"], ["switch", "Switch"]];
  /** The default settings of each kind; the context bar edits a copy. */
  const DEFAULTS = {
    knob: { size: 15, value: 0.6, body: "ring", mark: "both" },
    slider: { orient: "h", length: 32, thick: 7, value: 0.6, style: "fill" },
    button: { w: 11, h: 7, on: true, round: true },
    switch: { style: "slide", w: 13, h: 7, on: true },
  };
  /** The knob's sweep: 270 degrees, clockwise from lower left, as angles from straight up. */
  const SWEEP = { start: -135, span: 270 };

  const clamp01 = (v) => Math.max(0, Math.min(1, +v || 0));
  const int = (v, lo, hi) => Math.max(lo, Math.min(hi, Math.round(+v || 0)));
  const grid = (w, h) => Array.from({ length: h }, () => Array(w).fill("."));
  const rowsOf = (g) => g.map((r) => r.join(""));
  function put(g, pts, on = true) {
    for (const [x, y] of pts) if (g[y] && x >= 0 && x < g[y].length) g[y][x] = on ? "#" : ".";
  }
  /** The angle of (x, y) seen from (cx, cy), in degrees clockwise from straight up, -180..180. */
  const angleOf = (x, y, cx, cy) => (Math.atan2(x - cx, cy - y) * 180) / Math.PI;

  /**
   * A knob `size` pixels square (5 to 64). `value` 0..1 turns it through 270 degrees, from lower
   * left to lower right. `body`: "ring" (an outline) or "disc" (filled, its line dark).
   * `mark`: "line" (from the centre toward the rim), "arc" (an outer arc, solid up to the
   * value and dotted after it) or "both". With an arc the body is smaller, inside it.
   */
  function knob({ size = 15, value = 0.5, body = "ring", mark = "both" } = {}) {
    const G = root.GlyphAnim, n = int(size, 5, 64), v = clamp01(value), g = grid(n, n);
    const c = (n - 1) / 2, arc = mark === "arc" || mark === "both", line = mark === "line" || mark === "both";
    const angle = SWEEP.start + SWEEP.span * v;
    // the arc: the outline of the full circle, kept where it lies in the sweep
    if (arc) {
      for (const [x, y] of G.ellipse(0, 0, n - 1, n - 1)) {
        const a = angleOf(x, y, c, c);
        if (a < SWEEP.start - 1e-9 || a > SWEEP.start + SWEEP.span + 1e-9) continue;
        if (a <= angle + 1e-9 || (x + y) % 2 === 0) g[y][x] = "#";
      }
    }
    // the body: the whole knob, or a circle 2 pixels inside the arc (none when too small)
    const inset = arc ? 2 : 0, bn = n - 2 * inset;
    if (bn >= 5) {
      const pts = G.ellipse(inset, inset, n - 1 - inset, n - 1 - inset, body === "disc");
      put(g, pts);
    }
    // the indicator: from the centre (a ring) or near it (a disc) out to 1 pixel inside the body
    if (line) {
      const r = bn >= 5 ? (bn - 1) / 2 - 1 : (n - 1) / 2 - 1;
      const dx = Math.sin((angle * Math.PI) / 180), dy = -Math.cos((angle * Math.PI) / 180);
      const r0 = body === "disc" && bn >= 5 ? Math.min(1, r) : 0;
      const pts = G.line(Math.round(c + dx * r0), Math.round(c + dy * r0), Math.round(c + dx * r), Math.round(c + dy * r));
      put(g, pts, !(body === "disc" && bn >= 5));
    }
    return rowsOf(g);
  }

  /** The rows turned a quarter, so a slider across becomes one upright with its 0 at the bottom. */
  const upright = (rows) => Array.from({ length: rows[0].length }, (_, y) =>
    rows.map((r) => r[rows[0].length - 1 - y]).join(""));

  /**
   * A slider `length` pixels long (5 to 128) and `thick` across (3 to 16). `orient`: "h" (0 at
   * the left) or "v" (0 at the bottom). `style`: "fill" (a frame, filled up to the value, with a
   * dark gap inside the frame when there is room) or "handle" (a track line and a 3 pixel handle,
   * with a dark pixel each side of it on the track).
   */
  function slider({ orient = "h", length = 32, thick = 7, value = 0.5, style = "fill" } = {}) {
    const G = root.GlyphAnim, L = int(length, 5, 128), T = int(thick, 3, 16), v = clamp01(value), g = grid(L, T);
    if (style === "handle") {
      const mid = Math.floor((T - 1) / 2), hw = Math.min(3, L), x = Math.round((L - hw) * v);
      put(g, G.line(0, mid, L - 1, mid));
      if (T % 2 === 0) put(g, G.line(0, mid + 1, L - 1, mid + 1));
      put(g, [[x - 1, mid], [x + hw, mid], [x - 1, mid + 1], [x + hw, mid + 1]], false);
      put(g, G.rect(x, 0, x + hw - 1, T - 1, true));
    } else {
      put(g, G.rect(0, 0, L - 1, T - 1));
      const gap = T >= 5 && L >= 7 ? 1 : 0, x0 = 1 + gap, room = L - 2 * x0, fill = Math.round(room * v);
      if (fill > 0) put(g, G.rect(x0, x0, x0 + fill - 1, T - 1 - x0, true));
    }
    const rows = rowsOf(g);
    return orient === "v" ? upright(rows) : rows;
  }

  /** The four corner pixels of a w x h box, for rounded corners. */
  const corners = (w, h) => [[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]];

  /**
   * A button `w` x `h` (3 to 64 by 3 to 64): off is an outline, on is filled. `round` leaves
   * out the corner pixels.
   */
  function button({ w = 11, h = 7, on = true, round = true } = {}) {
    const G = root.GlyphAnim, W = int(w, 3, 64), H = int(h, 3, 64), g = grid(W, H);
    put(g, G.rect(0, 0, W - 1, H - 1, !!on));
    if (round) put(g, corners(W, H), false);
    return rowsOf(g);
  }

  /**
   * A switch with two states. `style` "slide": a track `w` x `h` (7 to 64 by 5 to 32) with
   * rounded corners and a square knob, at the left when off and at the right when on; on, the
   * track is filled and the knob has a dark ring. `style` "box": a check box `h` pixels square (5 to 32),
   * empty when off and with a tick when on.
   */
  function toggle({ style = "slide", w = 13, h = 7, on = true } = {}) {
    const G = root.GlyphAnim;
    if (style === "box") {
      const s = int(h, 5, 32), g = grid(s, s);
      put(g, G.rect(0, 0, s - 1, s - 1));
      if (on) {
        // a tick: down from the left third to the bottom, then up to the top right, 2 inside the box
        const a = [2, Math.round((s - 1) / 2)], b = [Math.round((s - 1) * 0.4), s - 3], c = [s - 3, 2];
        put(g, [...G.line(a[0], a[1], b[0], b[1]), ...G.line(b[0], b[1], c[0], c[1])]);
      }
      return rowsOf(g);
    }
    const H = int(h, 5, 32), W = Math.max(int(w, 7, 64), H + 2), g = grid(W, H), k = H - 4;
    put(g, G.rect(0, 0, W - 1, H - 1));
    put(g, corners(W, H), false);
    const x = on ? W - 2 - k : 2;
    // on, the track fills and a dark ring keeps the knob apart from it
    if (on) { put(g, G.rect(1, 1, W - 2, H - 2, true)); put(g, G.rect(x - 1, 1, x + k, H - 2), false); }
    put(g, G.rect(x, 2, x + k - 1, H - 3, true));
    return rowsOf(g);
  }

  /** The rows of a control: `kind` is one of KINDS, `p` its settings (DEFAULTS fill the rest). */
  function control(kind, p = {}) {
    const s = { ...DEFAULTS[kind], ...p };
    if (kind === "knob") return knob(s);
    if (kind === "slider") return slider(s);
    if (kind === "button") return button(s);
    if (kind === "switch") return toggle(s);
    throw new Error(`no control "${kind}"`);
  }

  /** The number of lit pixels in rows. */
  const litCount = (rows) => rows.reduce((n, r) => n + (r.match(/#/g)?.length ?? 0), 0);

  const api = { KINDS, DEFAULTS, SWEEP, knob, slider, button, toggle, control, litCount };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GlyphControls = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
