/**
 * The Fills card that site/glyph-editor.html and site/glyph-animator.html share.
 *
 * One subject: a form for one fill, a preview of what it gives, and Apply. The fill goes in
 * the selection, or in all of the frame when nothing is selected. Over several frames (the
 * animator's frame range) a number can ease from its start value to an end value with the
 * core's curves: frame i of n uses t = i / (n - 1). The pixels come from GlyphAnim.fill, so
 * the same settings always give the same frames. A classic script; it sets `GlyphFills`.
 */
(function (root) {
  "use strict";

  const KINDS = [["bayer", "Bayer dither"], ["checker", "Checker"], ["hatch", "Hatching"], ["crosshatch", "Cross-hatching"],
    ["halftone", "Halftone dots"], ["noise", "Noise"], ["blue", "Even noise"], ["linear", "Linear gradient"], ["radial", "Radial gradient"]];
  const USES = {                                   // the settings each fill reads
    bayer: ["density", "offset"], checker: ["size", "offset"], hatch: ["angle", "spacing", "offset"],
    crosshatch: ["angle", "spacing", "offset"], halftone: ["density", "cell", "offset"], noise: ["density", "seed", "offset"],
    blue: ["density", "offset"], linear: ["angle", "start", "end", "curve", "invert"], radial: ["start", "end", "curve", "invert"],
  };
  const EASED = ["density", "angle", "offset", "start", "end"];   // the settings that can change across frames
  const PERCENT = ["density", "start", "end"];     // 0..1 here, 0..100 % on the page
  const LIMITS = { density: [0, 1, 0.05], angle: [-180, 180, 15], spacing: [2, 16, 1], cell: [2, 16, 1],
    size: [1, 16, 1], seed: [1, 9999, 1], offset: [-64, 64, 1], start: [0, 1, 0.05], end: [0, 1, 0.05] };
  const LABELS = { density: "Density", angle: "Angle", spacing: "Spacing", cell: "Cell", size: "Size", seed: "Seed", offset: "Offset", invert: "Lit to dark",
    start: "Start", end: "End", curve: "Curve" };
  const curveName = (k) => root.GlyphTools?.CURVE_NAMES?.[k] ?? k;

  /** The frames a fill gives: `targets` are rows, one per frame; settings `from`, eased toward `to`. */
  function results(targets, kind, from, mask, { ease = null, to = {} } = {}) {
    const G = root.GlyphAnim, n = targets.length;
    return targets.map((rows, i) => G.fill(rows, kind, ease ? G.rangeParams(from, to, i, n, ease) : from, mask));
  }

  /**
   * Builds the card into `box`. `o`: targets() the frames to fill (rows each), mask() the
   * selection or null, apply(frames) to store them as one undo step, thumb(canvas, rows) to draw.
   * Returns { refresh() } for the page to call when the frames or the selection change.
   */
  function panel(box, o) {
    const doc = box.ownerDocument;
    const v = { kind: "bayer", density: 0.5, angle: 45, spacing: 4, cell: 4, size: 1, seed: 1, offset: 0, invert: false,
      start: 0, end: 1, curve: "linear" };
    const last = { density: 1, angle: 135, offset: 8, start: 0, end: 1 };   // the values at the last frame of a range
    let ease = false, curve = "linear";
    const el = (tag, props = {}, ...kids) => { const n = Object.assign(doc.createElement(tag), props); n.append(...kids); return n; };
    const form = el("div", { className: "fill-form" }), range = el("div", { className: "fill-range" });
    const preview = el("div", { className: "fill-preview" }), apply = el("button", { type: "button", className: "primary", textContent: "Apply" });
    const note = el("p", { className: "muted fill-note" });
    box.replaceChildren(form, range, preview, el("div", { className: "bar" }, apply), note);

    function field(key, value, onset, id) {
      if (key === "invert") {
        const c = el("input", { type: "checkbox", checked: value });
        c.dataset.fill = id ?? key;
        c.onchange = () => { onset(c.checked); refresh(); };
        return el("label", {}, c, " " + LABELS[key]);
      }
      if (key === "curve") {
        const sel = el("select", {}, ...Object.keys(root.GlyphAnim.EASE).map((k) => el("option", { value: k, textContent: curveName(k), selected: k === value })));
        sel.setAttribute("aria-label", "Curve"); sel.dataset.fill = id ?? key;
        sel.onchange = () => { onset(sel.value); refresh(); };
        return el("label", {}, LABELS[key] + " ", sel);
      }
      const [min, max, step] = LIMITS[key];
      const pct = PERCENT.includes(key);
      const input = el("input", { type: "number", min, max, step, value: pct ? Math.round(value * 100) : value });
      if (pct) { input.min = 0; input.max = 100; input.step = 5; }
      input.dataset.fill = id ?? key;
      input.oninput = () => {
        let x = +input.value;
        if (!Number.isFinite(x)) return;
        if (pct) x /= 100;
        onset(Math.max(min, Math.min(max, x)));
        refresh();
      };
      return el("label", {}, LABELS[key] + (pct ? " %" : "") + " ", input);
    }
    function build() {
      const kind = el("select", {}, ...KINDS.map(([k, n]) => el("option", { value: k, textContent: n, selected: k === v.kind })));
      kind.setAttribute("aria-label", "Fill");
      kind.dataset.fill = "kind";
      kind.onchange = () => { v.kind = kind.value; build(); refresh(); };
      form.replaceChildren(kind, ...USES[v.kind].map((k) => field(k, v[k], (x) => { v[k] = x; })));
      const n = o.targets().length, eased = USES[v.kind].filter((k) => EASED.includes(k));
      range.hidden = n < 2 || !eased.length;
      if (range.hidden) return;
      const toggle = el("input", { type: "checkbox", checked: ease });
      toggle.dataset.fill = "ease-on";
      toggle.onchange = () => { ease = toggle.checked; build(); refresh(); };
      const kids = [el("label", {}, toggle, ` Change across the ${n} frames`)];
      if (ease) {
        const sel = el("select", {}, ...Object.keys(root.GlyphAnim.EASE).map((k) => el("option", { value: k, textContent: curveName(k), selected: k === curve })));
        sel.setAttribute("aria-label", "Easing"); sel.dataset.fill = "ease";
        sel.onchange = () => { curve = sel.value; refresh(); };
        kids.push(sel, ...eased.map((k) => field(k, last[k], (x) => { last[k] = x; }, "end-" + k)));
      }
      range.replaceChildren(el("div", { className: "bar" }, ...kids));
    }
    function compute() {
      const targets = o.targets();
      return results(targets, v.kind, v, o.mask(), ease && targets.length > 1 ? { ease: curve, to: last } : {});
    }
    function refresh() {
      const targets = o.targets();
      if (range.hidden !== (targets.length < 2 || !USES[v.kind].some((k) => EASED.includes(k)))) build();
      const out = compute();
      preview.replaceChildren(...out.map((rows) => { const c = el("canvas", { className: "px" }); o.thumb(c, rows); return c; }));
      note.textContent = `${o.mask() ? "Inside the selection" : "All of the frame"}, on ${targets.length} frame${targets.length === 1 ? "" : "s"}.`;
    }
    apply.onclick = () => o.apply(compute());
    build(); refresh();
    return { refresh, settings: v, end: last, get ease() { return ease ? curve : null; } };
  }

  const api = { KINDS, USES, results, panel };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GlyphFills = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
