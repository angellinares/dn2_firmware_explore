"""The figures and tables of the Waverider page's Technical tab, computed from the models.

    python scripts/gen_waverider_tech.py [--page site/waverider.html] [--dnx D:/01_Code/Z_Personal/DNX]

Every number comes from the code that ships, never typed by hand:

- the reader: `dnfw.waverider.render` (frames blended, then 4-point Hermite), its mip
  levels `dnfw.waverider.geometry` / `mip`, and the pool's layout `dnfw.waverider.table3`;
- the de-click, the glide and the noise: `dnfw.waverider.live`, which the DSP code is
  checked against bit for bit (`scripts/sharc_waverider_m5.py` and its siblings);
- what DNX proposes for a file: DNX's own `proposeGeometry` (its built `fit.js`), run
  through node, when `--dnx` points at a DNX checkout with `web/dist` built.

Each figure is inline SVG drawn with the site's colour tokens, so it follows the light and
dark themes. It is written into the page's generated regions,
`<!-- dnfw:tech NAME -->...<!-- /dnfw:tech -->`, as `dnfw mods matrix` writes its own.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.waverider import dsp, geometry, live, mip, pages, render, table3  # noqa: E402
from waverider_mip_alias import harmonic_powers, note_hz, saw255   # noqa: E402

RATE = 48000
BLOCK = 32                       # samples a block: POS, the glide and the de-click step per block
REGION = 0x201000                # a pool slot's levels in the DSP's DDR (docs/waverider-stage3.md, build3)


# ---------------------------------------------------------------- a small SVG plotter

class Plot:
    """One x-y chart. Series are drawn with classes the page styles (s0 accent, s1 ink,
    s2 soft dashed, s3 ok), so the figure follows the theme."""

    W, H, L, R, T, B = 640, 300, 58, 14, 14, 44

    def __init__(self, x, y, xlabel, ylabel, logx=False, logy=False, xticks=None, yticks=None,
                 xfmt=str, yfmt=str, height=None, legend="tl"):
        self.x0, self.x1 = x
        self.y0, self.y1 = y
        self.logx, self.logy = logx, logy
        self.xlabel, self.ylabel = xlabel, ylabel
        self.xticks, self.yticks = xticks, yticks
        self.xfmt, self.yfmt = xfmt, yfmt
        if height:
            self.H = height
        self.where = legend               # tl, tr, bl or br: a corner the data leaves free; or below
        if legend == "below":
            self.B += 22
        self.parts: list[str] = []
        self.legend: list[tuple[str, str]] = []

    def _tx(self, v):
        a, b, v = ((math.log10(self.x0), math.log10(self.x1), math.log10(v)) if self.logx
                   else (self.x0, self.x1, v))
        return self.L + (v - a) / (b - a) * (self.W - self.L - self.R)

    def _ty(self, v):
        a, b, v = ((math.log10(self.y0), math.log10(self.y1), math.log10(v)) if self.logy
                   else (self.y0, self.y1, v))
        v = min(max(v, a), b)
        return self.H - self.B - (v - a) / (b - a) * (self.H - self.T - self.B)

    def line(self, xs, ys, cls="s0", label=None):
        pts = " ".join(f"{self._tx(x):.1f},{self._ty(y):.1f}" for x, y in zip(xs, ys))
        self.parts.append(f'<polyline class="{cls}" points="{pts}"/>')
        if label:
            self.legend.append((cls, label))

    def dots(self, xs, ys, cls="s0", label=None):
        for x, y in zip(xs, ys):
            self.parts.append(f'<circle class="{cls} dot" cx="{self._tx(x):.1f}" cy="{self._ty(y):.1f}" r="3"/>')
        if label:
            self.legend.append((cls, label))

    def vline(self, x, text="", low=False):
        px = self._tx(x)
        self.parts.append(f'<line class="mark" x1="{px:.1f}" y1="{self.T}" x2="{px:.1f}" y2="{self.H - self.B}"/>')
        if text:
            y = self.H - self.B - 6 if low else self.T + 12
            self.parts.append(f'<text class="note" x="{px + 4:.1f}" y="{y}">{html.escape(text)}</text>')

    def hline(self, y, text=""):
        py = self._ty(y)
        self.parts.append(f'<line class="mark" x1="{self.L}" y1="{py:.1f}" x2="{self.W - self.R}" y2="{py:.1f}"/>')
        if text:
            self.parts.append(f'<text class="note" x="{self.W - self.R - 4}" y="{py - 4:.1f}" text-anchor="end">{html.escape(text)}</text>')

    def svg(self, title: str) -> str:
        out = [f'<svg class="plot" viewBox="0 0 {self.W} {self.H}" role="img" aria-label="{html.escape(title)}">']
        bx, by, bw, bh = self.L, self.T, self.W - self.L - self.R, self.H - self.T - self.B
        out.append(f'<rect class="frame" x="{bx}" y="{by}" width="{bw}" height="{bh}"/>')
        for v in self.xticks or []:
            px = self._tx(v)
            out.append(f'<line class="grid" x1="{px:.1f}" y1="{by}" x2="{px:.1f}" y2="{by + bh}"/>')
            out.append(f'<text x="{px:.1f}" y="{by + bh + 16}" text-anchor="middle">{html.escape(self.xfmt(v))}</text>')
        for v in self.yticks or []:
            py = self._ty(v)
            out.append(f'<line class="grid" x1="{bx}" y1="{py:.1f}" x2="{bx + bw}" y2="{py:.1f}"/>')
            out.append(f'<text x="{bx - 6}" y="{py + 4:.1f}" text-anchor="end">{html.escape(self.yfmt(v))}</text>')
        label_y = self.H - 28 if self.where == "below" else self.H - 6
        out.append(f'<text x="{bx + bw / 2:.1f}" y="{label_y}" text-anchor="middle">{html.escape(self.xlabel)}</text>')
        out.append(f'<text x="14" y="{by + bh / 2:.1f}" text-anchor="middle" transform="rotate(-90 14 {by + bh / 2:.1f})">'
                   f'{html.escape(self.ylabel)}</text>')
        out += self.parts
        if self.where == "below":
            rows, lx = [[]], bx                       # wrap onto a new row when an entry would pass the edge
            for cls, label in self.legend:
                step = 40 + 7 * len(label)
                if rows[-1] and lx + step - 12 > self.W:
                    rows.append([])
                    lx = bx
                rows[-1].append((lx, cls, label))
                lx += step
            for r, row in enumerate(rows):
                y = self.H - 6 + 18 * r
                for lx, cls, label in row:
                    out.append(f'<line class="{cls}" x1="{lx}" y1="{y - 4}" x2="{lx + 22}" y2="{y - 4}"/>')
                    out.append(f'<text class="legend" x="{lx + 28}" y="{y}">{html.escape(label)}</text>')
            if len(rows) > 1:                          # the extra rows lie below: grow the canvas, not the plot
                out[0] = out[0].replace(f'viewBox="0 0 {self.W} {self.H}"', f'viewBox="0 0 {self.W} {self.H + 18 * (len(rows) - 1)}"')
            out.append("</svg>")
            return "".join(out)
        width = 44 + 7 * max((len(label) for _, label in self.legend), default=0)
        lx = bx + 10 if self.where[1] == "l" else bx + bw - width
        top = by + 14 if self.where[0] == "t" else by + bh - 8 - 16 * (len(self.legend) - 1)
        for k, (cls, label) in enumerate(self.legend):
            ly = top + 16 * k
            out.append(f'<line class="{cls}" x1="{lx}" y1="{ly - 4}" x2="{lx + 22}" y2="{ly - 4}"/>')
            out.append(f'<text class="legend" x="{lx + 28}" y="{ly}">{html.escape(label)}</text>')
        out.append("</svg>")
        return "".join(out)


def note_name(n: int) -> str:
    return ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][n % 12] + str(n // 12 - 1)


def table_html(head: list[str], rows: list[list], cls: str = "") -> str:
    th = "".join(f"<th>{html.escape(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f'<td{" class=\"num\"" if isinstance(c, (int, float)) or re.fullmatch(r"[-+0-9.,% x]+( [a-zA-Z]+)?", str(c)) else ""}>{html.escape(str(c))}</td>' for c in r) + "</tr>"
                   for r in rows)
    return f'<div class="scroll"><table{" class=" + chr(34) + cls + chr(34) if cls else ""}><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


# ---------------------------------------------------------------- 1. tables: what is stored, what the DSP holds

def geometry_table() -> str:
    """Per frame length: the levels, a 64-frame table on the +Drive and in the DSP's memory
    with its levels, and its share of the region each pool slot has (build3, 129 regions)."""
    rows = []
    for n in table3.TEMPLATE_SIZES:
        k = geometry.levels(n)
        frame_dsp = sum(table3.row_bytes(n, lv) for lv in range(k))
        store = 2 * 64 * n
        dsp_bytes = table3.HEADER_BYTES + 64 * frame_dsp
        rows.append([f"{n:,}", k, f"{geometry.top_harmonic(n, 0):,}", f"{store / 1024:,.0f} KiB",
                     f"{dsp_bytes / 1024:,.0f} KiB", f"{100 * dsp_bytes / REGION:.0f} %"])
    return table_html(["Points a frame", "Mip levels", "Harmonics in a frame", "64 frames on the +Drive",
                       "64 frames in the DSP, with its levels", "Of a pool slot's DSP region"], rows)


def dnx_proposals(dnx: pathlib.Path | None) -> str:
    """What DNX's importer proposes for common files, from DNX's own code."""
    cases = [("A WaveEdit bank: 64 x 256", 64 * 256), ("One single cycle of 2,048", 2048),
             ("Tonverk's default: 64 x 2,048", 64 * 2048), ("A Serum export: 256 x 2,048", 256 * 2048),
             ("A Tonverk large table: 64 x 4,096", 64 * 4096), ("A 600-sample recording", 600)]
    fit = None if dnx is None else dnx / "web/dist/packages/core/src/waverider/fit.js"
    node = shutil.which("node")
    if fit is None or not fit.exists() or not node:
        raise SystemExit("DNX's built fit.js and node are needed for the import table (--dnx)")
    script = ("import(process.argv[1]).then(m=>{const b={maxWaves:64,minPoints:64,maxPoints:4096,"
              "pointsPowerOfTwo:true};const out=JSON.parse(process.argv[2]).map(n=>{const p=m.proposeGeometry(n,b);"
              "return [p.geometry.waves,p.geometry.points,p.exact]});console.log(JSON.stringify(out))})")
    done = subprocess.run([node, "-e", script, fit.as_uri(), json.dumps([n for _, n in cases])],
                          capture_output=True, text=True, timeout=60, check=True)
    got = json.loads(done.stdout)
    rows = []
    for (what, n), (w, p, exact) in zip(cases, got):
        right = {16384: (64, 256), 2048: (1, 2048), 131072: (64, 2048), 524288: (64, 2048),
                 262144: (64, 4096)}.get(n)
        # Measured with DNX's fitToGeometry / blendToWaves (2026-10-15): the WaveEdit bank as
        # proposed holds 8 cycles a frame; the Serum export re-cut to 64 x 2,048 holds 4; with
        # blend it holds one, as it should.
        verdict = ("keep the proposal" if right == (w, p) else
                   "set waves 64 and points 256 (as proposed, each frame holds 8 cycles)" if n == 16384 else
                   "set waves 64, points 2,048 and turn on blend (a re-cut frame holds 4 cycles)" if n == 524288
                   else "a recording, not a wavetable: DNX resamples it to fit")
        rows.append([what, f"{n:,}", f"{w} x {p:,}", "yes" if exact else "no", verdict])
    return table_html(["The file", "Samples", "DNX proposes", "Divides exactly", "What to do"], rows)


# ---------------------------------------------------------------- 2. reading a table

def pos_map() -> str:
    p = Plot((0, 120), (0, 63), "POS (the knob, 0 to 120)", "frame played",
             xticks=[0, 20, 40, 60, 80, 100, 120], yticks=[0, 15, 31, 47, 63], height=260)
    knob = np.linspace(0, 120, 241)
    for frames, cls in ((64, "s0"), (32, "s1"), (16, "s2")):
        ys = [table3.position(live.position(int(k * 256)), frames) / 65536 for k in knob]
        p.line(knob, ys, cls, f"{frames} frames")
    return p.svg("Which frame POS plays, for tables of 16, 32 and 64 frames")


def frame_blend() -> str:
    """Harm.'s frames 1 and 2, and POS between them (the frames are blended, sample by sample)."""
    t = dsp.tables()[1]
    a, b = np.asarray(t[1], float) / 32768, np.asarray(t[2], float) / 32768
    p = Plot((0, 511), (-1, 1), "point in the frame (512 points, one cycle)", "level",
             xticks=[0, 128, 256, 384, 511], yticks=[-1, -0.5, 0, 0.5, 1], height=280, legend="below")
    xs = np.arange(512)
    p.line(xs, a, "s1", "frame 1 (POS 8)")
    p.line(xs, a + 0.5 * (b - a), "s0", "halfway (POS 12)")
    p.line(xs, b, "s2", "frame 2 (POS 16)")
    return p.svg("Harm. frames 1 and 2 and the mix halfway between them")


