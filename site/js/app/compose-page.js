/**
 * The Mod Composer page: a checklist of mods, the options of the three that take the user's own
 * files, and one build.
 *
 * The decisions live in `mods/compose.js` (order, conflicts, the build, the command), which
 * test/test_js_build_matches_cli.py checks against the CLI. Loading, verifying and offering the
 * file live in `shell.js`. A slot, a wavetable and a boot picture are drawn by the same modules as
 * their own pages (transient-view.js, lfo-tables.js, boot-picture.js). Which mods combine is read
 * from this page's compatibility table, which `dnfw mods matrix --page` writes.
 */

import { $, offer, openFirmware, outputName, showChecks, status, wireDrop } from "./shell.js";
import { GROUPS, MAX_WITH_RECORD, TAKES_FILES, blocked, build, command, order } from "../mods/compose.js";
import { VERSIONS } from "../mods/versions.js";
import { flagFor } from "../mods/availability.js";
import { COUNT, EQUAL_SAMPLES, extract, fit as fitEntry, lengths, toEntry, toFloat } from "../mods/transients.js";
import { TABLES } from "../mods/lfowaves.js";
import { W, markFromPixels } from "../mods/bootscreen.js";
import { fit } from "../audio.js";
import { toBytes } from "../wavetable.js";
import { fitText, ms, paint, play, readSample, tuning } from "./transient-view.js";
import { freshSlots, tableCards } from "./lfo-tables.js";
import { CHIMERA, chimera, drawFrame, loadPicture, savePgm } from "./boot-picture.js";

/** id -> [name, what it does, its page]. */
const MODS = {
  waverider: ["Waverider, a sixth machine", "A wavetable synth machine with two oscillators, a sub-oscillator and noise.", "waverider.html"],
  transients: ["FM drum transients", "Your own samples in the 32 FM DRUM transient slots.", "transients.html"],
  lfo4: ["A fourth LFO", "A fourth LFO on every track, on the empty fourth page under [MOD].", "lfo4.html"],
  fxmod: ["LFO modulation of the FX", "An LFO can modulate 24 Chorus, Delay and Reverb parameters.", "fx.html"],
  lfowaves: ["New LFO waveforms", "Seven waves after RAND: STEP, PULS, NOIS, TRAP and the wavetables WTB1, WTB2 and WTB3.", "lfo.html"],
  moddest: ["More modulation destinations", "13 more per-voice parameters open as LFO destinations.", "destinations.html"],
  lfolength: ["LFO ONE/HALF fix", "TRIG MODE ONE and HALF run one cycle or half a cycle, then hold the value.", "lfo-fix.html"],
  midiarp: ["Arpeggiator on MIDI tracks", "The arpeggiator plays on MIDI tracks.", "arp.html"],
  layermidi: ["Layering onto MIDI tracks", "TRACK WILL TRIGGER onto a MIDI track plays it over MIDI.", "layer-midi.html"],
  arpmodes: ["Arpeggiator SHUF and RAND", "SHUF and RAND as real arpeggiator modes.", "arp-modes.html"],
  arpscale: ["Arp offsets in scale", "The step offsets of the arpeggiator move by degrees of the scale.", "arp-scale.html"],
  reloadconfirm: ["Reload confirm", "FUNC + NO can ask before it reloads the pattern.", "reload-confirm.html"],
  bootscreen: ["Boot screen", "Your own mark in the start-up animation.", "boot.html"],
};
/** The suffix each mod's own page gives its file. */
const SUFFIX = { moddest: "destinations", lfolength: "lfofix" };
const BOOT_MODES = { still: "tunnel, still mark", flash: "tunnel, flashing mark", ascii: "ASCII glitch", spin: "spin (1966)" };
const STOCK_SIZES = lengths(false);
const pad = (n) => String(n).padStart(2, "0");
const nameOf = (id) => MODS[id][0];

const state = {
  firmware: null,
  filename: "Digitone_II_OS1.11.syx",
  on: new Set(),
  nameEdited: false,
  tr: { equal: false, raw: null, factory: [], replacements: new Map(), sel: 0 },
  lfo: freshSlots(),
  boot: { chimera: null, own: null, useOwn: false, mode: "flash" },
};

