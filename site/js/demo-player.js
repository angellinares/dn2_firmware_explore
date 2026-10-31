/**
 * A sound demo drawn as the Digitone II's 128 x 64 screen: the recording's level as one-bit
 * columns, solid where it has played, dotted where it has not, with the solo spans marked.
 *
 * Markup (`data-demo` on the wrapper; `data-peaks` is generated, see test_site_demo_player.py):
 *   <div data-demo data-title="WAVERIDER DEMO" data-duration="120.5" data-solos="0-58,110-120.5"
 *        data-peaks=".02,.20,...">  canvas, input[type=range], button, audio  </div>
 */

import { FONT } from "./font3x5.js";

export const W = 128, H = 64;
const X0 = 16, COLS = 96, MID = 38, HALF = 14;

const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function text(px, s, x, y, on = 1) {
  for (const ch of s.toUpperCase()) {
    const g = FONT[ch] || FONT[" "];
    g.forEach((row, dy) => [...row].forEach((b, dx) => {
      const X = x + dx, Y = y + dy;
      if (b === "1" && X >= 0 && X < W && Y >= 0 && Y < H) px[Y * W + X] = on;
    }));
    x += 4;
  }
}

/** The frame at time T of D seconds, as W*H bytes (1 = lit). */
export function frame({ peaks, solos, title }, t, d) {
  const px = new Uint8Array(W * H);
  const fill = (x, y, w, h, on = 1) => {
    for (let Y = y; Y < y + h; Y++) for (let X = x; X < x + w; X++) px[Y * W + X] = on;
  };
  fill(0, 0, W, 9);                                            // the header, inverted
  text(px, title, 2, 2, 0);
  const col = (s) => Math.round(Math.min(1, Math.max(0, s / d)) * COLS);
  for (const [a, b] of solos) {                                // a span Waverider plays alone
    const x = X0 + col(a), w = Math.max(1, col(b) - col(a));
    fill(x, 13, w, 1);
    const label = w >= 36 ? "WR ALONE" : "WR";
    text(px, label, col(b) >= COLS ? X0 + COLS - label.length * 4 + 1 : x, 15);
  }
  const cut = Math.min(COLS, Math.floor(t / d * COLS));
  const n = peaks.length;
  for (let i = 0; i < COLS; i++) {
    const r = peaks[Math.min(n - 1, Math.floor(i * n / COLS))];
    const h = Math.max(1, Math.min(HALF, Math.round(r / 0.34 * HALF)));
    const x = X0 + i;
    for (let y = MID - h; y < MID + h; y++)
      if (i < cut || ((x + y) & 1) === 0) px[y * W + x] = 1;   // played solid, the rest dotted
  }
  fill(X0 + Math.min(COLS - 1, cut), 22, 1, 32);               // the play position
  text(px, fmt(t), X0, 57);
  const total = fmt(d);
  text(px, total, X0 + COLS - total.length * 4 + 1, 57);
  return px;
}

export function mount(el) {
  const cfg = {
    title: el.dataset.title || "DEMO",
    peaks: el.dataset.peaks.split(",").map(Number),
    solos: (el.dataset.solos || "").split(",").filter(Boolean).map((s) => s.split("-").map(Number)),
  };
  const canvas = el.querySelector("canvas"), seek = el.querySelector("input[type=range]");
  const button = el.querySelector("button"), audio = el.querySelector("audio");
  const ctx = canvas.getContext("2d"), img = ctx.createImageData(W, H);
  let d = Number(el.dataset.duration) || 1, raf = 0;

  function draw() {
    const px = frame(cfg, audio.currentTime || 0, d);
    for (let i = 0; i < px.length; i++) {
      const v = px[i] ? 255 : 0;
      img.data.set([v, v, v, 255], i * 4);
    }
    ctx.putImageData(img, 0, 0);
    seek.value = String(audio.currentTime || 0);
  }
  function loop() { draw(); raf = audio.paused ? 0 : requestAnimationFrame(loop); }
  function playing(on) {
    button.setAttribute("aria-label", on ? "Pause the demo" : "Play the demo");
    button.dataset.playing = on ? "1" : "";
    if (on && !raf) raf = requestAnimationFrame(loop);
  }

  seek.max = String(d);
  button.addEventListener("click", () => { if (audio.paused) audio.play(); else audio.pause(); });
  seek.addEventListener("input", () => { audio.currentTime = Number(seek.value); draw(); });
  audio.addEventListener("loadedmetadata", () => { if (audio.duration) { d = audio.duration; seek.max = String(d); draw(); } });
  audio.addEventListener("play", () => playing(true));
  audio.addEventListener("pause", () => { playing(false); draw(); });
  audio.addEventListener("ended", () => { playing(false); draw(); });
  draw();
}

if (typeof document !== "undefined") document.querySelectorAll("[data-demo]").forEach(mount);
