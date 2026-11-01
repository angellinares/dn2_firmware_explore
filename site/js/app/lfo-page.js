/**
 * The LFO Waves page: what is specific to this mod, and nothing else.
 *
 * Loading and verifying the firmware, building, re-verifying and offering the
 * download live in `shell.js`. This file shows the seven waves and lets the user
 * keep or replace each of the three wavetables, previewing a table exactly the way
 * the firmware reads it (`wavetable.sample`, the generator's bilinear arithmetic).
 */

import { $, buildAndOffer, openFirmware, status, wireDrop } from "./shell.js";
import { replacement } from "../firmware.js";
import { toBytes } from "../wavetable.js";
import { LABELS, WAVES, apply } from "../mods/lfowaves.js";
import { freshSlots, tableCards } from "./lfo-tables.js";

const ABOUT = {
  STEP: "a staircase; STPS sets the number of steps",
  PULS: "a pulse; WDTH sets its width",
  NOIS: "noise; TYPE sets colour.loop (1.01 – 4.--)",
  TRAP: "a trapezoid; SLOP sets the edges, square to triangle",
  WTB1: "wavetable: basic shapes, sine to thin pulse",
  WTB2: "wavetable: harmonic sweep, one to fifteen harmonics",
  WTB3: "wavetable: vowels, A E I O U and back",
};
const state = {
  firmware: null,
  filename: "firmware.syx",
  slots: freshSlots(),
};

function drawWaves() {
  const host = $("waves");
  host.innerHTML = "";
  WAVES.forEach((name, k) => {
    const el = document.createElement("div");
    el.className = "wave";
    el.innerHTML = "<b></b><span></span><small></small>";
    el.querySelector("b").textContent = name;
    el.querySelector("span").textContent = LABELS[k];
    el.querySelector("small").textContent = ABOUT[name] ?? "";
    host.append(el);
  });
}

const drawTables = () => tableCards($("tables"), state.slots);

async function ready(firmware) {
  state.firmware = firmware;
  apply(firmware);                       // refuses a non-stock or already-modded image, before any choice
  for (const id of ["step2", "step3", "step4", "bar"]) $(id).classList.remove("hidden");
  drawTables();
  status("Loaded. Keep our wavetables or replace any of them, then build.");
}

async function buildImage() {
  const tables = state.slots.map((s) => (s.custom ? toBytes(s.table) : null));
  const { content, notes } = apply(state.firmware, tables);
  await buildAndOffer(state.firmware, new Map([[3, replacement(state.firmware, 3, content, "lfowaves")]]),
    { filename: state.filename, mod: "lfowaves", suffix: "lfowaves", note: notes[1] });
}

function open(file) {
  state.filename = file.name;
  return openFirmware(file, {
    onReady: ready,
    extraFacts: () => [["Adds", `${WAVES.length} LFO waveforms: ${WAVES.join(" ")}`]],
  });
}

drawWaves();
wireDrop($("drop"), open);
$("syx").addEventListener("change", (e) => { if (e.target.files?.[0]) open(e.target.files[0]); });
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => state.firmware && drawTables());