// ---------------------------------------------------------------- the compatibility table

/** The pairs this page's table marks as not combining, as [a, b]. */
function refusedPairs() {
  const table = document.querySelector("#compatibility table.matrix");
  if (!table) return [];
  const cols = [...table.querySelectorAll("thead code")].map((c) => c.textContent);
  const out = [];
  for (const row of table.querySelectorAll("tbody tr")) {
    const id = row.querySelector("th code")?.textContent;
    row.querySelectorAll("td").forEach((td, k) => { if (td.classList.contains("mx-no")) out.push([id, cols[k]]); });
  }
  return out;
}
const REFUSED = refusedPairs();

// ---------------------------------------------------------------- the list

function drawList() {
  const host = $("mods");
  for (const group of GROUPS) {
    const head = document.createElement("div");
    head.className = "group-name";
    head.textContent = group.name;
    host.append(head);
    for (const id of group.mods) {
      const [name, blurb, page] = MODS[id];
      const row = document.createElement("div");
      row.className = "mod-row";
      row.dataset.mod = id;
      row.innerHTML = `
        <input type="checkbox">
        <span class="glyph" aria-hidden="true"></span>
        <div class="what"><label><span class="nm"></span><span class="id"></span></label>
          <div class="blurb"></div><div class="why hidden"></div></div>
        <div class="side"><span class="pill hidden"></span><a class="manual">Manual</a></div>`;
      const box = row.querySelector("input");
      box.id = `m-${id}`;
      row.querySelector("label").htmlFor = box.id;
      row.querySelector(".glyph").dataset.glyph = id;
      row.querySelector(".nm").textContent = name;
      row.querySelector(".id").textContent = `${id} ${VERSIONS[id] ?? ""}`.trim();
      row.querySelector(".blurb").textContent = blurb;
      const manual = row.querySelector(".manual");
      manual.href = page;
      manual.setAttribute("aria-label", `${name}: its page`);
      box.addEventListener("change", () => toggle(id, box.checked));
      host.append(row);
      const panel = $(`panel-${id}`);
      if (panel) { panel.classList.add("hidden"); host.append(panel); }
    }
  }
}

function toggle(id, on) {
  if (on) state.on.add(id); else state.on.delete(id);
  if (on && id === "lfowaves") drawTables();        // drawn while visible, so the canvases have a width
  if (on && id === "transients") requestAnimationFrame(drawEditor);
  changed();
}

/** The rows: ticked, blocked and why, the pill of a mod with files, its panel. */
function drawRows() {
  const stop = blocked([...state.on], REFUSED);
  for (const row of document.querySelectorAll(".mod-row")) {
    const id = row.dataset.mod;
    const box = row.querySelector("input");
    const why = row.querySelector(".why");
    const flag = flagFor(id);
    const hit = stop.get(id);
    box.checked = state.on.has(id);
    box.disabled = Boolean(flag) || Boolean(hit);
    row.classList.toggle("blocked", box.disabled);
    why.textContent = flag ? flag.title
      : hit?.with.length ? `Does not combine with ${hit.with.map(nameOf).join(" or ")}.`
      : hit?.full ? `A build with Waverider holds at most ${MAX_WITH_RECORD} mods.` : "";
    why.classList.toggle("hidden", !why.textContent);
    const pill = row.querySelector(".pill");
    const tag = TAKES_FILES.includes(id) && state.on.has(id) ? pillFor(id) : null;
    pill.classList.toggle("hidden", !tag);
    if (tag) { pill.textContent = tag.text; pill.classList.toggle("needs", Boolean(tag.needs)); }
    $(`panel-${id}`)?.classList.toggle("hidden", !state.on.has(id));
  }
}

function pillFor(id) {
  if (id === "transients") {
    const n = state.tr.replacements.size;
    return n ? { text: `${n} of ${COUNT} yours` } : { text: "Needs audio", needs: true };
  }
  if (id === "lfowaves") {
    const n = state.lfo.filter((s) => s.custom).length;
    return { text: n ? `${n} of 3 yours` : "Ours" };
  }
  return { text: state.boot.useOwn ? "Your picture" : "Ours: the chimera" };
}

