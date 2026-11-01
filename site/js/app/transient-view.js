/**
 * One transient slot on screen: its waveform, its fit, its per-sample controls, and playback.
 *
 * Shared by the Transient Swapper page (transients-page.js) and the Mod Composer
 * (compose-page.js), so the two show a slot the same way. Every decision about the samples lives
 * in `audio.js` and `mods/transients.js`. This file only draws and plays.
 */

import { decode } from "../audio.js";
import { RATE } from "../mods/transients.js";

/** An audio FILE -> a replacement, not yet fitted: { name, source, options, fitted: null }. */
export async function readSample(file) {
  const source = await decode(await file.arrayBuffer());
  return { name: file.name, source, options: { leadMs: 3, startMs: null, gain: 1 }, fitted: null };
}

export const ms = (samples) => `${((1000 * samples) / RATE).toFixed(1)} ms`;

/**
 * Created on first play, not at load.
 *
 * Constructing an AudioContext eagerly means a browser that refuses one — no
 * output device, a hardened profile, a headless render — throws while the
 * page's module is still evaluating, and the whole page renders nothing. Audition is
 * a convenience; building firmware is the job, and the job should not depend
 * on the convenience being available.
 */
let audio = null;

function audioContext() {
  if (audio === null) {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null;
    try {
      audio = new Ctor();
    } catch {
      return null;
    }
  }
  return audio;
}

export function play(samples) {
  if (!samples?.length) return;
  const ctx = audioContext();
  if (!ctx) return;
  if (ctx.state === "suspended") ctx.resume();
  const buffer = ctx.createBuffer(1, samples.length, RATE);
  buffer.copyToChannel(samples instanceof Float32Array ? samples
                       : Float32Array.from(samples), 0);
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  source.start();
}

/**
 * What a slot does with its sound, as a line and a tooltip -> { text, title, cut }.
 * ENTRY is the user's replacement or null, WAS the factory sound's length in samples, SIZE the slot's.
 */
export function fitText(entry, was, size) {
  if (!entry) {
    // A factory transient that the layout cuts or pads: say so on the slot.
    return {
      cut: was > size,
      text: was > size ? `factory ${ms(was)}, cut to ${ms(size)}` : was < size ? `factory ${ms(was)}, padded` : "",
      title: was > size
        ? `The factory transient is ${ms(was)}. Equal slots keep its first ${ms(size)}.`
        : was < size ? `The factory transient is ${ms(was)}. The rest of the slot is silence.` : "",
    };
  }
  const whole = entry.source.length / RATE;
  const kept = size / RATE;
  return {
    cut: entry.fitted.truncated,
    text: entry.fitted.truncated
      ? `cut ${whole.toFixed(2)}s → ${(kept * 1000).toFixed(1)}ms`
      : `${(whole * 1000).toFixed(0)}ms, padded to ${(kept * 1000).toFixed(1)}ms`,
    title: entry.fitted.truncated
      ? `Your file is ${whole.toFixed(2)} s. A slot holds ${(kept * 1000).toFixed(1)} ms, `
        + `so only the window starting at ${(entry.fitted.start / RATE * 1000).toFixed(0)} ms is kept. `
        + "Move it with the start control."
      : "Your file is shorter than the slot. The rest is silence.",
  };
}

/**
 * The per-sample controls, into HOST. REFIT() fits ENTRY again after a change, REPAINT() redraws.
 *
 * Per sample and not global, because the right lead depends on the sound: a
 * sharp click wants almost none, a soft attack wants more or the onset detector
 * fires partway up the rise and cuts the front off. One value for a whole bank
 * is the kind of fixed assumption this project keeps having to retract.
 */
export function tuning(host, entry, { refit, repaint }) {
  host.innerHTML = "";

  const startLimit = Math.max(0, Math.floor((entry.source.length / RATE) * 1000) - 1);
  const controls = [
    { key: "leadMs", label: "lead", min: 0, max: 50, step: 0.5, unit: "ms",
      disabled: () => entry.options.startMs !== null },
    { key: "startMs", label: "start", min: 0, max: Math.max(startLimit, 1), step: 1,
      unit: "ms", nullable: true },
    { key: "gain", label: "gain", min: 0.1, max: 4, step: 0.05, unit: "x" },
  ];

  for (const control of controls) {
    const label = document.createElement("label");
    label.textContent = control.label;

    const range = document.createElement("input");
    range.type = "range";
    range.min = String(control.min);
    range.max = String(control.max);
    range.step = String(control.step);
    range.value = String(entry.options[control.key] ?? control.min);
    range.setAttribute("aria-label", control.label);

    const output = document.createElement("output");
    const show = () => {
      const value = entry.options[control.key];
      output.textContent = value === null ? "auto" : `${value}${control.unit}`;
      if (control.disabled) range.disabled = control.disabled();
    };
    show();

    range.addEventListener("input", () => {
      entry.options[control.key] = Number(range.value);
      refit();
      host.querySelectorAll("output").forEach((o, i) => {
        const c = controls[i];
        const v = entry.options[c.key];
        o.textContent = v === null ? "auto" : `${v}${c.unit}`;
      });
      host.querySelectorAll("input[type=range]").forEach((r, i) => {
        if (controls[i].disabled) r.disabled = controls[i].disabled();
      });
      repaint();
    });
    range.addEventListener("change", () => play(entry.fitted.samples));

    host.append(label, range, output);

    // "start" is the one control with a meaningful off position: unset means
    // "find the onset for me", which is not a number on the slider's scale.
    if (control.nullable) {
      const auto = document.createElement("button");
      auto.type = "button";
      auto.textContent = "auto";
      auto.style.gridColumn = "1 / -1";
      auto.style.justifySelf = "start";
      auto.addEventListener("click", () => {
        entry.options.startMs = entry.options.startMs === null ? Number(range.value) : null;
        refit();
        tuning(host, entry, { refit, repaint });
        repaint();
        play(entry.fitted.samples);
      });
      host.append(auto);
    }
  }
}