def interp_response() -> str:
    """How well the two interpolators reject the images above a table's band: the response
    of linear and of 4-point Catmull-Rom (Hermite) interpolation, as a function of
    frequency relative to the table's sample rate."""
    over = 64
    t = np.arange(-2 * over, 2 * over + 1) / over

    def catmull(x):
        x = abs(x)
        return np.where(x < 1, 1.5 * x ** 3 - 2.5 * x ** 2 + 1,
                        np.where(x < 2, -0.5 * x ** 3 + 2.5 * x ** 2 - 4 * x + 2, 0))
    lin = np.maximum(0, 1 - np.abs(t))
    n = 1 << 14
    f = np.fft.rfftfreq(n, 1 / over)
    resp = {}
    for name, k in (("linear", lin), ("Hermite", catmull(t))):
        h = np.abs(np.fft.rfft(k, n)) / over
        resp[name] = 20 * np.log10(np.maximum(h, 1e-6))
    keep = f <= 3
    p = Plot((0, 3), (-80, 5), "frequency, in multiples of the table's sample rate (points x note frequency)",
             "response (dB)", xticks=[0, 0.5, 1, 1.5, 2, 2.5, 3], yticks=[0, -20, -40, -60, -80],
             xfmt=lambda v: f"{v:g}", height=280, legend="below")
    p.line(f[keep], resp["linear"][keep], "s2", "linear (the plain-table reader)")
    p.line(f[keep], resp["Hermite"][keep], "s0", "4-point Hermite (the shipped reader)")
    p.vline(1, "the first image")              # at the top: the curves are low there
    return p.svg("The response of linear and Hermite interpolation")