// ---------------------------------------------------------------- transients

const tr = state.tr;
const size = (slot) => lengths(tr.equal)[slot];
/** The factory sound's length in samples: from the loaded image, or stock 1.11's. */
const factoryLength = (slot) => (tr.raw ? tr.raw[slot].length / 2 : STOCK_SIZES[slot]);
/** "cut" or "pad" for a factory slot that the layout changes, else "". */
const change = (slot) => (tr.replacements.has(slot) ? ""
  : factoryLength(slot) > size(slot) ? "cut" : factoryLength(slot) < size(slot) ? "pad" : "");

function refreshFactory() {
  tr.factory = tr.raw ? tr.raw.map((pcm, slot) => toFloat(fitEntry(pcm, size(slot)))) : [];
}

const fitFor = (slot, entry) => fit(entry.source, { ...entry.options, length: size(slot) });

function drawStrip() {
  const host = $("strip");
  for (let slot = 0; slot < COUNT; slot++) {
    const b = document.createElement("button");
    b.type = "button";
    b.innerHTML = '<span class="n"></span><span class="tran"></span><span class="lenbar"><i></i></span><span class="len"></span><span class="mark"></span>';
    b.querySelector(".n").textContent = pad(slot);
    b.querySelector(".tran").textContent = String(4 * slot);
    b.addEventListener("click", () => { tr.sel = slot; drawTransients(); });
    wireDrop(b, (file) => { tr.sel = slot; loadSample(file); });
    host.append(b);
  }
}

function drawTransients() {
  const n = tr.replacements.size;
  $("trHead").textContent = `Your transients: ${n} of ${COUNT} slots replaced`;
  $("trClear").disabled = !n;
  [...$("strip").children].forEach((b, slot) => {
    const yours = tr.replacements.get(slot);
    const ch = change(slot);
    const len = size(slot);
    b.className = yours ? "yours" : ch ? "changed" : "";
    b.setAttribute("aria-pressed", String(slot === tr.sel));
    b.querySelector(".lenbar i").style.width = `${Math.round((100 * len) / 7200)}%`;
    b.querySelector(".len").textContent = (1000 * len / 48000).toFixed(1).replace(/\.0$/, "");
    b.querySelector(".mark").textContent = ch;
    b.setAttribute("aria-label", `Slot ${pad(slot)}, TRAN ${4 * slot}, ${ms(len)}, `
      + (yours ? yours.name : `factory${ch ? ` ${ms(factoryLength(slot))}, ${ch === "cut" ? "cut" : "padded"}` : ""}`));
  });
  drawEditor();
}

function drawEditor() {
  const slot = tr.sel, entry = tr.replacements.get(slot) ?? null, len = size(slot);
  $("selHead").textContent = `${pad(slot)} · TRAN ${4 * slot} · ${ms(len)}`;
  $("selName").textContent = entry ? entry.name : "factory";
  paint($("selWave"), { factory: tr.factory[slot], entry, size: len });
  const line = fitText(entry, factoryLength(slot), len);
  $("selFit").textContent = line.text;
  $("selFit").title = line.title;
  $("selFit").classList.toggle("cut", line.cut);
  $("selNote").textContent = entry
    ? (entry.fitted.truncated ? `The shaded part is the ${ms(len)} that the slot keeps. The page drops the rest of your file.`
      : "Your file is shorter than the slot. The rest of the slot is silence.")
    : `${state.firmware ? "Factory sound." : "Load your firmware to hear the factory sound."} `
      + "Drop audio here to replace it, or choose a file.";
  const tune = $("selTune");
  if (entry) tuning(tune, entry, { refit: () => { entry.fitted = fitFor(slot, entry); }, repaint: () => drawEditor() });
  else tune.innerHTML = "";
  $("selRevert").disabled = !entry;
  $("selPlay").disabled = !entry && !tr.factory[slot];
  $("selFileLabel").textContent = entry ? "Replace" : "Choose a file";
  $("selNext").textContent = tr.equal ? `Equal slots: the page fits your sample to ${ms(EQUAL_SAMPLES)}.`
    : `Factory sizes: the page fits your sample to the ${ms(len)} of this slot. Choose a longer slot for a longer sample.`;
}