/**
 * Draw one slot into CANVAS. FACTORY is its current sound fitted to the slot, ENTRY the user's
 * replacement or null, SIZE the slot's length in samples.
 *
 * **With no replacement:** the current sound as the build writes it, filling the canvas.
 *
 * **With a replacement:** the user's *whole* file, with the slot's length that will
 * actually be imported shaded and drawn in the accent; everything outside the
 * shaded band is greyed, because it is being thrown away.
 *
 * Drawing only the fitted part — which is what this did first — hides the
 * decision the tool just made on the user's behalf. A slot has a fixed length
 * and most files people reach for are longer, so the interesting
 * question is never "what does the slot contain" but "which part of my sample
 * did it take". Shading it answers that, and the `start` control visibly slides
 * the band.
 */
export function paint(canvas, { factory, entry, size }) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  const mid = height / 2;
  const style = getComputedStyle(document.documentElement);
  const ink = style.getPropertyValue("--ink-soft").trim() || "#888";
  const accent = style.getPropertyValue("--accent").trim() || "#b4530a";
  const band = style.getPropertyValue("--accent-dim").trim() || "#f0e3d6";

  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = ink;
  ctx.globalAlpha = 0.35;
  ctx.beginPath();
  ctx.moveTo(0, mid);
  ctx.lineTo(width, mid);
  ctx.stroke();
  ctx.globalAlpha = 1;

  if (!entry) {
    trace(ctx, factory, width, height, accent, 1, 0, width);
    return;
  }

  // The canvas spans whichever is longer: the user's file, or the window the
  // slot takes. A file *shorter* than a slot is padded with silence at the end,
  // and spanning only the file would hide that padding entirely -- the user
  // would see a full-width waveform and have no idea most of the slot is empty.
  const span = Math.max(entry.source.length, entry.fitted.start + size);
  const from = (entry.fitted.start / span) * width;
  const to = ((entry.fitted.start + size) / span) * width;
  const sourceEnd = (entry.source.length / span) * width;

  // The band first, so the waveform sits on top of it rather than under.
  ctx.fillStyle = band;
  ctx.fillRect(from, 0, Math.max(to - from, 2), height);
  ctx.strokeStyle = accent;
  ctx.globalAlpha = 0.6;
  ctx.beginPath();
  ctx.moveTo(from + 0.5, 0);
  ctx.lineTo(from + 0.5, height);
  ctx.moveTo(to - 0.5, 0);
  ctx.lineTo(to - 0.5, height);
  ctx.stroke();
  ctx.globalAlpha = 1;

  // Discarded either side in grey, the kept window in the accent. The source is
  // drawn against its own span, so it stops where the file stops and any
  // padding inside the band reads as the flat line it will actually be.
  trace(ctx, entry.source, sourceEnd, height, ink, 0.4, 0, from);
  trace(ctx, entry.source, sourceEnd, height, ink, 0.4, to, sourceEnd);
  trace(ctx, entry.source, sourceEnd, height, accent, 1, from, Math.min(to, sourceEnd));
}

/**
 * Draw `samples` across the full canvas, painting only columns in [x0, x1).
 *
 * The clip range is a column range rather than a sample range on purpose: the
 * kept window and the discarded parts must share one horizontal scale, or the
 * shaded band would not line up with the waveform under it.
 */
function trace(ctx, samples, width, height, colour, alpha, x0, x1) {
  if (!samples?.length) return;
  const mid = height / 2;
  const step = samples.length / width;
  ctx.globalAlpha = alpha;
  ctx.fillStyle = colour;
  const lo = Math.max(0, Math.floor(x0));
  const hi = Math.min(width, Math.ceil(x1));
  for (let x = lo; x < hi; x++) {
    let high = 0;
    let low = 0;
    const from = Math.floor(x * step);
    const to = Math.min(samples.length, Math.max(from + 1, Math.floor((x + 1) * step)));
    for (let i = from; i < to; i++) {
      if (samples[i] > high) high = samples[i];
      if (samples[i] < low) low = samples[i];
    }
    const top = mid - high * (mid - 1);
    const bottom = mid - low * (mid - 1);
    ctx.fillRect(x, top, 1, Math.max(1, bottom - top));
  }
  ctx.globalAlpha = 1;
}
