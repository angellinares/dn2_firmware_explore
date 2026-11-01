/**
 * The Boot Screen page: a picture becomes the 128 x 64 one-bit mark, and the
 * user's choices become the `bootscreen` mod's options. Loading, verifying,
 * building and the download live in `shell.js`; the bytes in `mods/bootscreen.js`.
 */

import { $, buildAndOffer, openFirmware, status, wireDrop } from "./shell.js";
import { replacement } from "../firmware.js";
import { STOCK_TUNNEL, W, apply, asciiFrames, invert, markFromPixels, spinFrames } from "../mods/bootscreen.js";
import { GLYPHS } from "../asciiglitch.js";
import { chimera, drawFrame, loadPicture } from "./boot-picture.js";

const state = { firmware: null, filename: "firmware.syx", luma: null, mark: null, ascii: null, lit: null };
const INTRO_FRAMES = 175;   // measured on 1.11: the intro routine's second argument

const flashing = () => $("modeFlash").checked;
const ascii = () => $("modeAscii").checked;
const spin = () => $("modeSpin").checked;
/** Either animation drawn ahead of time: frames, played by the same firmware code. */
const animated = () => ascii() || spin();

function options() {
  const m = Number($("tunnel").value);
  const opts = {
    slow: Number($("slow").value), fast: Number($("fast").value),
    rush: Number($("rush").value), stop: Number($("stop").value),
    tunnel: [STOCK_TUNNEL[0] * m, STOCK_TUNNEL[1] * m],
  };
  if (animated()) opts.ascii = state.ascii;
  return opts;
}

function images() {
  if (animated()) return [];
  return flashing() ? [state.mark, invert(state.mark)] : [state.mark];
}

function asciiOptions() {
  return {
    ramp: $("ramp").value, glitchChars: $("glitchChars").value,
    resolve: Number($("resolve").value), idleFrames: 16, seed: Number($("seed").value),
    glitch: Number($("glitch").value), idle: Number($("idle").value),
  };
}

/** One sentence per option, so the numbers read as what the intro will do. */
function describe() {
  if (animated()) {
    $("buildBtn").disabled = !state.firmware || !state.ascii;
    if (!state.ascii) return "Fix the options above to build.";
    const [frames, loop] = state.ascii;
    return (ascii() ? `Resolves over ${loop} frames, then loops ${frames.length - loop} frames of residual glitch`
                    : `Settles after ${loop} frames, then the swirl turns once every ${frames.length - loop} frames`)
         + ` for the rest of the intro. Adds ${frames.length} KB of frames.`;
  }
  const { slow, fast, rush, stop } = options();
  const valid = Number.isInteger(rush) && Number.isInteger(stop) && rush >= 0 && rush <= stop;
  $("buildBtn").disabled = !valid || !state.firmware;
  if (!flashing()) return "The mark is held for the whole intro.";
  if (!valid) return "Speed-up must not come after the hold. Fix the frame numbers to build.";
  return `Swaps every ${2 ** slow} frames, every ${2 ** fast} from frame ${rush}, `
       + `and holds the mark from frame ${stop}.`;
}

function rebuildSpin() {
  for (const id of ["turns", "zoom", "smear"]) $(`${id}Val`).textContent = `(${Number($(id).value).toFixed(2)})`;
  try {
    state.ascii = spinFrames(state.lit, {
      resolve: Number($("spinResolve").value), idleFrames: 48, stars: Number($("stars").value),
      smear: Number($("smear").value), spin: Number($("turns").value), zoom: Number($("zoom").value),
      seed: Number($("spinSeed").value),
    });
    $("spinErr").textContent = "";
  } catch (error) {
    state.ascii = null;
    $("spinErr").textContent = String(error.message ?? error);
  }
}

function rebuildAscii() {
  $("glitchVal").textContent = `(${Number($("glitch").value).toFixed(2)})`;
  $("idleVal").textContent = `(${Number($("idle").value).toFixed(2)})`;
  try {
    state.ascii = asciiFrames(state.lit, asciiOptions());
    $("asciiErr").textContent = "";
  } catch (error) {
    state.ascii = null;
    $("asciiErr").textContent = String(error.message ?? error);
  }
}