async function loadSample(file) {
  const slot = tr.sel;
  status(`Decoding ${file.name}…`, true);
  let note = "";
  try {
    const entry = await readSample(file);
    entry.fitted = fitFor(slot, entry);
    tr.replacements.set(slot, entry);
    play(entry.fitted.samples);
    if (entry.fitted.truncated) note = `${file.name} is cut to the ${ms(size(slot))} that slot ${pad(slot)} holds.`;
  } catch (error) {
    note = `${file.name}: ${error.message ?? error}`;
  }
  status("");
  changed();
  status(note);
}

function setEqual(equal) {
  tr.equal = equal;
  refreshFactory();
  for (const [slot, entry] of tr.replacements) entry.fitted = fitFor(slot, entry);
  changed();
}

/** The replacements as the mod takes them: slot -> exactly that slot's samples. */
function entries() {
  const out = new Map();
  for (const [slot, entry] of tr.replacements) out.set(slot, toEntry(entry.fitted.samples, size(slot)));
  return out;
}

// ---------------------------------------------------------------- LFO waves

const drawTables = () => tableCards($("tables"), state.lfo, { onChange: changed, idPrefix: "c-" });

// ---------------------------------------------------------------- boot screen

const boot = state.boot;
const luma = () => (boot.useOwn ? boot.own?.luma : boot.chimera) ?? null;
const lit = (l) => (x, y) => l[y * W + x] >= 128;
const pgmName = () => `${boot.own.name.replace(/\.[^.]*$/, "")}.pgm`;

function drawBoot() {
  const l = luma();
  if (l) drawFrame($("bootFrame"), markFromPixels(lit(l)), true);
  $("bootChimera").checked = !boot.useOwn;
  $("bootOwn").checked = boot.useOwn;
  $("bootSaveRow").classList.toggle("hidden", !boot.useOwn);
  $("bootNote").textContent = (boot.useOwn ? `The build uses ${boot.own.name}.` : "The build uses the chimera.")
    + " Any picture works: the page fits it to 128 × 64 and cuts it to black and white at threshold 128.";
}

// ---------------------------------------------------------------- the build panel

/** What the build takes from the user's files, for compose.js. */
function choice(forBuild = false) {
  const c = {};
  if (state.on.has("transients")) {
    c.transients = { entries: forBuild ? entries() : new Map(), equal: tr.equal, folder: "my-transients/" };
  }
  if (state.on.has("lfowaves")) {
    c.lfowaves = { tables: state.lfo.map((s) => (s.custom ? toBytes(s.table) : null)), files: state.lfo.map((s) => s.custom) };
  }
  if (state.on.has("bootscreen") && luma()) {
    c.bootscreen = { lit: lit(luma()), mode: boot.mode, image: boot.useOwn ? pgmName() : `site/${CHIMERA}` };
  }
  return c;
}

function detail(id) {
  if (id === "transients") {
    const keys = [...tr.replacements.keys()].sort((a, b) => a - b);
    const left = Array.from({ length: COUNT }, (_, k) => k).filter((k) => !tr.replacements.has(k));
    const layout = tr.equal
      ? `Equal slots of ${ms(EQUAL_SAMPLES)}: ${left.filter((k) => change(k) === "cut").length} factory cut, `
        + `${left.filter((k) => change(k) === "pad").length} padded.`
      : "Factory slot sizes.";
    return keys.length ? { text: `${keys.length} of ${COUNT} slots replaced: ${keys.map(pad).join(", ")}. ${layout}` }
      : { text: `No slots replaced yet. ${layout}`, needs: true };
  }
  if (id === "lfowaves") {
    const yours = TABLES.filter((t, k) => state.lfo[k].custom).map((t) => t.name);
    const ours = TABLES.filter((t, k) => !state.lfo[k].custom).map((t) => t.name);
    return { text: !yours.length ? "All three tables are ours."
      : `Yours: ${yours.join(", ")}.${ours.length ? ` Ours: ${ours.join(", ")}.` : ""}` };
  }
  if (id === "bootscreen") {
    return { text: `${boot.useOwn ? boot.own.name : "The chimera"}, ${BOOT_MODES[boot.mode]}.` };
  }
  return null;
}

