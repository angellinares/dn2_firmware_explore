/**
 * The three wavetable cards of the LFO waves mod: each table drawn as the firmware reads it, with
 * its POS control, and a file to replace it with.
 *
 * Shared by the LFO Waves page (lfo-page.js) and the Mod Composer (compose-page.js). The tables
 * themselves are read and reduced in `wavetable.js`.
 */

import { wireDrop } from "./shell.js";
import { WavetableError, fromBytes, loadTable, sample } from "../wavetable.js";
import { TABLES, defaultTables } from "../mods/lfowaves.js";

export const OURS_NAMES = ["basic shapes", "harmonic sweep", "vowels"];
export const ours = () => defaultTables().map(fromBytes);

/** Three slots, each { table, custom: the user's file name or null, pos }, with our tables in them. */
export const freshSlots = () => ours().map((table) => ({ table, custom: null, pos: 64 }));

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Seven faint frames stacked, and the curve at POS on top, as the firmware reads it. */
export function drawTable(canvas, slot) {
  const ratio = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 280, h = Math.round(w * 0.42);
  canvas.width = Math.round(w * ratio);
  canvas.height = Math.round(h * ratio);
  const g = canvas.getContext("2d");
  g.setTransform(ratio, 0, 0, ratio, 0, 0);
  g.clearRect(0, 0, w, h);
  const mid = h / 2, amp = h * 0.42;

  g.strokeStyle = css("--rule");
  g.lineWidth = 1;
  g.beginPath(); g.moveTo(0, mid); g.lineTo(w, mid); g.stroke();

  g.strokeStyle = css("--ink-soft");
  g.globalAlpha = 0.28;
  slot.table.forEach((frame) => {
    g.beginPath();
    for (let x = 0; x <= w; x++) {
      const p = (x / w) * 32, s = Math.floor(p) % 32, t = p - Math.floor(p);
      const v = (frame[s] * (1 - t) + frame[(s + 1) % 32] * t) / 127;
      x ? g.lineTo(x, mid - v * amp) : g.moveTo(x, mid - v * amp);
    }
    g.stroke();
  });
  g.globalAlpha = 1;

  g.strokeStyle = css("--accent");
  g.lineWidth = 2;
  g.beginPath();
  for (let x = 0; x <= w; x++) {
    const v = sample(slot.table, Math.min(x / w, 0.999999), slot.pos);
    x ? g.lineTo(x, mid - v * amp) : g.moveTo(x, mid - v * amp);
  }
  g.stroke();
}

/** A file that could not be used: say which file, why, and that the slot kept its table. */
function refuse(err, file, slot, e) {
  const why = e instanceof WavetableError ? e.message : (e.message ?? String(e));
  err.textContent = `Couldn't use ${file}: ${why}. ${slot} keeps its current table.`;
}

/**
 * One card per table into HOST, for SLOTS (freshSlots()). ONCHANGE() runs after a table is
 * replaced or reset. IDPREFIX keeps the controls' ids apart when a page has more than one set.
 */
export function tableCards(host, slots, { onChange = () => {}, idPrefix = "" } = {}) {
  const original = ours();
  const redraw = () => { tableCards(host, slots, { onChange, idPrefix }); onChange(); };
  host.innerHTML = "";
  TABLES.forEach((t, k) => {
    const slot = slots[k];
    const card = document.createElement("div");
    card.className = "table" + (slot.custom ? " custom" : "");
    card.innerHTML = `
      <h3><span></span><span class="src"></span></h3>
      <canvas></canvas>
      <label class="pos">POS <input type="range" min="0" max="127"><output></output></label>
      <div class="row">
        <label class="filebtn">Use your own…<input type="file" accept=".wav,.WAV,.json" hidden></label>
        <button type="button">Use ours</button>
      </div>
      <div class="err" role="status"></div>`;
    card.querySelector("h3 span").textContent = t.name;
    card.querySelector(".src").textContent = slot.custom ?? `ours: ${OURS_NAMES[k]}`;
    const canvas = card.querySelector("canvas");
    const range = card.querySelector("input[type=range]");
    const out = card.querySelector("output");
    const file = card.querySelector("input[type=file]");
    const reset = card.querySelector("button");
    const err = card.querySelector(".err");
    range.id = `${idPrefix}pos${k + 1}`;
    file.id = `${idPrefix}table${k + 1}`;
    range.value = slot.pos;
    out.textContent = slot.pos;
    reset.disabled = !slot.custom;

    const use = async (f) => {
      try {
        slot.table = loadTable(new Uint8Array(await f.arrayBuffer()), f.name);
        slot.custom = f.name;
        redraw();
      } catch (e) {
        refuse(err, f.name, t.name, e);
      }
    };
    range.addEventListener("input", () => {
      slot.pos = Number(range.value);
      out.textContent = slot.pos;
      drawTable(canvas, slot);
    });
    file.addEventListener("change", () => { if (file.files?.[0]) use(file.files[0]); });
    reset.addEventListener("click", () => {
      slot.table = original[k];
      slot.custom = null;
      redraw();
    });
    wireDrop(card, use);
    host.append(card);
    requestAnimationFrame(() => drawTable(canvas, slot));
  });
}