/** Play the frames as the intro will: 0..last, then loop, restarting after the intro. */
let tick = 0;
function play() {
  if (animated() && state.ascii) {
    const [frames, loop] = state.ascii;
    const f = tick % INTRO_FRAMES;
    const k = f < frames.length ? f : loop + ((f - frames.length) % (frames.length - loop || 1));
    drawFrame($("frameB"), frames[Math.min(k, frames.length - 1)], true);
    tick += 1;
  }
  setTimeout(() => requestAnimationFrame(play), 1000 / 30);
}

function render() {
  if (!state.luma) return;
  const threshold = Number($("threshold").value);
  const flip = $("invertMark").value === "yes";
  $("thresholdVal").textContent = `(${threshold})`;
  state.lit = (x, y) => (state.luma[y * W + x] >= threshold) !== flip;
  state.mark = markFromPixels(state.lit);
  drawFrame($("frameA"), state.mark, true);
  if (ascii()) rebuildAscii();
  else if (spin()) rebuildSpin();
  else drawFrame($("frameB"), invert(state.mark), true);
  $("screenB").classList.toggle("hidden", !flashing() && !animated());
  $("capB").textContent = animated() ? "As it plays (about 30 frames a second)" : "Alternates with";
  $("timing").classList.toggle("hidden", !flashing());
  $("asciiControls").classList.toggle("hidden", !ascii());
  $("spinControls").classList.toggle("hidden", !spin());
  $("tunnelStep").classList.toggle("hidden", animated());
  $("timeline").textContent = describe();
}

async function usePreset() {
  state.luma = await chimera();
  render();
}

async function ready(firmware) {
  // A dry run is the check that this image takes the mod: it throws, naming
  // why, before anything is offered.
  apply(firmware, images(), options());
  state.firmware = firmware;
  for (const id of ["step3", "bar"]) $(id).classList.remove("hidden");
  $("timeline").textContent = describe();
  status("Loaded. Ready to build.");
}

async function buildImage() {
  const { content, notes } = apply(state.firmware, images(), options());
  await buildAndOffer(
    state.firmware,
    new Map([[3, replacement(state.firmware, 3, content, "bootscreen")]]),
    { filename: state.filename, mod: "bootscreen", suffix: ascii() ? "bootscreen-ascii" : spin() ? "bootscreen-spin" : "bootscreen", note: notes[0] });
}

function open(file) {
  state.filename = file.name;
  return openFirmware(file, { onReady: ready });
}

for (const [id, pick] of [["slow", 4], ["fast", 3]]) {
  const sel = $(id);
  for (let s = 0; s <= 8; s++) {
    const o = document.createElement("option");
    o.value = String(s);
    o.textContent = `${2 ** s} frame${s ? "s" : ""}`;
    if (s === pick) o.selected = true;
    sel.append(o);
  }
}

$("srcPreset").addEventListener("change", usePreset);
$("srcFile").addEventListener("change", () => $("picture").click());
$("picture").addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    state.luma = await loadPicture(file);
    $("capA").textContent = `The mark — ${file.name}`;
    render();
  } catch (error) {
    status(`Could not read ${file.name}: ${error.message ?? error}`);
  }
});
for (const id of ["threshold", "invertMark", "slow", "fast", "rush", "stop", "tunnel", "modeStatic", "modeFlash",
                  "modeAscii", "ramp", "glitchChars", "glitch", "idle", "resolve", "seed",
                  "modeSpin", "turns", "zoom", "smear", "stars", "spinResolve", "spinSeed"]) {
  $(id).addEventListener("input", render);
}
wireDrop($("drop"), open);
$("syx").addEventListener("change", (e) => {
  if (e.target.files?.[0]) open(e.target.files[0]);
});
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());

$("glyphList").textContent = GLYPHS;
usePreset();
play();
