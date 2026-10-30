/**
 * The drawing surface that site/glyph-editor.html and site/glyph-animator.html share.
 *
 * One subject: turning the pointer and the keyboard into frames. It holds the tool bar (icons
 * from glyph_icons.js, in groups), the context bar for the active tool, the shortcut help, the
 * selection (a 1-bit mask with its own small undo), the floating layer of a move and the
 * clipboard, and it draws the frame on a canvas that fills its column. The Text and Controls
 * tools show their rows under the pointer and stamp them on a click. The pixels come from
 * glyph_anim_core.js, glyph_text.js and glyph_controls.js; this file holds no geometry. A
 * classic script, so the pages also work when opened from disk; it sets `GlyphTools`.
 */
(function (root) {
  "use strict";

  const TOOLS = [
    { id: "pencil", name: "Pencil", key: "B", group: "Draw" },
    { id: "line", name: "Line", key: "L", group: "Shapes" },
    { id: "rect", name: "Rectangle", key: "R", group: "Shapes" },
    { id: "ellipse", name: "Ellipse", key: "E", group: "Shapes" },
    { id: "select", name: "Select rectangle", key: "M", group: "Select" },
    { id: "wand", name: "Magic wand", key: "W", group: "Select" },
    { id: "move", name: "Move", key: "V", group: "Select" },
    { id: "bucket", name: "Bucket fill", key: "G", group: "Fill" },
    { id: "pattern", name: "Pattern fill", key: "P", group: "Fill" },
    { id: "gradient", name: "Gradient", key: "D", group: "Fill" },
    { id: "text", name: "Text", key: "T", group: "Stamp" },
    { id: "control", name: "Controls", key: "K", group: "Stamp" },
  ];
  const TOGGLES = [
    { id: "erase", name: "Erase", key: "X", group: "Draw" },
    { id: "filled", name: "Filled shapes", key: "F", group: "Shapes" },
  ];
  const GROUPS = ["Draw", "Shapes", "Select", "Fill", "Stamp"];
  /** The tools that stamp rows on a click: the rows follow the pointer until then. */
  const STAMPS = ["text", "control"];
  const PATTERNS = [["bayer", "Bayer"], ["checker", "Checker"], ["hatch", "Hatching"], ["crosshatch", "Cross-hatching"],
    ["halftone", "Halftone dots"], ["noise", "Noise"], ["blue", "Even noise"]];
  const SHORTCUTS = [
    ...TOOLS.map((t) => [t.key, t.name]), ...TOGGLES.map((t) => [t.key, t.name + " on or off"]),
    ["Shift-drag", "Square, circle or 45-degree line; with a select tool, add to the selection"],
    ["Alt-drag", "Subtract from the selection; with Move, copy"],
    ["Right button", "Draw dark pixels; with Text or Controls, stamp dark"],
    ["Ctrl+A", "Select all"], ["Ctrl+D", "Deselect"], ["Ctrl+Shift+I", "Invert the selection"],
    ["Ctrl+Alt+Z", "Undo the selection"], ["Ctrl+X, C, V", "Cut, copy, paste"], ["Delete", "Clear the selection"],
    ["Arrow keys", "Move the selection one cell"], ["Enter", "Drop the moved pixels"], ["Escape", "Cancel the move, or deselect"],
    ["Ctrl+Z", "Undo"], ["?", "This help"],
  ];

  /** The names of the easing curves in the lists. */
  const CURVE_NAMES = { linear: "Linear", "quad-in": "Quadratic in", "quad-out": "Quadratic out", "quad-inout": "Quadratic in-out",
    "cubic-in": "Cubic in", "cubic-out": "Cubic out", "cubic-inout": "Cubic in-out",
    "sine-in": "Sine in", "sine-out": "Sine out", "sine-inout": "Sine in-out" };

  let clipboard = null;                       // {rows, mask}: shared by every frame on the page

  /* ---- a drag that draws (pencil and shapes) ---- */

  /** A drag that starts at cell (x, y) on `frame`: move(x, y, shift) gives the frame to show
   *  while dragging, and `frame` at the end is the result. One drag is one undo step. */
  function drag(state, frame, x, y, { button = 0 } = {}) {
    const G = root.GlyphAnim;
    const erase = state.erase || button === 2;
    const base = frame;
    // the pencil keeps its old habit: the first pixel sets the colour, unless erasing
    const on = state.tool === "pencil" ? !erase && base[y][x] !== "#" : !erase;
    let last = [x, y], current = G.plot(base, [[x, y]], on);
    return {
      on,
      get frame() { return current; },
      move(nx, ny, shift = false) {
        if (state.tool === "pencil") {
          current = G.plot(current, G.line(last[0], last[1], nx, ny), on);
          last = [nx, ny];
        } else {
          current = G.plot(base, G.shape(state.tool, x, y, nx, ny, { filled: state.filled, shift }), on);
        }
        return current;
      },
    };
  }

  /** The size of one cell of a drawing grid `cells` wide in a container `room` CSS pixels wide:
   *  whole device pixels so every cell is the same square, at most `max` CSS pixels, at least
   *  one device pixel. Returns {device, css, width} (width: the grid's CSS width). */
  function fitCell(room, cells, { max = 24, dpr = 1 } = {}) {
    const device = Math.max(1, Math.min(Math.floor(max * dpr), Math.floor((room * dpr) / cells)));
    return { device, css: device / dpr, width: (device * cells) / dpr };
  }

  /** Where a stamp's rows go for the cell under the pointer: text has its top left there, a
   *  control its centre. Returns [x, y], the top left corner. */
  function stampOrigin(tool, rows, x, y) {
    if (tool !== "control" || !rows.length) return [x, y];
    return [x - Math.floor((rows[0].length - 1) / 2), y - Math.floor((rows.length - 1) / 2)];
  }

  /** The content width of an element: its width without padding. */
  function contentWidth(el) {
    const s = el.ownerDocument.defaultView.getComputedStyle(el);
    return el.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight);
  }

  /** The edges of a mask, as [x0, y0, x1, y1] cell-corner segments, each with its parity. */
  function maskEdges(mask) {
    const out = [], h = mask.length, w = mask[0].length, on = (x, y) => y >= 0 && y < h && x >= 0 && x < w && mask[y][x] === "#";
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        if (!on(x, y)) continue;
        if (!on(x, y - 1)) out.push([x, y, x + 1, y]);
        if (!on(x, y + 1)) out.push([x, y + 1, x + 1, y + 1]);
        if (!on(x - 1, y)) out.push([x, y, x, y + 1]);
        if (!on(x + 1, y)) out.push([x + 1, y, x + 1, y + 1]);
      }
    }
    return out;
  }

  /**
   * The surface. `o`:
   *   canvas, toolbar, context, help: the elements it fills (help: the popover's container);
   *   frame(): the frame to edit (rows); set(rows): show rows now, not an undo step;
   *   begin(): store an undo step; end(): an edit is over (the page saves and redraws);
   *   undo(): the page's undo; onion(): the frame to show faintly, or null; max: cell size cap;
 *   selected(): the selection changed.
   */
  function surface(o) {
    const G = root.GlyphAnim, I = root.GlyphIcons, doc = o.canvas.ownerDocument, win = doc.defaultView;
    const state = { tool: "pencil", erase: false, filled: false, connect: 4, mode: "replace",
      pattern: { kind: "bayer", density: 0.5, angle: 45, spacing: 4, cell: 4, size: 1, seed: 1 },
      gradient: { kind: "linear", invert: false, start: 0, end: 1, curve: "linear" },
      text: { text: "TEXT", font: "3x5", spacing: 1 }, opaque: false,
      control: { kind: "knob", ...structuredClone(root.GlyphControls.DEFAULTS) } };
    const T = root.GlyphText, C = root.GlyphControls;
    const fonts = T.builtInFonts();               // a font file the user loads joins this list, in this page only
    let mask = null, maskUndo = [], float = null, gesture = null, lastCell = null, moved = false, hover = null;
    const size = () => { const f = o.frame(); return [f[0].length, f.length]; };
    const css = (v) => win.getComputedStyle(doc.documentElement).getPropertyValue(v).trim();

    /* -- selection -- */
    function setMask(next, { record = true } = {}) {
      if (record) { maskUndo.push(mask); if (maskUndo.length > 50) maskUndo.shift(); }
      mask = next && !G.maskEmpty(next) ? next : null;
      render();
      o.selected?.();
    }
    const selectAll = () => { drop(); setMask(G.maskAll(...size())); };
    const deselect = () => { drop(); if (mask) setMask(null); };
    const invertSel = () => { drop(); setMask(mask ? G.maskInvert(mask) : G.maskAll(...size())); };
    const undoSel = () => { drop(); if (maskUndo.length) setMask(maskUndo.pop(), { record: false }); };

    /* -- the floating layer of a move or a paste: one undo step from lift to drop -- */
    function liftNow(copy) {
      if (float) return;
      const [w, h] = size();
      const m = mask ?? G.maskAll(w, h);
      o.begin();
      const { layer, base } = G.lift(o.frame(), m, { copy });
      float = { layer, base, dx: 0, dy: 0, start: o.frame() };
      showFloat();
    }
    function showFloat() {
      const s = G.stamp(float.base, float.layer, float.dx, float.dy);
      mask = G.maskEmpty(s.mask) ? null : s.mask;
      o.set(s.frame);
      render();
    }
    function nudge(dx, dy) { float.dx += dx; float.dy += dy; showFloat(); }
    function drop() { if (!float) return; float = null; o.end(); render(); }
    function cancelFloat() {
      if (!float) return;
      const start = float.start, m = float.layer.mask;
      float = null; mask = G.maskEmpty(m) ? null : m;
      o.set(start); o.end(); render();
    }
    function copySel() {
      drop();
      const [w, h] = size(), m = mask ?? G.maskAll(w, h);
      clipboard = G.lift(o.frame(), m, { copy: true }).layer;
    }
    function clearSel() {
      drop();
      const [w, h] = size(), m = mask ?? G.maskAll(w, h);
      o.begin(); o.set(G.within(o.frame(), G.blank(w, h), m)); o.end();
    }
    function cutSel() { copySel(); clearSel(); }
    function paste() {
      if (!clipboard) return;
      drop();
      const [w, h] = size();
      const layer = { rows: G.resize(clipboard.rows, w, h), mask: G.resize(clipboard.mask, w, h) };
      o.begin();
      float = { layer, base: o.frame(), dx: 0, dy: 0, start: o.frame() };
      showFloat();
    }

    /* -- the stamp tools: Text and Controls -- */
    const fontNow = () => fonts.find((f) => f.id === state.text.font) ?? fonts[0];
    /** The rows the active stamp tool places, or [] (no text, or another tool). */
    function stampRows() {
      if (state.tool === "text") return T.layout(state.text.text, fontNow(), { spacing: state.text.spacing }).rows;
      if (state.tool === "control") return C.control(state.control.kind, state.control[state.control.kind]);
      return [];
    }
    /** The frame a click at cell p gives: the rows placed at p, lit (or dark when erasing). */
    function stamped(frame, p, dark) {
      const rows = stampRows();
      if (!rows.length) return frame;
      const [x, y] = stampOrigin(state.tool, rows, p[0], p[1]);
      return G.paste(frame, rows, x, y, { on: !dark, opaque: state.opaque });
    }

    /* -- one-step edits -- */
    function edit(rows) {
      drop();
      if (rows.join("\n") === o.frame().join("\n")) return;
      o.begin(); o.set(rows); o.end();
    }

    /* -- drawing the surface -- */
    let cell = 1;
    function render() {
      const f = o.frame();
      if (!f) return;
      const h = f.length, w = f[0].length, canvas = o.canvas;
      if (mask && (mask.length !== h || mask[0].length !== w)) { mask = null; maskUndo = []; float = null; }
      const fit = fitCell(contentWidth(canvas.parentElement), w, { max: o.max ?? 24, dpr: win.devicePixelRatio || 1 });
      const s = (cell = fit.device);
      canvas.width = w * s; canvas.height = h * s; canvas.style.width = `${fit.width}px`;
      const c = canvas.getContext("2d");
      c.fillStyle = css("--cell-off"); c.fillRect(0, 0, canvas.width, canvas.height);
      const prev = o.onion ? o.onion() : null, ink = css("--ink"), accent = css("--accent"), off = css("--cell-off");
      // a stamp tool shows what a click gives: the cells it lights in the accent colour, the
      // cells it darkens in a faint accent
      const preview = hover && !gesture && STAMPS.includes(state.tool) ? stamped(f, hover, state.erase) : null;
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          if (preview && preview[y][x] !== f[y][x]) {
            const lights = preview[y][x] === "#";
            c.globalAlpha = 1; c.fillStyle = lights ? accent : off; c.fillRect(x * s, y * s, s, s);
            if (!lights) { c.globalAlpha = 0.35; c.fillStyle = accent; c.fillRect(x * s, y * s, s, s); }
            continue;
          }
          if (f[y][x] === "#") c.globalAlpha = 1;
          else if (prev && prev[y] && prev[y][x] === "#") c.globalAlpha = 0.22;
          else continue;
          c.fillStyle = ink; c.fillRect(x * s, y * s, s, s);
        }
      }
      c.globalAlpha = 1;
      // a white grid shows each pixel: every cell from 3 device pixels, every 8 cells always
      const lines = (every, colour) => {
        c.strokeStyle = colour; c.lineWidth = 1; c.beginPath();
        for (let x = every; x < w; x += every) { c.moveTo(x * s + 0.5, 0); c.lineTo(x * s + 0.5, canvas.height); }
        for (let y = every; y < h; y += every) { c.moveTo(0, y * s + 0.5); c.lineTo(canvas.width, y * s + 0.5); }
        c.stroke();
      };
      if (s >= 3) lines(1, css("--grid"));
      lines(8, css("--grid-major"));
      // the selection: edges in black and white by turns, so they show on any cell, in both themes
      const sel = gesture?.preview ?? mask;
      if (sel) {
        const t = Math.max(1, Math.round(s / 4));
        for (const [x0, y0, x1, y1] of maskEdges(sel)) {
          c.fillStyle = (x0 + y0) % 2 ? "#ffffff" : "#000000";
          if (y0 === y1) c.fillRect(x0 * s, Math.min(y0 * s, canvas.height - t), s, t);
          else c.fillRect(Math.min(x0 * s, canvas.width - t), y0 * s, t, s);
        }
      }
      o.canvas.dataset.tool = state.tool;
    }

    /* -- pointer -- */
    function cellAt(e, clamp) {
      const r = o.canvas.getBoundingClientRect(), [w, h] = size();
      let x = Math.floor(((e.clientX - r.left) / r.width) * w), y = Math.floor(((e.clientY - r.top) / r.height) * h);
      if (clamp) { x = Math.max(0, Math.min(w - 1, x)); y = Math.max(0, Math.min(h - 1, y)); }
      return x >= 0 && y >= 0 && x < w && y < h ? [x, y] : null;
    }
    const modeOf = (e) => (e.shiftKey ? "add" : e.altKey ? "subtract" : state.mode);

    o.canvas.addEventListener("contextmenu", (e) => e.preventDefault());
    o.canvas.addEventListener("pointerdown", (e) => {
      const p = cellAt(e, false);
      if (!p || (e.button !== 0 && e.button !== 2)) return;
      e.preventDefault();
      lastCell = p; moved = false;
      const t = state.tool, [w, h] = size();
      if (t !== "move") drop();
      if (t === "pencil" || t === "line" || t === "rect" || t === "ellipse") {
        o.begin();
        gesture = { kind: "draw", start: o.frame().join("\n"), d: drag(state, o.frame(), p[0], p[1], { button: e.button }) };
        o.set(gesture.d.frame);
      } else if (t === "select") {
        gesture = { kind: "select", from: p, mode: modeOf(e), shiftAtStart: e.shiftKey };
        gesture.preview = G.maskCombine(mask, G.maskRect(w, h, p[0], p[1], p[0], p[1]), gesture.mode);
        render();
      } else if (t === "wand") {
        setMask(G.maskCombine(mask, G.wand(o.frame(), p[0], p[1], { connect: state.connect }), modeOf(e)));
      } else if (t === "move") {
        if (!float) liftNow(e.altKey);
        gesture = { kind: "move", from: p, dx: float.dx, dy: float.dy };
      } else if (t === "bucket") {
        edit(G.flood(o.frame(), p[0], p[1], !(state.erase || e.button === 2), { connect: state.connect, mask }));
      } else if (t === "pattern") {
        const region = G.wand(o.frame(), p[0], p[1], { connect: state.connect });
        const limit = mask ? G.maskCombine(region, G.maskInvert(mask), "subtract") : region;
        edit(G.fill(o.frame(), state.pattern.kind, state.pattern, limit));
      } else if (t === "gradient") {
        o.begin();
        gesture = { kind: "gradient", from: p, start: o.frame(), startText: o.frame().join("\n") };
        showGradient(p);
      } else if (STAMPS.includes(t)) {
        hover = p;
        edit(stamped(o.frame(), p, state.erase || e.button === 2));
        return;
      }
      try { o.canvas.setPointerCapture(e.pointerId); } catch { /* a pointer that is not active */ }
    });
    /** The gradient of a drag: the press point is Start % and the point under the pointer End %
     *  (radial: the press point is the centre). A click with no drag fills the whole area. */
    function showGradient(p) {
      const g = gesture, gr = state.gradient, dragged = p[0] !== g.from[0] || p[1] !== g.from[1];
      const params = { angle: 0, invert: gr.invert, start: gr.start, end: gr.end, curve: gr.curve };
      if (dragged) { params.from = g.from; params.to = p; }
      o.set(G.fill(g.start, gr.kind, params, mask));
    }
    function pointerMove(p, shift) {
      const g = gesture, [w, h] = size();
      if (!g) return;
      if (g.kind === "draw") o.set(g.d.move(p[0], p[1], shift));
      else if (g.kind === "select") {
        let [x1, y1] = p;
        if (shift && !g.shiftAtStart) [x1, y1] = G.constrain("rect", g.from[0], g.from[1], x1, y1);
        g.preview = G.maskCombine(mask, G.maskRect(w, h, g.from[0], g.from[1], x1, y1), g.mode);
        render();
      } else if (g.kind === "move") {
        float.dx = g.dx + p[0] - g.from[0]; float.dy = g.dy + p[1] - g.from[1];
        showFloat();
      } else if (g.kind === "gradient") showGradient(p);
    }
    // the stamp preview follows the pointer over the canvas, and leaves with it
    o.canvas.addEventListener("pointermove", (e) => {
      if (gesture || !STAMPS.includes(state.tool)) return;
      const p = cellAt(e, false);
      if (p?.[0] === hover?.[0] && p?.[1] === hover?.[1]) return;
      hover = p; render();
    });
    o.canvas.addEventListener("pointerleave", () => { if (hover) { hover = null; render(); } });
    win.addEventListener("pointermove", (e) => {
      if (!gesture) return;
      const p = cellAt(e, true);
      if (!p || (p[0] === lastCell[0] && p[1] === lastCell[1] && !e.shiftKey)) return;
      lastCell = p; moved = true;
      pointerMove(p, e.shiftKey);
    });
    win.addEventListener("pointerup", () => {
      const g = gesture;
      if (!g) return;
      gesture = null;
      if (g.kind === "draw") { if (o.frame().join("\n") === g.start) o.unbegin?.(); o.end(); }
      else if (g.kind === "select") {
        if (!moved && g.mode === "replace") setMask(null);       // a click deselects
        else setMask(g.preview);
      } else if (g.kind === "gradient") { if (o.frame().join("\n") === g.startText) o.unbegin?.(); o.end(); }
      render();
    });

    /* -- keyboard -- */
    const typing = (e) => /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
    win.addEventListener("keydown", (e) => {
      if (typing(e)) return;
      const ctrl = e.ctrlKey || e.metaKey, k = e.key;
      if (gesture && k === "Shift") { if (lastCell) pointerMove(lastCell, true); return; }
      if (ctrl && !e.altKey && k.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); drop(); o.undo?.(); return; }
      if (ctrl && e.altKey && k.toLowerCase() === "z") { e.preventDefault(); undoSel(); return; }
      if (ctrl && k.toLowerCase() === "a") { e.preventDefault(); selectAll(); return; }
      if (ctrl && k.toLowerCase() === "d") { e.preventDefault(); deselect(); return; }
      if (ctrl && e.shiftKey && k.toLowerCase() === "i") { e.preventDefault(); invertSel(); return; }
      if (ctrl && k.toLowerCase() === "c") { e.preventDefault(); copySel(); return; }
      if (ctrl && k.toLowerCase() === "x") { e.preventDefault(); cutSel(); return; }
      if (ctrl && k.toLowerCase() === "v") { e.preventDefault(); paste(); return; }
      if (ctrl || e.altKey) return;
      const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
      if (arrows[k] && (float || mask)) { e.preventDefault(); if (!float) liftNow(false); nudge(...arrows[k]); return; }
      if (k === "Enter" && float) { e.preventDefault(); drop(); return; }
      if (k === "Escape") { if (helpOpen()) toggleHelp(false); else if (float) cancelFloat(); else deselect(); return; }
      if ((k === "Delete" || k === "Backspace") && mask) { e.preventDefault(); clearSel(); return; }
      if (k === "?") { toggleHelp(); return; }
      const tool = TOOLS.find((t) => t.key === k.toUpperCase());
      if (tool) { setTool(tool.id); return; }
      const tog = TOGGLES.find((t) => t.key === k.toUpperCase());
      if (tog) setToggle(tog.id, !state[tog.id]);
    });
    win.addEventListener("keyup", (e) => { if (gesture && e.key === "Shift" && lastCell) pointerMove(lastCell, false); });

    /* -- the tool bar -- */
    const buttons = {};
    function iconButton(item, toggle) {
      const b = doc.createElement("button");
      b.type = "button"; b.className = "tool"; b.dataset.tool = item.id;
      b.innerHTML = I.iconSvg(item.id, 32);
      b.title = `${item.name} (${item.key})`;
      b.setAttribute("aria-label", `${item.name}, shortcut ${item.key}`);
      b.setAttribute("aria-pressed", "false");
      b.onclick = () => (toggle ? setToggle(item.id, !state[item.id]) : setTool(item.id));
      buttons[item.id] = b;
      return b;
    }
    const groups = GROUPS.map((g) => {
      const box = doc.createElement("div");
      box.className = "tool-group"; box.setAttribute("role", "group"); box.setAttribute("aria-label", g);
      for (const t of TOOLS.filter((x) => x.group === g)) box.append(iconButton(t, false));
      for (const t of TOGGLES.filter((x) => x.group === g)) box.append(iconButton(t, true));
      return box;
    });
    const helpBtn = doc.createElement("button");
    helpBtn.type = "button"; helpBtn.className = "tool help-btn"; helpBtn.innerHTML = I.iconSvg("help", 32);
    helpBtn.title = "Shortcuts (?)"; helpBtn.setAttribute("aria-label", "Shortcuts, shortcut ?");
    helpBtn.setAttribute("aria-expanded", "false"); helpBtn.onclick = () => toggleHelp();
    o.toolbar.replaceChildren(...groups, helpBtn);
    o.toolbar.classList.add("toolbar");
    o.toolbar.setAttribute("role", "toolbar"); o.toolbar.setAttribute("aria-label", "Drawing tools");

    /* -- help -- */
    const help = doc.createElement("div");
    help.className = "help-pop"; help.hidden = true; help.setAttribute("role", "dialog"); help.setAttribute("aria-label", "Shortcuts");
    const dl = doc.createElement("dl");
    for (const [k, v] of SHORTCUTS) { const dt = doc.createElement("dt"), dd = doc.createElement("dd"); dt.textContent = k; dd.textContent = v; dl.append(dt, dd); }
    const close = doc.createElement("button");
    close.type = "button"; close.textContent = "Close"; close.onclick = () => toggleHelp(false);
    const ht = doc.createElement("strong"); ht.textContent = "Shortcuts";
    help.append(ht, dl, close);
    (o.help ?? o.toolbar).append(help);
    const helpOpen = () => !help.hidden;
    help.tabIndex = -1;
    function toggleHelp(open = help.hidden) {
      help.hidden = !open; helpBtn.setAttribute("aria-expanded", String(open));
      if (open) { help.scrollTop = 0; help.focus({ preventScroll: true }); } else helpBtn.focus({ preventScroll: true });
    }

    /* -- the context bar: the options of the active tool only -- */
    const el = (tag, props = {}, ...kids) => { const n = Object.assign(doc.createElement(tag), props); n.append(...kids); return n; };
    function segmented(label, options, value, set) {
      const box = el("div", { className: "seg" });
      box.setAttribute("role", "group"); box.setAttribute("aria-label", label);
      for (const [v, text] of options) {
        const b = el("button", { type: "button", textContent: text });
        b.dataset.value = String(v);
        b.setAttribute("aria-pressed", String(v === value));
        b.onclick = () => { set(v); renderContext(); };
        box.append(b);
      }
      return box;
    }
    function number(label, value, { min, max, step = 1 }, set) {
      const input = el("input", { type: "number", value, min, max, step });
      input.oninput = () => { const v = +input.value; if (Number.isFinite(v)) set(Math.max(min, Math.min(max, v))); };
      return el("label", {}, label + " ", input);
    }
    function range(label, value, set, key) {
      const input = el("input", { type: "range", min: 0, max: 100, value: Math.round(value * 100) });
      if (key) input.dataset.ctx = key;
      const out = el("output", { textContent: `${input.value}%` });
      input.oninput = () => { set(+input.value / 100); out.textContent = `${input.value}%`; };
      return el("label", {}, label + " ", input, out);
    }
    const button = (text, fn, title) => { const b = el("button", { type: "button", textContent: text, onclick: fn }); if (title) b.title = title; return b; };
    /** A small picture of the stamp's rows in the context bar, so they show before the pointer is on the canvas. */
    function stampThumb() {
      const cv = el("canvas", { className: "px stamp-thumb" });
      cv.setAttribute("aria-hidden", "true");
      return cv;
    }
    function drawThumb(cv) {
      const rows = stampRows(), w = rows[0]?.length ?? 0, h = rows.length;
      const sc = w ? Math.max(1, Math.min(4, Math.floor(160 / w), Math.floor(64 / h))) : 1;
      cv.width = Math.max(1, w * sc); cv.height = Math.max(1, h * sc);
      const x2 = cv.getContext("2d");
      x2.fillStyle = css("--cell-off"); x2.fillRect(0, 0, cv.width, cv.height);
      x2.fillStyle = css("--ink");
      rows.forEach((r, y) => { for (let x = 0; x < w; x++) if (r[x] === "#") x2.fillRect(x * sc, y * sc, sc, sc); });
    }
    function textParts() {
      const tx = state.text, thumb = stampThumb(), info = el("span", { className: "hint" });
      const update = () => {
        const l = T.layout(tx.text, fontNow(), { spacing: tx.spacing });
        drawThumb(thumb);
        info.textContent = (l.width ? `${l.width} x ${l.height} pixels.` : "Type the text.")
          + (l.missing.length ? ` Not in the font: ${l.missing.join(" ")}` : "");
        render();
      };
      const font = el("select", {}, ...fonts.map((f) => el("option", { value: f.id, textContent: f.name, selected: f.id === tx.font })));
      font.setAttribute("aria-label", "Font"); font.dataset.ctx = "font";
      font.onchange = () => { tx.font = font.value; update(); };
      const input = el("input", { type: "text", value: tx.text, spellcheck: false });
      input.setAttribute("aria-label", "Text"); input.dataset.ctx = "text";
      input.oninput = () => { tx.text = input.value; update(); };
      const load = button("Load font", async () => {
        const f = await pickFile(doc, ".json,application/json");
        if (!f) return;
        try {
          const font = { id: `file-${fonts.length}`, ...T.parseFont(await f.text(), f.name) };
          fonts.push(font); tx.font = font.id; renderContext();
        } catch (err) { info.textContent = `${f.name}: ${err.message}`; }
      }, "A font file in the shape of font3x5.json. It stays in this page.");
      const parts = [el("label", {}, "Font ", font), load, input,
        number("Spacing", tx.spacing, { min: 0, max: 8 }, (v) => { tx.spacing = v; update(); }), thumb, info];
      update();
      return parts;
    }
    function controlParts() {
      const k = state.control.kind, p = state.control[k], thumb = stampThumb();
      const update = () => { drawThumb(thumb); render(); };
      const set = (key) => (v) => { p[key] = v; update(); };
      const seg = (label, key, options) => segmented(label, options, p[key], set(key));
      const parts = [segmented("Control", C.KINDS, k, (v) => { state.control.kind = v; })];
      if (k === "knob") {
        parts.push(number("Size", p.size, { min: 5, max: 64 }, set("size")), range("Value", p.value, set("value"), "value"),
          seg("Body", "body", [["ring", "Ring"], ["disc", "Disc"]]),
          seg("Mark", "mark", [["line", "Line"], ["arc", "Arc"], ["both", "Line and arc"]]));
      } else if (k === "slider") {
        parts.push(seg("Direction", "orient", [["h", "Across"], ["v", "Upright"]]),
          number("Length", p.length, { min: 5, max: 128 }, set("length")), number("Width", p.thick, { min: 3, max: 16 }, set("thick")),
          range("Value", p.value, set("value"), "value"), seg("Style", "style", [["fill", "Fill"], ["handle", "Handle"]]));
      } else if (k === "button") {
        parts.push(number("W", p.w, { min: 3, max: 64 }, set("w")), number("H", p.h, { min: 3, max: 64 }, set("h")),
          seg("State", "on", [[false, "Off"], [true, "On"]]), seg("Corners", "round", [[false, "Square"], [true, "Round"]]));
      } else {
        parts.push(seg("Style", "style", [["slide", "Slide"], ["box", "Check box"]]));
        if (p.style === "slide") parts.push(number("W", p.w, { min: 7, max: 64 }, set("w")));
        parts.push(number(p.style === "slide" ? "H" : "Size", p.h, { min: 5, max: 32 }, set("h")),
          seg("State", "on", [[false, "Off"], [true, "On"]]));
      }
      parts.push(thumb);
      drawThumb(thumb);
      return parts;
    }
    const behind = () => segmented("Behind", [[false, "Keep behind"], [true, "Clear behind"]], state.opaque, (v) => { state.opaque = v; });
    function selectionButtons() {
      return [button("Select all", selectAll, "Ctrl+A"), button("Deselect", deselect, "Ctrl+D"),
        button("Invert", invertSel, "Ctrl+Shift+I"), button("Undo selection", undoSel, "Ctrl+Alt+Z")];
    }
    function renderContext() {
      const t = TOOLS.find((x) => x.id === state.tool);
      const parts = [el("span", { className: "ctx-name", textContent: `${t.name} (${t.key})` })];
      const connect = () => segmented("Neighbours", [[4, "4 neighbours"], [8, "8 neighbours"]], state.connect, (v) => { state.connect = v; });
      const mode = () => segmented("Selection mode", [["replace", "New"], ["add", "Add"], ["subtract", "Subtract"]], state.mode, (v) => { state.mode = v; });
      switch (state.tool) {
        case "pencil": parts.push(el("span", { className: "hint", textContent: "The first pixel sets the colour. Erase or the right button draws dark." })); break;
        case "line": parts.push(el("span", { className: "hint", textContent: "Shift: steps of 45 degrees." })); break;
        case "rect": case "ellipse":
          parts.push(segmented("Shape", [[false, "Outline"], [true, "Filled"]], state.filled, (v) => setToggle("filled", v)));
          parts.push(el("span", { className: "hint", textContent: "Shift: a square or a circle." }));
          break;
        case "select": parts.push(mode(), ...selectionButtons()); break;
        case "wand": parts.push(mode(), connect(), ...selectionButtons()); break;
        case "move":
          parts.push(button("Cut", cutSel, "Ctrl+X"), button("Copy", copySel, "Ctrl+C"), button("Paste", paste, "Ctrl+V"),
            button("Clear", clearSel, "Delete"), button("Drop", drop, "Enter"),
            el("span", { className: "hint", textContent: "Alt-drag copies. Arrow keys move one cell." }));
          break;
        case "bucket": parts.push(connect(), el("span", { className: "hint", textContent: "Fills the area you click, inside the selection." })); break;
        case "pattern": {
          const p = state.pattern;
          const kind = el("select", { ariaLabel: "Pattern" }, ...PATTERNS.map(([v, n]) => el("option", { value: v, textContent: n, selected: v === p.kind })));
          kind.setAttribute("aria-label", "Pattern");
          kind.onchange = () => { p.kind = kind.value; renderContext(); };
          parts.push(kind);
          if (["bayer", "halftone", "noise", "blue"].includes(p.kind)) parts.push(range("Density", p.density, (v) => { p.density = v; }));
          if (p.kind === "hatch" || p.kind === "crosshatch") {
            parts.push(number("Angle", p.angle, { min: -180, max: 180, step: 15 }, (v) => { p.angle = v; }));
            parts.push(number("Spacing", p.spacing, { min: 2, max: 16 }, (v) => { p.spacing = v; }));
          }
          if (p.kind === "halftone") parts.push(number("Cell", p.cell, { min: 2, max: 16 }, (v) => { p.cell = v; }));
          if (p.kind === "checker") parts.push(number("Size", p.size, { min: 1, max: 16 }, (v) => { p.size = v; }));
          if (p.kind === "noise") parts.push(number("Seed", p.seed, { min: 1, max: 9999 }, (v) => { p.seed = v; }));
          parts.push(connect(), el("span", { className: "hint", textContent: "Fills the area you click." }));
          break;
        }
        case "gradient":
          parts.push(segmented("Gradient", [["linear", "Linear"], ["radial", "Radial"]], state.gradient.kind, (v) => { state.gradient.kind = v; }));
          parts.push(segmented("Direction", [[false, "Dark to lit"], [true, "Lit to dark"]], state.gradient.invert, (v) => { state.gradient.invert = v; }));
          parts.push(range("Start", state.gradient.start, (v) => { state.gradient.start = v; }, "start"));
          parts.push(range("End", state.gradient.end, (v) => { state.gradient.end = v; }, "end"));
          {
            const curve = el("select", {}, ...Object.keys(G.EASE).map((k) => el("option", { value: k, textContent: CURVE_NAMES[k] ?? k, selected: k === state.gradient.curve })));
            curve.setAttribute("aria-label", "Curve"); curve.dataset.ctx = "curve";
            curve.onchange = () => { state.gradient.curve = curve.value; };
            parts.push(el("label", {}, "Curve ", curve));
          }
          parts.push(el("span", { className: "hint", textContent: "Drag from the Start point to the End point. Past them the ends stay as they are. A click fills all of the selection." }));
          break;
        case "text":
          parts.push(...textParts(), behind(),
            el("span", { className: "hint", textContent: "Click to place the text. The pointer is its top left corner. Erase or the right button stamps it dark." }));
          break;
        case "control":
          parts.push(...controlParts(), behind(),
            el("span", { className: "hint", textContent: "Click to place the control. The pointer is its centre. Erase or the right button stamps it dark." }));
          break;
        default: break;
      }
      o.context.replaceChildren(...parts);
      o.context.classList.add("context-bar");
      o.context.setAttribute("aria-label", "Tool options");
    }
    function sync() {
      for (const t of TOOLS) buttons[t.id].setAttribute("aria-pressed", String(state.tool === t.id));
      for (const t of TOGGLES) buttons[t.id].setAttribute("aria-pressed", String(state[t.id]));
    }
    function setTool(id) { if (id !== "move") drop(); state.tool = id; if (!STAMPS.includes(id)) hover = null; sync(); renderContext(); render(); }
    function setToggle(id, on) { state[id] = on; sync(); renderContext(); }
    sync(); renderContext();

    // the grid follows its column: window resizes and layout changes
    let room = 0;
    new win.ResizeObserver(() => { const r = contentWidth(o.canvas.parentElement); if (r !== room) { room = r; render(); } }).observe(o.canvas.parentElement);

    return {
      state, render, setTool, setToggle, drop, cancelFloat, selectAll, deselect, invertSel, undoSel,
      copy: copySel, cut: cutSel, paste, clear: clearSel,
      get mask() { return mask; }, set mask(m) { setMask(m); },
      get floating() { return !!float; },
      /** Forget the selection and the move when the page shows another frame or glyph. */
      reset() { float = null; gesture = null; mask = null; maskUndo = []; hover = null; render(); },
      /** The rows the Text or Controls tool would place now ([] for another tool). */
      stampRows,
    };
  }

  /**
   * A frame size picker: a list of sizes and "Other size", which shows W and H fields.
   * `o`: presets ([w, h] pairs; GlyphAnim.SIZES by default), value [w, h], ids {select, w, h}
   * for the three controls, label, onChange(w, h) when a valid size is picked.
   * Returns { get size(), set(w, h) }. The fields keep the size of a preset too, so a page can
   * read them.
   */
  function sizePicker(box, o = {}) {
    const G = root.GlyphAnim, doc = box.ownerDocument;
    const presets = o.presets ?? G.SIZES, ids = o.ids ?? {};
    const el = (tag, props = {}, ...kids) => { const n = Object.assign(doc.createElement(tag), props); n.append(...kids); return n; };
    const key = ([w, h]) => `${w}x${h}`;
    const select = el("select", {}, ...presets.map((s) => el("option", { value: key(s), textContent: `${s[0]} x ${s[1]}` })),
      el("option", { value: "custom", textContent: "Other size" }));
    select.setAttribute("aria-label", o.label ?? "Frame size");
    const field = (label, max) => el("input", { type: "number", min: 1, max, step: 1 });
    const w = field("W", G.LIMITS.width), h = field("H", G.LIMITS.height);
    w.setAttribute("aria-label", "Width"); h.setAttribute("aria-label", "Height");
    if (ids.select) select.id = ids.select;
    if (ids.w) w.id = ids.w;
    if (ids.h) h.id = ids.h;
    const wl = el("label", {}, "W ", w), hl = el("label", {}, "H ", h);
    const size = () => [Math.round(+w.value), Math.round(+h.value)];
    function show(v) {
      [w.value, h.value] = v;
      const preset = presets.some((s) => key(s) === key(v));
      select.value = preset ? key(v) : "custom";
      wl.hidden = hl.hidden = preset;
    }
    select.onchange = () => {
      if (select.value === "custom") { wl.hidden = hl.hidden = false; w.focus(); return; }
      show(select.value.split("x").map(Number));
      o.onChange?.(...size());
    };
    for (const input of [w, h]) {
      input.onchange = () => { const [a, b] = size(); if (G.sizeOk(a, b)) o.onChange?.(a, b); };
    }
    box.append(select, wl, hl);
    show(o.value ?? presets[0]);
    return { get size() { return size(); }, set: (a, b) => show([a, b]) };
  }

  /* ---- files out: download names and the download itself ---- */

  const STAMP_KEY = "glyph-tools.stamp-names";
  const pad2 = (n) => String(n).padStart(2, "0");

  /** The file name with the local date and time before its extension: name_yymmdd-hhmmss.ext. */
  function stampName(filename, date = new Date()) {
    const stamp = pad2(date.getFullYear() % 100) + pad2(date.getMonth() + 1) + pad2(date.getDate()) + "-"
      + pad2(date.getHours()) + pad2(date.getMinutes()) + pad2(date.getSeconds());
    const dot = filename.lastIndexOf(".");
    return dot > 0 ? `${filename.slice(0, dot)}_${stamp}${filename.slice(dot)}` : `${filename}_${stamp}`;
  }

  /** Whether downloads get the date and time in their names: the viewer's choice, on by default.
   *  Storage can be missing or blocked, so a failed read is "on" and a failed write is ignored. */
  function stampNames(win = root) {
    try { return win.localStorage?.getItem(STAMP_KEY) !== "off"; } catch { return true; }
  }
  function setStampNames(on, win = root) {
    try { win.localStorage?.setItem(STAMP_KEY, on ? "on" : "off"); } catch { /* the choice lasts for this page only */ }
  }

  /** The name a download gets: with the date and time when the viewer wants them (or `stamp` says so). */
  function downloadName(filename, { stamp = stampNames(), date = new Date() } = {}) {
    return stamp ? stampName(filename, date) : filename;
  }

  /** Offer bytes or text as a file to save; returns the file name used. The link is in the
   *  document while it is clicked, and its URL is freed later: phone browsers need both. */
  function download(doc, data, filename, type = "application/octet-stream") {
    const name = downloadName(filename, { stamp: stampNames(doc.defaultView) });
    const url = URL.createObjectURL(new Blob([data], { type }));
    const a = Object.assign(doc.createElement("a"), { href: url, download: name });
    a.style.display = "none";
    doc.body.append(a);
    a.click();
    a.remove();
    doc.defaultView.setTimeout(() => URL.revokeObjectURL(url), 30000);
    return name;
  }

  /** The "Add date and time to file names" check box, with its note, into `box`. */
  function stampOption(box) {
    const doc = box.ownerDocument, win = doc.defaultView;
    const input = Object.assign(doc.createElement("input"), { type: "checkbox", checked: stampNames(win), id: "stamp-names" });
    const label = doc.createElement("label");
    label.append(input, " Add date and time to file names");
    const note = Object.assign(doc.createElement("span"), { className: "muted stamp-note",
      textContent: "A browser does not overwrite a file it downloaded. To save over one file, open it and press Save (Chrome or Edge on a computer)." });
    const show = () => { note.hidden = input.checked; };
    input.onchange = () => { setStampNames(input.checked, win); show(); };
    show();
    box.append(label, note);
    return input;
  }

  /** Write text or bytes through a File System Access handle. Returns null when it worked, or
   *  the error: a lost permission or a full disk must not look like a save. */
  async function writeHandle(handle, data) {
    try {
      const w = await handle.createWritable();
      await w.write(data);
      await w.close();
      return null;
    } catch (e) { return e; }
  }

  /** Ask for one file, with a plain file input. */
  function pickFile(doc, accept) {
    return new Promise((done) => {
      const input = Object.assign(doc.createElement("input"), { type: "file", accept });
      input.onchange = () => done(input.files[0]);
      input.click();
    });
  }

  const api = { TOOLS, TOGGLES, SHORTCUTS, PATTERNS, CURVE_NAMES, STAMPS, drag, stampOrigin, fitCell, contentWidth, maskEdges, surface, sizePicker, download, pickFile,
    stampName, stampNames, setStampNames, downloadName, stampOption, writeHandle,
    get clipboard() { return clipboard; } };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GlyphTools = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
