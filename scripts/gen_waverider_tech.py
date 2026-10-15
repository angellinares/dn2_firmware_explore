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

from dnfw.waverider import dsp, geometry, live, mip, render, table3  # noqa: E402
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
            lx = bx
            for cls, label in self.legend:
                out.append(f'<line class="{cls}" x1="{lx}" y1="{self.H - 10}" x2="{lx + 22}" y2="{self.H - 10}"/>')
                out.append(f'<text class="legend" x="{lx + 28}" y="{self.H - 6}">{html.escape(label)}</text>')
                lx += 40 + 7 * len(label)
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
             xfmt=lambda v: f"{v:g}", height=260, legend="tr")
    p.line(f[keep], resp["linear"][keep], "s2", "linear (the plain-table reader)")
    p.line(f[keep], resp["Hermite"][keep], "s0", "4-point Hermite (the shipped reader)")
    p.vline(1, "the first image", low=True)
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
             xticks=[0, 2, 4, 6, 8, 10, 12], yticks=[-1, 0, 1], height=240, xfmt=lambda v: f"{v:g}",
             legend="bl")
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
    vs = list(range(0, 127))
    p = Plot((0, 126), (1, 1000), "SLW (the knob's value; 127 is Off)", "time constant (ms)", logy=True,
             xticks=[0, 14, 28, 42, 56, 70, 84, 98, 112, 126], yticks=[1, 3, 10, 30, 100, 300, 1000],
             height=220, yfmt=lambda v: f"{v:g}")
    p.line(vs, [live.smth_tau(v) * 1000 for v in vs], "s0")
    return p.svg("The slew's time constant for each SLW value")


def smt_response() -> str:
    """What the glide does to each source of POS: a jump of the knob, a sine LFO at 4 Hz,
    and a p-lock that comes with a note (the glide snaps). SMT 56 (62.5 ms), 1,500 steps a second."""
    smt = 56 << 8
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
             yticks=[0, 30, 60, 90, 120], height=260, xfmt=lambda v: f"{v:g}", legend="tr")
    p.line(t, target, "s2", "POS from the knob, the LFO and the p-lock")
    p.line(t, glided, "s0", "POS the reader plays, SLW 56 (62.5 ms)")
    p.vline(0.1, "knob jump", low=True)
    p.vline(0.45, "LFO 4 Hz", low=True)
    p.vline(0.95, "trig with a lock", low=True)
    return p.svg("What SLW does to a knob jump, an LFO and a p-lock")


def smt_values_table() -> str:
    """For a few SMT values: the time constant, the filter's coefficient k (the DSP's float32
    table), its cutoff, and the time to reach 95 % of a jump."""
    rows = []
    for v in (0, 14, 28, 42, 56, 70, 84, 98, 112, 126, 127):
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
    for v in (98, 84, 70, 56, 42):
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


# ---------------------------------------------------------------- 6. page 5: FOLD, NPOS, Ring and AM

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
             xticks=[0, 2, 4, 6, 8], yticks=[-1, 0, 1], height=260, legend="below")
    for word, cls in ((0, "s0"), (0x3000, "s1"), (0x7F00, "s3")):
        ys = _voice((word, 0, 0, 0x4000))[-span:]
        p.line([k / 48 for k in range(span)], _peaks(ys), cls, f"FOLD {word >> 8}")
    return p.svg("Prim. at POS 64, C3, folded")


def npos_figure() -> str:
    blocks = 300                                      # 0.2 s
    p = Plot((0, 200), (0, 15), "time (ms)", "frame", xticks=[0, 50, 100, 150, 200],
             yticks=[0, 5, 10, 15], height=260, legend="below")
    for word, cls, smth in ((0x4000, "s1", live.SMTH_OFF), (0x7F00, "s3", live.SMTH_OFF), (0x7F00, "s0", 56)):
        x, s, ys = live.npos_seeds()[0], 0.0, []
        for b in range(blocks):
            off, x = live.npos_offset(x, word)
            pos = live.position(max(0, 0x3C00 + off))
            s = live.smooth(s, pos, smth << 8, b == 0)       # SLW as its frame word
            ys.append(live.trunc(s) / 65536)
        label = f"NPOS {word >> 8}" + ("" if smth == live.SMTH_OFF else f", SLW {smth}")
        p.line([b / 1.5 for b in range(blocks)], ys, cls, label)
    return p.svg("The frame that plays, POS at 64, over 0.2 s")


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


# ---------------------------------------------------------------- the page

def figures(dnx: pathlib.Path | None) -> dict[str, str]:
    alias_svg, alias_table, _ = alias_measure()
    return {
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
        "npos": npos_figure(),
        "shaper": shaper_figure(),
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
    args = ap.parse_args(argv)
    figs = figures(args.dnx)
    args.page.write_text(rewrite(args.page.read_text(encoding="utf-8"), figs), encoding="utf-8", newline="\n")
    print(f"wrote {len(figs)} figures and tables into {args.page}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