def alias_measure() -> tuple[str, str, list]:
    """The alias power, against the harmonics, of a 255-harmonic saw from C2 to C8: no mip
    levels (linear), mip levels with linear at 24 kHz, and the shipped reader (mip levels,
    Hermite, 28 kHz). Also the shipped reader's alias below 20 kHz only."""
    table = saw255()
    levels = mip.table_levels(table)
    notes = list(range(36, 109, 6))
    rows, series = [], {"plain": [], "mip24": [], "ship": [], "ship20": []}

    def alias_db(x, f0, below=None):
        h, a = harmonic_powers(np.asarray(x), f0)
        if below is not None:
            mag2 = np.abs(np.fft.rfft(np.asarray(x) * _bh(len(x)))) ** 2
            df = RATE / len(x)
            on = np.zeros(len(mag2), bool)
            on[:7] = True
            hh = 1
            while hh * f0 < RATE / 2:
                c = int(round(hh * f0 / df))
                on[max(0, c - 6):c + 7] = True
                hh += 1
            band = np.arange(len(mag2)) * df < below
            a = float(mag2[~on & band].sum())
        return 10 * math.log10(max(a, 1e-30) / max(h, 1e-30))
    count = 1 << 14
    for n in notes:
        f0 = note_hz(n)
        inc = render.increment(f0)
        plain, _ = render.render(levels[0], 0, inc, 0, count, "ideal", "linear")
        m24, _ = render.render(levels[mip.level_for(inc, 24000)], 0, inc, 0, count, "ideal", "linear")
        ship, _ = render.render(levels[mip.level_for(inc, 28000)], 0, inc, 0, count, "ideal", "hermite2")
        series["plain"].append(alias_db(plain, f0))
        series["mip24"].append(alias_db(m24, f0))
        series["ship"].append(alias_db(ship, f0))
        series["ship20"].append(alias_db(ship, f0, below=20000))
        rows.append([note_name(n), f"{f0:,.0f}", mip.level_for(inc, 28000), f"{series['plain'][-1]:.0f} dB",
                     f"{series['ship'][-1]:.0f} dB", f"{series['ship20'][-1]:.0f} dB"])
    p = Plot((36, 108), (-150, 0), "note", "alias (dB)",
             xticks=list(range(36, 109, 12)), yticks=[0, -25, -50, -75, -100, -125, -150],
             xfmt=note_name, height=280, legend="bl")
    p.line(notes, series["plain"], "s2", "one level, linear (no mip-maps)")
    p.line(notes, series["mip24"], "s1", "mip-maps, linear, 24 kHz")
    p.line(notes, series["ship"], "s0", "mip-maps, Hermite, 28 kHz (shipped): all aliases")
    p.line(notes, series["ship20"], "s3", "the same, aliases below 20 kHz only")
    table = table_html(["Note", "Hz", "Level played", "No mip-maps", "Shipped, all", "Shipped, below 20 kHz"], rows)
    return p.svg("Alias power against note for three readers"), table, series


def _bh(n):
    k = np.arange(n) * 2 * np.pi / (n - 1)
    return 0.35875 - 0.48829 * np.cos(k) + 0.14128 * np.cos(2 * k) - 0.01168 * np.cos(3 * k)


def levels_table() -> str:
    """For a 2,048-point frame: each level's points, its harmonics, and the notes it plays."""
    n = 2048
    rows = []
    for k in range(geometry.levels(n)):
        top = geometry.top_harmonic(n, k)
        # the level plays while top * f0 < 28 kHz (and the one below did not fit)
        hi = 28000 / top
        lo = 28000 / geometry.top_harmonic(n, k - 1) if k else 0
        midi = lambda f: 69 + 12 * math.log2(f / 440) if f > 0 else -99
        rows.append([k, f"{geometry.level_points(n, k):,}", f"1 to {top:,}",
                     ("up to " if not k else f"{lo:,.0f} to ") + f"{hi:,.0f} Hz",
                     ("lowest" if not k else note_name(math.ceil(midi(lo)))) + " to " +
                     (note_name(math.floor(midi(hi))) if midi(hi) <= 127 else "the top")])
    return table_html(["Level", "Points", "Harmonics kept", "Note frequency", "Notes"], rows)


# ---------------------------------------------------------------- 3. changes without clicks

def dclk_figure() -> str:
    """A table change (Prim. to Harm.) in the middle of a note at C3, with DCLK Off and at 3 ms."""
    tables = dsp.tables()
    inc = live.increment(48.0)
    pos = live.position(60 * 256)
    blocks = 18
    switch = 6
    out = {}
    for v in (0, 31):
        n_fade = live.dclk_lengths()[v]
        inv = live.dclk_inverses()[v]
        phase, y, fade = 0, [], None
        for b in range(blocks):
            tab = tables[0 if b < switch else 1]
            new, nxt = mip.read(tab, phase, inc, pos, BLOCK, "float32")
            if b == switch and n_fade:
                fade = [tables[0], n_fade]
            if fade:
                old, _ = mip.read(fade[0], phase, inc, pos, BLOCK, "float32")
                new = live.crossfade(new, old, fade[1], inv)
                fade[1] -= BLOCK
                if fade[1] <= 0:
                    fade = None
            y += new
            phase = nxt
        out[v] = y
    t_ms = np.arange(len(out[0])) / RATE * 1000
    p = Plot((0, t_ms[-1]), (-1.1, 1.1), "time (ms)", "level",
             xticks=[0, 2, 4, 6, 8, 10, 12], yticks=[-1, 0, 1], height=260, xfmt=lambda v: f"{v:g}",
             legend="below")
    p.line(t_ms, out[0], "s2", "DCLK Off: the wave jumps")
    p.line(t_ms, out[31], "s0", "DCLK 3.0 ms (the default): a crossfade")
    p.vline(switch * BLOCK / RATE * 1000, "TBL changes")
    return p.svg("A table change with DCLK off and at 3 ms")