function waitReason(ids) {
  if (!state.firmware) return "Load your firmware to build.";
  if (!ids.length) return "Tick at least one mod.";
  if (state.on.has("transients") && !tr.replacements.size) {
    return "FM drum transients has no audio yet, so it changes nothing. Drop a sample on a slot, or untick the mod.";
  }
  if (state.on.has("bootscreen") && !luma()) return "The boot picture is still loading.";
  return "";
}

function defaultName(ids) {
  const suffix = (id) => (id === "bootscreen" && boot.mode in { ascii: 1, spin: 1 } ? `bootscreen-${boot.mode}` : SUFFIX[id] ?? id);
  return ids.reduce((name, id) => outputName(name, suffix(id), id), state.filename);
}

const quote = (a) => (/^[\w./=:-]+$/.test(a) ? a : `'${a.replace(/'/g, "'\\''")}'`);

function drawBuild() {
  const ids = order([...state.on]);
  $("count").textContent = ids.length ? `${ids.length} mod${ids.length === 1 ? "" : "s"}, applied in this order` : "No mods ticked.";
  const list = $("chosen");
  list.innerHTML = "";
  ids.forEach((id, k) => {
    const li = document.createElement("li");
    li.innerHTML = '<span class="n"></span><div class="what"><span class="nm"></span><span class="detail"></span></div>';
    li.querySelector(".n").textContent = String(k + 1);
    li.querySelector(".nm").textContent = nameOf(id);
    const d = detail(id);
    const el = li.querySelector(".detail");
    if (d) { el.textContent = d.text; el.classList.toggle("needs", Boolean(d.needs)); } else el.remove();
    list.append(li);
  });
  $("lastNote").classList.toggle("hidden", !(state.on.has("lfo4") && ids.length > 1));
  $("okLine").classList.toggle("hidden", ids.length < 2);
  const wait = waitReason(ids);
  $("waitLine").textContent = wait;
  $("buildBtn").disabled = Boolean(wait);
  if (!state.nameEdited) $("outName").value = ids.length ? defaultName(ids) : "modded.syx";

  const lines = command(ids, choice(), { stock: state.filename, out: $("outName").value });
  $("cmd").textContent = ids.length
    ? "dnfw mods apply " + lines.map((l) => l.map(quote).join(" ")).join(" \\\n  ")
    : "Tick a mod to see the command.";
  $("cmdTransients").classList.toggle("hidden", !state.on.has("transients"));
  $("cmdBoot").classList.toggle("hidden", !(state.on.has("bootscreen") && boot.useOwn));
}

function drawFiles() {
  const rows = [];
  for (const slot of [...tr.replacements.keys()].sort((a, b) => a - b)) {
    rows.push([tr.replacements.get(slot).name, `transients, slot ${pad(slot)}`, "transients"]);
  }
  state.lfo.forEach((s, k) => { if (s.custom) rows.push([s.custom, `lfowaves, ${TABLES[k].name}`, "lfowaves"]); });
  if (boot.own) rows.push([boot.own.name, "bootscreen", "bootscreen"]);
  const host = $("files");
  host.innerHTML = "";
  if (!rows.length) rows.push(["None yet.", "", null]);
  for (const [name, where, id] of rows) {
    const li = document.createElement("li");
    li.innerHTML = '<span class="fname"></span><span class="where"></span>';
    li.querySelector(".fname").textContent = name;
    li.querySelector(".fname").title = name;
    const w = li.querySelector(".where");
    const off = id && (!state.on.has(id) || (id === "bootscreen" && !boot.useOwn));
    w.textContent = off ? `${where}, not in the build` : where;
    w.classList.toggle("off", Boolean(off));
    host.append(li);
  }
}

