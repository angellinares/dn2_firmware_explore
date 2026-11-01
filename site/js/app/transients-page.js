/**
 * The Transient Swapper page: wiring, and nothing else.
 *
 * Every decision that could be *wrong* -- codec, container, integrity, bank
 * location, slot fitting -- lives in the modules under `site/js/` and is tested
 * in `test/test_js_*.py` against real firmware. This file reads the DOM, calls
 * them in order, and draws the result. It is deliberately the only untested
 * file in the stack, which is only defensible because it decides nothing.
 *
 * Two rules it does enforce, because they are about what reaches a user:
 *
 * - **Nothing downloads that has not verified.** The rebuilt image is reloaded
 *   from its own bytes and re-checked, and the download link is only created if
 *   every field passes. `docs/PRINCIPLES.md`: nothing is flashed that the
 *   toolchain cannot verify end to end, and a browser is not an excuse.
 * - **Nothing leaves the tab.** There is no fetch in this file and no server to
 *   fetch from; the page is static files.
 */

import {
  $, buildAndOffer, openFirmware as openFirmwareShell, status, wireDrop,
} from "./shell.js";
import { fit } from "../audio.js";
import {
  COUNT, EQUAL_SAMPLES, RATE, apply, extract, fit as fitEntry, lengths, toEntry, toFloat,
} from "../mods/transients.js";
import { fitText, ms, paint as paintSlot, play, readSample, tuning } from "./transient-view.js";

/** Page state. One object so `reset` is one assignment and cannot half-clear. */
let state = null;

function fresh() {
  return {
    firmware: null,
    filename: "firmware.syx",
    equal: false,                 // the layout: factory sizes, or equal slots
    raw: [],                      // the current sound of each slot, as the table plays it
    factory: [],                  // Float32Array per slot: that sound fitted to the slot
    replacements: new Map(),      // slot -> { name, source, options, fitted }
  };
}

/** A slot's length in samples, in the layout chosen. */
const size = (slot) => lengths(state.equal)[slot];

function fitFor(slot, entry) {
  return fit(entry.source, { ...entry.options, length: size(slot) });
}

function refreshFactory() {
  state.factory = state.raw.map((pcm, slot) => toFloat(fitEntry(pcm, size(slot))));
}

/** The layout checkbox: refit every slot to its new length and redraw. */
function setLayout(equal) {
  state.equal = equal;
  refreshFactory();
  for (const [slot, entry] of state.replacements) entry.fitted = fitFor(slot, entry);
  for (let slot = 0; slot < COUNT; slot++) refreshSlot(slot);
  updateStatus();
}

// ---------------------------------------------------------------- step 1

async function openFirmware(file) {
  state = fresh();
  state.filename = file.name;
  return openFirmwareShell(file, {
    onReady: (firmware) => {
      state.firmware = firmware;
      state.raw = extract(firmware);
      state.equal = $("equalSlots").checked;
      refreshFactory();
      drawSlots();
      for (let slot = 0; slot < COUNT; slot++) refreshSlot(slot);
      for (const id of ["step2", "step3", "bar"]) $(id).classList.remove("hidden");
      status(`Loaded. ${COUNT} slots ready.`);
    },
    extraFacts: (fw) => [["Packets", fw.packets.toLocaleString()]],
  });
}

// ---------------------------------------------------------------- step 2

function drawSlots() {
  const host = $("slots");
  host.innerHTML = "";
  for (let slot = 0; slot < COUNT; slot++) host.append(slotCard(slot));
}

function slotCard(slot) {
  const card = document.createElement("div");
  card.className = "slot";
  card.dataset.slot = String(slot);

  const top = document.createElement("div");
  top.className = "slot-top";
  const n = document.createElement("span");
  n.className = "slot-n";
  n.textContent = String(slot).padStart(2, "0");
  // The TRAN value that plays this slot: the DSP's table has one entry per TRAN
  // step of 4 (docs/tran-mapping.md).
  const tran = document.createElement("span");
  tran.className = "slot-tran";
  const value = 4 * slot;
  tran.textContent = `TRAN ${value}`;
  tran.title = `Set TRAN to ${value} to hear this slot`;
  // The slot's length: how much of a sample it can hold, in the layout chosen.
  const len = document.createElement("span");
  len.className = "slot-len";
  const name = document.createElement("span");
  name.className = "slot-name";
  name.textContent = "factory";
  // Whether this slot had to cut the user's file, and from what. Every slot has
  // the same length, so truncation is not an edge case: most samples people reach
  // for are longer. `fit` returns the flag.
  const fit = document.createElement("span");
  fit.className = "slot-fit";
  top.append(n, tran, len, name, fit);

  const canvas = document.createElement("canvas");
  canvas.width = 460;
  canvas.height = 92;
  canvas.title = "Click to hear this slot";
  canvas.addEventListener("click", () => play(currentSamples(slot)));

  const actions = document.createElement("div");
  actions.className = "slot-actions";

  const input = document.createElement("input");
  input.type = "file";
  input.accept = "audio/*";
  input.id = `file-${slot}`;
  const label = document.createElement("label");
  label.className = "filebtn";
  label.htmlFor = input.id;
  label.textContent = "Replace";
  input.addEventListener("change", () => {
    if (input.files?.[0]) loadSample(slot, input.files[0]);
  });

  const revert = document.createElement("button");
  revert.textContent = "Revert";
  revert.disabled = true;
  revert.addEventListener("click", () => {
    state.replacements.delete(slot);
    refreshSlot(slot);
    updateStatus();
  });

  actions.append(label, input, revert);

  const tune = document.createElement("div");
  tune.className = "tune hidden";

  card.append(top, canvas, actions, tune);
  wireDrop(card, (file) => loadSample(slot, file));
  requestAnimationFrame(() => paint(slot));
  return card;
}