def dclk_curve() -> str:
    vs = list(range(1, 128))
    p = Plot((1, 127), (1, 100), "DCLK (the knob's value)", "crossfade (ms)", logy=True,
             xticks=[1, 31, 63, 95, 127], yticks=[1, 3, 10, 30, 100], height=220,
             yfmt=lambda v: f"{v:g}")
    p.line(vs, [live.dclk_ms(v) for v in vs], "s0")
    p.dots([31], [live.dclk_ms(31)], "s0", "3.0 ms, the default")
    return p.svg("The crossfade time for each DCLK value")


# ---------------------------------------------------------------- 4. SLW, the slew (SMTH in the code; SMT1/SMT2 before 0.1.1)

def smt_curve() -> str:
    vs = list(range(1, 128))
    p = Plot((1, 127), (1, 1000), "SLW (the knob's value; 0 is Off)", "time constant (ms)", logy=True,
             xticks=[1, 15, 29, 43, 57, 71, 85, 99, 113, 127], yticks=[1, 3, 10, 30, 100, 300, 1000],
             height=220, yfmt=lambda v: f"{v:g}")
    p.line(vs, [live.smth_tau(v) * 1000 for v in vs], "s0")
    return p.svg("The slew's time constant for each SLW value")


def smt_response() -> str:
    """What the glide does to each source of POS: a jump of the knob, a sine LFO at 4 Hz,
    and a p-lock that comes with a note (the glide snaps). SLW 71 (62.5 ms), 1,500 steps a second."""
    smt = 71 << 8
    blocks = int(1.2 * 1500)
    t = np.arange(blocks) / 1500
    target, glided = [], []
    s = 0.0
    for b, tt in enumerate(t):
        pos = 20.0
        if tt >= 0.1:
            pos = 100.0                                    # the knob turned at once
        if tt >= 0.45:
            pos = 60.0 + 30.0 * math.sin(2 * math.pi * 4 * (tt - 0.45))   # an LFO at 4 Hz
        note = b == 0 or 0.95 <= tt < 0.95 + 1 / 1500
        if tt >= 0.95:
            pos = 10.0                                     # a trig with a p-lock: a note
        word = int(round(pos * 256))
        s = live.smooth(s, live.position(word), smt, note)
        target.append(pos)
        glided.append(s / live.position(256))
    p = Plot((0, 1.2), (0, 120), "time (s)", "POS", xticks=[0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2],
             yticks=[0, 30, 60, 90, 120], height=280, xfmt=lambda v: f"{v:g}", legend="below")
    p.line(t, target, "s2", "POS from the knob, the LFO and the p-lock")
    p.line(t, glided, "s0", "POS the reader plays, SLW 71 (62.5 ms)")
    p.vline(0.1, "knob jump", low=True)
    p.vline(0.45, "LFO 4 Hz", low=True)
    p.vline(0.95, "trig with a lock", low=True)
    return p.svg("What SLW does to a knob jump, an LFO and a p-lock")


def smt_values_table() -> str:
    """For a few SMT values: the time constant, the filter's coefficient k (the DSP's float32
    table), its cutoff, and the time to reach 95 % of a jump."""
    rows = []
    for v in (0, 1, 15, 29, 43, 57, 71, 85, 99, 113, 127):
        k = live.smth_table()[v]
        if v == live.SMTH_OFF:
            rows.append([v, "Off", f"{k:.6f}", "none", "at once"])
            continue
        tau = live.smth_tau(v)
        n95 = math.ceil(math.log(0.05) / math.log(1 - k))          # blocks
        rows.append([v, f"{tau * 1000:,.1f} ms", f"{k:.6f}", f"{1 / (2 * math.pi * tau):,.2f} Hz",
                     f"{n95 / 1500 * 1000:,.0f} ms"])
    return table_html(["SLW", "Time constant", "k (each block)", "Cutoff", "95 % of a jump"], rows)


def smt_lfo_table() -> str:
    """How much of an LFO's sweep on POS remains after the glide, by LFO rate and SMT."""
    rows = []
    for v in (29, 43, 57, 71, 85):
        tau = live.smth_tau(v)
        k = 1 - math.exp(-1 / (1500 * tau))
        cells = [v, f"{tau * 1000:.1f} ms"]
        for f in (0.5, 2, 8):
            w = 2 * math.pi * f / 1500
            g = abs(k / (1 - (1 - k) * complex(math.cos(w), -math.sin(w))))
            cells.append(f"{100 * g:.0f} %")
        rows.append(cells)
    return table_html(["SLW", "Time constant", "LFO 0.5 Hz", "LFO 2 Hz", "LFO 8 Hz"], rows)


# ---------------------------------------------------------------- 5. noise

def noise_spectra() -> str:
    n = 1 << 16
    out = {}
    for typ in range(4):
        v = live.NoiseVoice(live.noise_seeds()[0])
        word = (typ << 8, 64 << 8, live.NOISE_INF << 8)
        ys = []
        first = True
        while len(ys) < n:
            ys += v.render((100 << 8,) + word, first, BLOCK) or []
            first = False
        out[typ] = _bands(np.asarray(ys[:n]))
    f = out[0][0]
    p = Plot((30, 24000), (-40, 30), "frequency (Hz)", "level (dB, WHT at 0)", logx=True,
             xticks=[30, 100, 300, 1000, 3000, 10000, 24000], yticks=[30, 20, 10, 0, -10, -20, -30, -40],
             height=280, xfmt=lambda v: f"{v / 1000:g}k" if v >= 1000 else f"{v:g}", legend="bl")
    ref = 10 * np.log10(np.mean(out[0][1]))
    for typ, cls in ((0, "s1"), (1, "s0"), (2, "s2"), (3, "s3")):
        p.line(f, 10 * np.log10(out[typ][1]) - ref, cls, live.NOISE_TYPES[typ])
    return p.svg("The spectra of the four noise types")


def colr_spectra() -> str:
    n = 1 << 16
    p = Plot((30, 24000), (-30, 10), "frequency (Hz)", "level (dB, COLR 0 at 0)", logx=True,
             xticks=[30, 100, 300, 1000, 3000, 10000, 24000], yticks=[10, 0, -10, -20, -30],
             height=240, xfmt=lambda v: f"{v / 1000:g}k" if v >= 1000 else f"{v:g}", legend="br")
    res = {}
    for colr in (-64, -32, 0, 32, 63):
        v = live.NoiseVoice(live.noise_seeds()[0])
        ys, first = [], True
        while len(ys) < n:
            ys += v.render((100 << 8, 0, (colr + 64) << 8, live.NOISE_INF << 8), first, BLOCK) or []
            first = False
        f, power = _bands(np.asarray(ys[:n]))
        res[colr] = 10 * np.log10(power)
    for colr, cls in ((-64, "s2"), (0, "s1"), (63, "s0")):
        p.line(f, res[colr] - res[0].mean(), cls, f"COLR {colr:+d}" if colr else "COLR 0")
    return p.svg("WHT noise at COLR -64, 0 and +63")