/** After any choice: the old download no longer matches, and everything redraws. */
function changed() {
  $("buildVerdict").innerHTML = "";
  if (!$("status").classList.contains("busy")) status("");
  const mine = state.lfo.filter((t) => t.custom).length;
  $("lfoHead").textContent = `Your wavetables: ${mine ? `${mine} of 3 yours` : "all 3 ours"}`;
  drawRows();
  drawTransients();
  drawBoot();
  drawBuild();
  drawFiles();
}

async function buildIt() {
  const ids = order([...state.on]);
  $("buildBtn").disabled = true;
  status("Building…", true);
  // One frame, so the status paints before the packing and the HMAC take the main thread.
  await new Promise((r) => requestAnimationFrame(r));
  try {
    const bytes = await build(state.firmware, ids, choice(true));
    let name = $("outName").value.trim() || "modded.syx";
    if (!/\.syx$/i.test(name)) name += ".syx";
    await offer(bytes, { name, note: `${ids.length} mod${ids.length === 1 ? "" : "s"}` });
  } catch (error) {
    showChecks($("buildVerdict"), [{ name: "build failed", ok: false, detail: String(error.message ?? error) }]);
    status("");
  } finally {
    $("buildBtn").disabled = Boolean(waitReason(ids));
  }
}

// ---------------------------------------------------------------- wiring

function open(file) {
  return openFirmware(file, {
    onReady: (firmware) => {
      state.firmware = firmware;
      state.filename = file.name;
      try { tr.raw = extract(firmware); } catch { tr.raw = null; }
      refreshFactory();
      changed();
      status("Loaded. Tick the mods that you want, then build.");
    },
  });
}

drawList();
drawStrip();
drawTables();
wireDrop($("drop"), open);
$("syx").addEventListener("change", (e) => { if (e.target.files?.[0]) open(e.target.files[0]); });
$("buildBtn").addEventListener("click", buildIt);
$("outName").addEventListener("input", () => { state.nameEdited = Boolean($("outName").value.trim()); drawBuild(); });
$("copyBtn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("cmd").textContent);
    $("copyBtn").textContent = "Copied";
  } catch {
    $("copyBtn").textContent = "Select and copy";
  }
  setTimeout(() => { $("copyBtn").textContent = "Copy"; }, 1500);
});

$("equalSlots").addEventListener("change", (e) => setEqual(e.target.checked));
$("trClear").addEventListener("click", () => { tr.replacements.clear(); changed(); });
$("selRevert").addEventListener("click", () => { tr.replacements.delete(tr.sel); changed(); });
$("selPlay").addEventListener("click", () => play(tr.replacements.get(tr.sel)?.fitted.samples ?? tr.factory[tr.sel]));
$("selWave").addEventListener("click", () => play(tr.replacements.get(tr.sel)?.fitted.samples ?? tr.factory[tr.sel]));
$("selFile").addEventListener("change", (e) => { if (e.target.files?.[0]) loadSample(e.target.files[0]); e.target.value = ""; });
wireDrop($("editor"), loadSample);

$("bootMode").addEventListener("change", (e) => { boot.mode = e.target.value; changed(); });
$("bootChimera").addEventListener("change", () => { boot.useOwn = false; changed(); });
$("bootOwn").addEventListener("change", () => {
  if (boot.own) { boot.useOwn = true; changed(); } else $("bootFile").click();
});
$("bootFile").addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  e.target.value = "";
  if (!file) { changed(); return; }
  let note = "";
  try {
    boot.own = { name: file.name, luma: await loadPicture(file) };
    boot.useOwn = true;
  } catch (error) {
    note = `Could not read ${file.name}: ${error.message ?? error}`;
  }
  changed();
  status(note);
});
$("bootSave").addEventListener("click", () => savePgm(lit(boot.own.luma), pgmName()));

changed();
chimera().then((l) => { boot.chimera = l; changed(); }, () => status("The chimera picture did not load."));
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { drawTables(); drawEditor(); });