function card(slot) {
  return $("slots").querySelector(`.slot[data-slot="${slot}"]`);
}

/** What this slot currently holds: the fitted replacement, or the factory. */
function currentSamples(slot) {
  return state.replacements.get(slot)?.fitted?.samples ?? state.factory[slot];
}

async function loadSample(slot, file) {
  status(`Decoding ${file.name}…`, true);
  try {
    const entry = await readSample(file);
    const { source } = entry;
    entry.fitted = fitFor(slot, entry);
    state.replacements.set(slot, entry);
    refreshSlot(slot);
    play(entry.fitted.samples);
    updateStatus();
    if (entry.fitted.truncated) {
      status(`${file.name} is ${(source.length / RATE).toFixed(2)}s — `
             + `cut to the ${ms(size(slot))} this slot holds.`);
    }
  } catch (error) {
    status(`${file.name}: ${error.message ?? error}`);
  }
}

function refreshSlot(slot) {
  const element = card(slot);
  const entry = state.replacements.get(slot);
  element.classList.toggle("filled", Boolean(entry));
  element.querySelector(".slot-name").textContent = entry ? entry.name : "factory";
  element.querySelector(".slot-len").textContent = ms(size(slot));

  const fit = element.querySelector(".slot-fit");
  const line = fitText(entry, state.raw[slot].length / 2, size(slot));
  fit.classList.toggle("cut", line.cut);
  fit.textContent = line.text;
  fit.title = line.title;
  // The note already says "factory": the name would only repeat it.
  if (!entry && line.text) element.querySelector(".slot-name").textContent = "";
  element.querySelector(".slot-actions button").disabled = !entry;

  const tune = element.querySelector(".tune");
  tune.classList.toggle("hidden", !entry);
  if (entry) {
    tuning(tune, entry, { refit: () => { entry.fitted = fitFor(slot, entry); }, repaint: () => paint(slot) });
  }
  paint(slot);
}

/** Draw one slot (transient-view.js). */
function paint(slot) {
  paintSlot(card(slot)?.querySelector("canvas"),
    { factory: state.factory[slot], entry: state.replacements.get(slot), size: size(slot) });
}

// ---------------------------------------------------------------- step 3

async function buildImage() {
  const count = state.replacements.size;
  if (!count) {
    status("Nothing replaced yet — drop audio on a slot first.");
    return;
  }
  const entries = new Map();
  for (const [slot, entry] of state.replacements) {
    entries.set(slot, toEntry(entry.fitted.samples, size(slot)));
  }
  const applied = apply(state.firmware, entries, { equal: state.equal });
  await buildAndOffer(state.firmware, new Map([[7, applied.section]]), {
    filename: state.filename, mod: "transients", suffix: "transients",
    note: `${count} slot${count === 1 ? "" : "s"} replaced, `
      + (state.equal ? `equal slots of ${ms(EQUAL_SAMPLES)}` : "factory slot sizes"),
  });
}

// ---------------------------------------------------------------- wiring

function updateStatus() {
  const count = state.replacements.size;
  status(count ? `${count} of ${COUNT} slots replaced.` : `${COUNT} slots ready.`);
}

state = fresh();
wireDrop($("drop"), openFirmware);
$("syx").addEventListener("change", (event) => {
  if (event.target.files?.[0]) openFirmware(event.target.files[0]);
});
$("buildBtn").addEventListener("click", buildImage);
$("equalSlots").addEventListener("change", (event) => {
  if (state.firmware) setLayout(event.target.checked);
});
$("resetBtn").addEventListener("click", () => location.reload());

// Repaint on a theme change: the waveforms take their colours from the CSS
// tokens, and a canvas does not restyle itself.
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (state?.factory.length) for (let s = 0; s < COUNT; s++) paint(s);
});