def _psd(x: np.ndarray, seg: int = 1024) -> np.ndarray:
    w = np.hanning(seg)
    acc = np.zeros(seg // 2 + 1)
    k = 0
    for at in range(0, len(x) - seg + 1, seg // 2):
        acc += np.abs(np.fft.rfft(x[at:at + seg] * w)) ** 2
        k += 1
    return acc / k


def _bands(x: np.ndarray, per_octave: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """The spectrum in 1/6-octave bands from 20 Hz: (centres, mean power), so a line reads clean."""
    power = _psd(x, 8192)
    f = np.fft.rfftfreq(8192, 1 / RATE)
    edges = 20 * 2 ** (np.arange(0, 11 * per_octave) / per_octave)
    centres, means = [], []
    for lo, hi in zip(edges, edges[1:]):
        sel = (f >= lo) & (f < hi)
        if sel.any() and hi <= RATE / 2:
            centres.append(math.sqrt(lo * hi))
            means.append(power[sel].mean())
    return np.asarray(centres), np.asarray(means)


def dec_curve() -> str:
    vs = list(range(0, 127))
    p = Plot((0, 126), (5, 10000), "DEC (the knob's value; Inf has no decay)", "time constant (ms)", logy=True,
             xticks=[0, 21, 42, 63, 84, 105, 126], yticks=[5, 10, 30, 100, 300, 1000, 3000, 10000], height=220,
             yfmt=lambda v: f"{v:g}")
    p.line(vs, [live.noise_tau(v) * 1000 for v in vs], "s0")
    return p.svg("The noise decay's time constant for each DEC value")


# ---------------------------------------------------------------- 6. page 5: FOLD, Ring and AM, WARP, FM

def _peaks(xs):
    return [x / live.SHAPE_PEAK for x in xs]


def fold_curve() -> str:
    xs = [live._f32(live.SHAPE_PEAK * (k / 200 - 2)) for k in range(801)]
    p = Plot((-2, 2), (-1.05, 1.05), "input (1 = one oscillator's peak at LEV 100)", "output",
             xticks=[-2, -1, 0, 1, 2], yticks=[-1, 0, 1], height=280, legend="below")
    inside = [x for x in _peaks(xs) if abs(x) <= 1.05]
    p.line(inside, inside, "s0", "FOLD 0 (off)")
    for word, cls in ((0x2000, "s1"), (0x4000, "s2"), (0x7F00, "s3")):
        p.line(_peaks(xs), _peaks(live.fold(xs, word)), cls, f"FOLD {word >> 8}")
    return p.svg("What FOLD does to each sample")


def _voice(shape, blocks=40, osc2=(0x4000, 0x100, 0x4000, 0)):
    tables = dsp.tables()
    seq = [(48.0, (0x4000, 0, 0x4000, 0x6400), osc2)] * blocks
    return live.render_two(tables, seq, shapes=[shape] * blocks)


def fold_wave() -> str:
    n = 48000 / live.note_hz(48.0)                   # C3: one cycle
    span = int(round(2 * n))
    p = Plot((0, span / 48), (-1.05, 1.05), "time (ms)", "output (1 = the fold point)",
             xticks=[0, 5, 10, 15], yticks=[-1, 0, 1], height=260, legend="below")
    for word, cls in ((0, "s0"), (0x3000, "s1"), (0x7F00, "s3")):
        ys = _voice((word, 0, 0, 0x4000))[-span:]
        p.line([k / 48 for k in range(span)], _peaks(ys), cls, f"FOLD {word >> 8}")
    return p.svg("Prim. at POS 64, C3, folded")


def shaper_figure() -> str:
    span = 960                                        # 20 ms
    osc2 = (0x4000, 0, 0x4700, 0x6400)                # Prim. at POS 64, 7 semitones up
    o1 = _voice((0, 0, 0, 0), osc2=(0x4000, 0, 0x4700, 0))[-span:]
    both = _voice((0, 0, 0, 0), osc2=osc2)[-span:]
    ts = [k / 48 for k in range(span)]
    p = Plot((0, 20), (-2.1, 2.1), "time (ms)", "output (1 = one oscillator's peak)",
             xticks=[0, 5, 10, 15, 20], yticks=[-2, -1, 0, 1, 2], height=280, legend="below")
    p.line(ts, _peaks([b - a for a, b in zip(o1, both)]), "s0", "osc 2")
    p.line(ts, _peaks(o1), "s1", "osc 1")
    p.line(ts, _peaks(_voice((0, 0, 0x0100, 0x7F00), osc2=osc2)[-span:]), "s2", "Ring, AMT 127")
    p.line(ts, _peaks(_voice((0, 0, 0x0200, 0x7F00), osc2=osc2)[-span:]), "s3", "AM, AMT 127")
    return p.svg("Osc 1 and osc 2 a fifth apart, and the shaper")


def warp_curve() -> str:
    xs = [k / 400 for k in range(401)]
    p = Plot((0, 1), (0, 1), "the oscillator's phase (one cycle)", "where it reads the wave",
             xticks=[0, 0.25, 0.5, 0.75, 1], yticks=[0, 0.5, 1], height=280, legend="below")
    for v, cls in ((0, "s0"), (32, "s1"), (64, "s2"), (127, "s3")):
        k = live.warp_table()[v]
        ys = [x if not v else live.warp_phase(min(int(x * 2 ** 32), 2 ** 32 - 1), *k) / 2 ** 32 for x in xs]
        p.line(xs, ys, cls, f"WARP {v}" + (" (off)" if not v else ""))
    return p.svg("What WARP does to the phase")


ROWS = (2.4, 0.0, -2.4)                             # one row per value: a wave each, apart


def warp_wave() -> str:
    n = 48000 / live.note_hz(48.0)                   # C3: one cycle
    span = int(round(2 * n))
    values = ((0, "s0"), (16, "s1"), (127, "s3"))
    p = Plot((0, span / 48), (-3.6, 3.6), "time (ms)", "WARP (a row each)", xticks=[0, 5, 10, 15],
             yticks=list(ROWS), yfmt=lambda v: str(values[ROWS.index(v)][0]), height=300, legend="below")
    for (v, cls), row in zip(values, ROWS):
        ys = _voice((0, 0, 0, 0x4000, v << 8, 0))[-span:]
        p.line([k / 48 for k in range(span)], [row + y for y in _peaks(ys)], cls, f"WARP {v}")
    return p.svg("Prim. at POS 64, C3, warped")


def fm_wave() -> str:
    n = 48000 / live.note_hz(48.0)
    span = int(round(2 * n))
    osc2 = (0x4000, 0, 0x4000, 0x6400)                # Prim. at POS 64, the same pitch, LEV2 100
    o2 = [b - a for a, b in zip(_voice((0, 0, 0, 0x4000, 0, 0), osc2=(0x4000, 0, 0x4000, 0)),
                                _voice((0, 0, 0, 0x4000, 0, 0), osc2=osc2))]
    values = ((0, "s0"), (32, "s1"), (127, "s3"))
    p = Plot((0, span / 48), (-3.6, 3.6), "time (ms)", "FM (a row each)", xticks=[0, 5, 10, 15],
             yticks=list(ROWS), yfmt=lambda v: str(values[ROWS.index(v)][0]), height=300, legend="below")
    for (v, cls), row in zip(values, ROWS):
        mix = _voice((0, 0, 0, 0x4000, 0, v << 8), osc2=osc2)
        o1 = [m - b for m, b in zip(mix, o2)][-span:]  # osc 2 is the same at every FM: osc 1 alone
        p.line([k / 48 for k in range(span)], [row + y for y in _peaks(o1)], cls, f"FM {v}")
    return p.svg("Osc 1 under FM from osc 2, at the same pitch")


# ---------------------------------------------------------------- 7. the high range: where a frame loses every partial

HR_NOTE = 60                                         # C4
HR_POS = 0x3000                                      # POS 48: Harm.'s frame 6, the 7th partial alone
HR_PARTIAL = 7
HR_WARP = 35
HR_SILENT_DB = -60                                   # where the figure draws "silent"


def _hr_kept(note: float, warp: int) -> int:
    """The highest harmonic the reader keeps for an oscillator at NOTE (TUNE and DETN included)."""
    inc = live.increment(note, live.increment_table())
    sel = live.phase_sel(inc, live.warp_table()[warp]) if warp else inc
    return mip.top_harmonic(mip.level_for(sel))


def _hr_osc2_db(det: int, warp: int, blocks: int = 24) -> float | None:
    """Osc 2 alone (LEV1 0, LEV2 100) on Harm. at POS 48, C4, TUNE 0: its RMS in dB, None when silent."""
    o1 = (HR_POS, 0x100, live.TUN1_ZERO, 0)
    o2 = (HR_POS, 0x100, live.TUN1_ZERO + det * 256, 0x6400)
    y = live.render_two(dsp.tables(), [(float(HR_NOTE), o1, o2)] * blocks,
                        shapes=[(0, 0, 0, 0, warp << 8, 0, 0, 0)] * blocks)[-512:]
    r = math.sqrt(sum(v * v for v in y) / len(y))
    return 20 * math.log10(r) if r > 0 else None


def _hr_scan() -> dict[int, list]:
    return {w: [_hr_osc2_db(d, w) for d in range(64)] for w in (0, HR_WARP)}


def _hr_cliff(levels: list) -> int:
    """The first DETN at which osc 2 is silent."""
    return next(d for d, v in enumerate(levels) if v is None)


def _hr_fold_from() -> int:
    """The first DETN at which the 7th partial is above 24 kHz (it then plays folded back)."""
    return next(d for d in range(64) if HR_PARTIAL * note_hz(HR_NOTE + d) > RATE / 2)


def high_range_levels() -> str:
    notes = [n / 4 for n in range(48 * 4, 120 * 4 + 1)]
    p = Plot((48, 120), (1, 255), "the oscillator's note (TUNE and DETN included)", "highest harmonic kept",
             logy=True, xticks=list(range(48, 121, 12)), yticks=[1, 3, 7, 15, 31, 63, 127, 255],
             xfmt=note_name, height=300, legend="below")
    for warp, cls in ((0, "s0"), (HR_WARP, "s1"), (127, "s3")):
        p.line(notes, [_hr_kept(n, warp) for n in notes], cls, f"WARP {warp}" + (" (off)" if not warp else ""))
    p.hline(HR_PARTIAL)
    p.parts.append(f'<text class="note" x="{p.W - p.R - 4}" y="{p._ty(HR_PARTIAL) + 14:.1f}" text-anchor="end">'
                   '7th partial</text>')   # below the line, past C8: the one gap no curve crosses
    return p.svg("The highest harmonic the reader keeps, against the oscillator's note")


def high_range_cliff(scan: dict[int, list]) -> str:
    p = Plot((0, 63), (HR_SILENT_DB, 0), "DETN (C4, TUNE 0)", "osc 2 (dB)",
             xticks=[0, 12, 24, 36, 48, 60], yticks=[0, -20, -40, -60],
             yfmt=lambda v: "silent" if v == HR_SILENT_DB else str(v), height=260, legend="below")
    for warp, cls in ((0, "s0"), (HR_WARP, "s1")):
        ys = [HR_SILENT_DB if v is None else v for v in scan[warp]]
        p.line(list(range(64)), ys, cls, f"WARP {warp}")
    p.vline(_hr_fold_from())
    p.parts.append(f'<text class="note" x="{p._tx(_hr_fold_from()) - 4:.1f}" y="{p.H - p.B - 6}" text-anchor="end">'
                   'above 24 kHz from here</text>')    # left of the line: the WARP 0 drop is just right of it
    return p.svg("Osc 2's level against DETN, on Harm. at POS 48")


def high_range_table(scan: dict[int, list]) -> str:
    c0, c35, fold = _hr_cliff(scan[0]), _hr_cliff(scan[HR_WARP]), _hr_fold_from()
    rows = []
    for d in sorted({0, 12, c35 - 1, c35, fold, c0 - 1, c0, 57}):
        f7 = HR_PARTIAL * note_hz(HR_NOTE + d)
        cells = [f"{d}", note_name(HR_NOTE + d), f"{f7:,.0f} Hz"]
        for w in (0, HR_WARP):
            v = scan[w][d]
            cells += [_hr_kept(HR_NOTE + d, w), "silent" if v is None else f"{v:.1f} dB"]
        rows.append(cells)
    return table_html(["DETN", "Osc 2's note", "Its 7th partial", "WARP 0: harmonics kept", "WARP 0: osc 2",
                       f"WARP {HR_WARP}: harmonics kept", f"WARP {HR_WARP}: osc 2"], rows)


def high_range_steps(scan: dict[int, list]) -> str:
    c0, c35 = _hr_cliff(scan[0]), _hr_cliff(scan[HR_WARP])
    steps = [
        "On a Waverider track, set page 1's LEV to 0 and TUNE to 0.",
        "On page 2, set TBL to Harm., POS to 48 and LEV to 100. The scope shows seven cycles.",
        f"Play C4. Osc 2 plays its 7th partial, at {HR_PARTIAL * note_hz(HR_NOTE):,.0f} Hz.",
        f"Turn DETN up. At {c0 - 1} osc 2 still plays. At {c0} it is silent.",
        f"Set DETN to {c35}. Osc 2 plays again.",
        f"On page 5, set WARP to {HR_WARP}. Osc 2 is silent. At WARP 0 it plays again.",
    ]
    return "<ol>" + "".join(f"<li>{html.escape(s)}</li>" for s in steps) + "</ol>"


# ---------------------------------------------------------------- 7b. the sub's polyBLEP (0.3.8)

# The unit's reading of the sub alone (LEV1 and LEV2 0, SUB 100, OCT -1), notes 36 to 96 in steps
# of 3, on fsrc2 (Waverider 0.3.8 with the polyBLEP), 2026-10-29: the power between the sub's
# harmonics, 0.18 s into each note, the same measure as _between_db. Notes below 57 put the sub
# under 100 Hz, where the measure is not used.
UNIT_SUB = {
    "SQR": {57: -37.9, 60: -43.4, 63: -42.5, 66: -43.0, 69: -43.4, 72: -43.6, 75: -43.5, 78: -43.2,
            81: -51.6, 84: -42.1, 87: -41.5, 90: -40.8, 93: -40.1, 96: -39.3},
    "PLS": {57: -36.2, 60: -40.8, 63: -40.3, 66: -40.8, 69: -41.2, 72: -41.4, 75: -41.4, 78: -41.2,
            81: -47.1, 84: -40.4, 87: -39.9, 90: -39.4, 93: -38.7, 96: -37.8},
}
SUB_NOTES = list(range(36, 97, 3))             # the unit test's ramp
SUB_MEASURED = [n for n in SUB_NOTES if n >= 57]  # from A3: the sub at 110 Hz and up
SUB_WAVE = {"SQR": 2, "PLS": 3}
SUB_N = 8192                                  # the measure's window, as on the unit


def _sub_f0(note: int) -> float:
    return note_hz(note - 12)                 # OCT -1: the sub plays an octave under the note


def _sub_wave(f0: float, wave: int, count: int, blep: bool) -> np.ndarray:
    """COUNT samples of the sub's WAVE at F0 Hz, gain 1: the DSP's own model with the polyBLEP,
    or the plain wave without it."""
    step = int(f0 / RATE * 2 ** 32)
    out, ph = [], 0
    if blep:
        while len(out) < count:
            ys, ph = live.render_sub(ph, step << 1, (0, 0, wave << 8, 0), BLOCK, g=1.0)
            out += ys
        return np.array(out[:count], float)
    for _ in range(count):
        out.append(live.sub_value(ph, wave))
        ph = (ph + step) & 0xFFFFFFFF
    return np.array(out, float)


def _between_db(x: np.ndarray, f0: float) -> float:
    """The power between the harmonics of F0, against all the power above 20 Hz (Blackman
    window): what the unit's recording was measured with."""
    X = np.abs(np.fft.rfft(x * np.blackman(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    near = np.abs(f / f0 - np.round(f / f0)) < 0.12
    return float(10 * np.log10(X[(~near) & (f > 20)].sum() / X[f > 20].sum()))


def sub_blep_edge() -> str:
    """Two cycles of SQR at a high note, sample by sample: the plain wave, and the wave with
    the polyBLEP, which moves the samples either side of each edge."""
    f0 = _sub_f0(96)
    n = 96
    plain = _sub_wave(f0, 2, n, False)
    blep = _sub_wave(f0, 2, n, True)
    xs = list(range(n))
    p = Plot((0, n - 1), (-1.6, 1.6), "Sample", "Level", xticks=list(range(0, n, 16)),
             yticks=[-1.5, -1, -0.5, 0, 0.5, 1, 1.5], yfmt=lambda v: f"{v:g}", height=260, legend="below")
    p.line(xs, plain, "s2", "SQR without the polyBLEP")
    p.line(xs, blep, "s0", "SQR with the polyBLEP")
    p.dots(xs, blep)
    return p.svg(f"The sub's SQR at {f0:,.0f} Hz, sample by sample, with and without the polyBLEP")


def _sub_series(name: str) -> tuple[list, list]:
    plain, blep = [], []
    for note in SUB_MEASURED:
        f0 = _sub_f0(note)
        skip = 4800                                                      # past the start, as on the unit
        plain.append(_between_db(_sub_wave(f0, SUB_WAVE[name], skip + SUB_N, False)[skip:], f0))
        blep.append(_between_db(_sub_wave(f0, SUB_WAVE[name], skip + SUB_N, True)[skip:], f0))
    return plain, blep


def sub_blep_alias() -> tuple[str, str, str]:
    """For SQR and PLS: the power between the harmonics against the note, for the model with
    and without the polyBLEP, and the unit's reading. Also the table of the same numbers."""
    svgs, rows = [], {}
    for name in ("SQR", "PLS"):
        plain, blep = _sub_series(name)
        unit = UNIT_SUB[name]
        p = Plot((57, 96), (-70, -10), "Note (the sub plays an octave lower)", "Between the harmonics, dB",
                 xticks=[57, 60, 72, 84, 96], xfmt=note_name, yticks=[-70, -60, -50, -40, -30, -20, -10],
                 height=280, legend="below")
        p.line(SUB_MEASURED, plain, "s2", f"{name}, model without the polyBLEP")
        p.line(SUB_MEASURED, blep, "s1", f"{name}, model with the polyBLEP")
        p.dots(list(unit), list(unit.values()), "s0", f"{name}, the unit (dots)")
        svgs.append(p.svg(f"The power between the harmonics of the sub's {name}, against the note"))
        for note, a, b in zip(SUB_MEASURED, plain, blep):
            if note in unit:
                rows.setdefault(note, [note_name(note), f"{_sub_f0(note):,.0f}"])
                rows[note] += [f"{a:.0f} dB", f"{b:.0f} dB", f"{unit[note]:.0f} dB"]
    table = table_html(["Note", "Sub Hz", "SQR without", "SQR with", "SQR, unit",
                        "PLS without", "PLS with", "PLS, unit"], list(rows.values()))
    return svgs[0], svgs[1], table


SPEC_W, SPEC_H = 640, 200
SPEC_STOPS = ((0.0, (8, 6, 14)), (0.25, (58, 18, 92)), (0.5, (160, 40, 90)),
              (0.75, (236, 110, 40)), (1.0, (252, 240, 160)))          # dark to light, on a dark ground


def _spec_png(x: np.ndarray, path: pathlib.Path, floor_db: float = -70.0) -> None:
    """A spectrogram of X, 0 to 24 kHz up the image, time across, as a PNG of SPEC_W x SPEC_H.
    Each column is scaled to its own loudest bin, so every note reads on the same scale, and the
    window is a 4-term Blackman-Harris, whose leakage stays under the floor."""
    from PIL import Image
    n = 2048
    hop = max(1, (len(x) - n) // SPEC_W)
    k_ = np.arange(n) / (n - 1) * 2 * np.pi
    win = 0.35875 - 0.48829 * np.cos(k_) + 0.14128 * np.cos(2 * k_) - 0.01168 * np.cos(3 * k_)
    cols = []
    for k in range(SPEC_W):
        seg = x[k * hop:k * hop + n]
        if len(seg) < n:
            seg = np.pad(seg, (0, n - len(seg)))
        cols.append(np.abs(np.fft.rfft(seg * win)) ** 2)
    S = np.array(cols).T[:1000]                                          # 0 to 23.4 kHz, 5 bins a row
    S = S.reshape(SPEC_H, -1, SPEC_W).mean(1)
    db = 10 * np.log10(S / (S.max(0, keepdims=True) + 1e-30) + 1e-20)
    v = np.clip((db - floor_db) / -floor_db, 0, 1)[::-1]
    xs = [a for a, _ in SPEC_STOPS]
    rgb = np.stack([np.interp(v, xs, [c[i] for _, c in SPEC_STOPS]) for i in range(3)], -1)
    Image.fromarray(rgb.astype(np.uint8)).save(path, optimize=True)


def _sub_ramp(blep: bool) -> np.ndarray:
    """The unit test's ramp in the model: SQR, notes 36 to 96 in steps of 3, half a second each."""
    return np.concatenate([_sub_wave(_sub_f0(n), 2, RATE // 2, blep) for n in SUB_NOTES])


def sub_blep_spectrograms(unit_wav: pathlib.Path | None, write: bool = False) -> str:
    """Three spectrograms of the same ramp: the model without and with the polyBLEP, and the
    unit's recording when UNIT_WAV is given (else the PNG already on the page stays). The PNGs
    are written only with WRITE (the command line), so a test that checks the page writes nothing."""
    art = ROOT / "site/art/waverider"
    if write:
        _spec_png(_sub_ramp(False), art / "sub_blep_without.png")
        _spec_png(_sub_ramp(True), art / "sub_blep_with.png")
    if write and unit_wav and unit_wav.exists():
        import wave
        with wave.open(str(unit_wav)) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, w.getnchannels()).mean(1) / 32768
        env = np.convolve(np.abs(pcm), np.ones(480) / 480, "same")
        on = np.where(env > 10 ** (-60 / 20))[0]
        _spec_png(pcm[on[0]:on[-1]], art / "sub_blep_unit.png")
    figs = [("sub_blep_without.png", "The model, without the polyBLEP"),
            ("sub_blep_with.png", "The model, with the polyBLEP"),
            ("sub_blep_unit.png", "The unit, with the polyBLEP (Waverider 0.3.8)")]
    out = ['<div class="spec-row">']
    for name, cap in figs:
        alt = f"{cap}: a spectrogram of the sub's SQR, from note C2 to C7"
        out.append(f'<figure class="spec"><img src="art/waverider/{name}" alt="{html.escape(alt)}" '
                   f'width="{SPEC_W}" height="{SPEC_H}"><figcaption>{html.escape(cap)}</figcaption></figure>')
    out.append("</div>")
    return "".join(out)


# ---------------------------------------------------------------- the page

# ---------------------------------------------------------------- 8. MIDI: the CC and NRPN of every knob

# The records Waverider does not rename keep WaveTone's long name, which the header shows
# (the firmware's parameter table, records 241, 245 and 249).
STOCK_LONG_NAMES = {241: "Osc1 Level", 245: "Osc2 Level", 249: "Osc Phase Reset"}


def midi_map() -> str:
    """Every knob place of the five pages with its CC and NRPN (docs/waverider-midi.md), from the
    map the firmware answers with (pages.midi_rows)."""
    rows = []
    for (rid, nrpn, cc), (page, knob) in zip(pages.midi_rows(), ((p, k) for p, ids in enumerate(pages.PAGES)
                                                                for k, r in enumerate(ids) if r)):
        rows.append([str(page + 1), "ABCDEFGH"[knob], pages.label(rid), pages.LONG_NAMES.get(rid, STOCK_LONG_NAMES.get(rid, "")),
                     cc, f"{nrpn >> 7}:{nrpn & 127}"])
    return table_html(["Page", "Knob", "Label", "Name", "CC", "NRPN"], rows)


def figures(dnx: pathlib.Path | None, unit_wav: pathlib.Path | None = None, write: bool = False) -> dict[str, str]:
    alias_svg, alias_table, _ = alias_measure()
    blep_sqr, blep_pls, blep_table = sub_blep_alias()
    scan = _hr_scan()
    return {
        "hrlevels": high_range_levels(),
        "hrcliff": high_range_cliff(scan),
        "hrtable": high_range_table(scan),
        "hrsteps": high_range_steps(scan),
        "midimap": midi_map(),
        "geometry": geometry_table(),
        "dnx": dnx_proposals(dnx),
        "posmap": pos_map(),
        "blend": frame_blend(),
        "interp": interp_response(),
        "alias": alias_svg,
        "aliastable": alias_table,
        "levels": levels_table(),
        "dclk": dclk_figure(),
        "dclkcurve": dclk_curve(),
        "smtcurve": smt_curve(),
        "smt": smt_response(),
        "smtlfo": smt_lfo_table(),
        "smtvalues": smt_values_table(),
        "noise": noise_spectra(),
        "colr": colr_spectra(),
        "dec": dec_curve(),
        "foldcurve": fold_curve(),
        "foldwave": fold_wave(),
        "shaper": shaper_figure(),
        "warpcurve": warp_curve(),
        "warpwave": warp_wave(),
        "fmwave": fm_wave(),
        "subblepedge": sub_blep_edge(),
        "subblepsqr": blep_sqr,
        "subbleppls": blep_pls,
        "subbleptable": blep_table,
        "subblepspec": sub_blep_spectrograms(unit_wav, write),
    }


TECH = re.compile(r"(<!-- dnfw:tech (\w+) -->).*?(<!-- /dnfw:tech -->)", re.S)


def rewrite(text: str, figs: dict[str, str]) -> str:
    missing = set(figs) - {m.group(2) for m in TECH.finditer(text)}
    if missing:
        raise SystemExit(f"the page has no region for {sorted(missing)}")
    return TECH.sub(lambda m: m.group(1) + figs[m.group(2)] + m.group(3), text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--page", type=pathlib.Path, default=ROOT / "site/waverider.html")
    ap.add_argument("--dnx", type=pathlib.Path, default=pathlib.Path("D:/01_Code/Z_Personal/DNX"))
    ap.add_argument("--unit-wav", type=pathlib.Path, default=None,
                    help="the unit's recording of the sub ramp, for its spectrogram (kept off the repository)")
    args = ap.parse_args(argv)
    figs = figures(args.dnx, args.unit_wav, write=True)
    args.page.write_text(rewrite(args.page.read_text(encoding="utf-8"), figs), encoding="utf-8", newline="\n")
    print(f"wrote {len(figs)} figures and tables into {args.page}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
