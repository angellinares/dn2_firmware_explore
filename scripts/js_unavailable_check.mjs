// A withdrawn mod (site/js/mods/availability.js) under node: LFO4 is not read or built and
// its page shows the notice where the file chooser was; a mod that is not withdrawn builds
// as before; with the entry removed LFO4 is on offer again. Run by test/test_js_unavailable.py.
import { flagFor } from "../site/js/mods/availability.js";
import { markCard, withdrawPage } from "../site/js/app/unavailable.js";

const TITLE = "LFO4 is unavailable for now";
const BODY = "We are looking into a report of song data being damaged in projects used with LFO4. "
  + "The download is off until that is resolved. If you have LFO4 installed, back up your "
  + "projects and work in copies.";

function element(tag) {
  const el = { tag, children: [], className: "", textContent: "", style: {}, hidden: false,
    append(...kids) { this.children.push(...kids); },
    after(node) { this.sibling = node; },
    replaceWith(node) { this.replacedBy = node; },
    remove() { this.removed = true; },
    querySelector(sel) { return sel === ".tag" ? this.tagEl : sel === "p" ? this.firstP : null; },
  };
  return el;
}
const elements = { drop: element("div"), bar: element("div"), status: element("span") };
elements.status.classList = { toggle() {} };
for (const id of ["loaded", "facts", "verdict"]) {
  elements[id] = element("div");
  elements[id].classList = { remove() {} };
}
globalThis.document = { createElement: element, getElementById: (id) => elements[id] ?? null };
globalThis.requestAnimationFrame = (fn) => fn();
globalThis.URL.createObjectURL = () => "blob:test";

const { buildAndOffer, openFirmware } = await import("../site/js/app/shell.js");
const text = (el) => el.textContent + el.children.map((c) => text(c)).join("");
const ok = (name, pass) => { console.log(`${pass ? "OK  " : "FAIL"} ${name}`); if (!pass) process.exitCode = 1; };

const flag = flagFor("lfo4");
ok("LFO4 carries an entry with the date it was withdrawn", flag?.since === "2026-10-10");
ok("the notice has the agreed title and body", flag.title === TITLE && flag.reason === BODY);

// (a) cannot be selected or downloaded
let read = 0;
const file = { name: "dn2.syx", arrayBuffer: async () => { read++; return new ArrayBuffer(0); } };
const opened = await openFirmware(file, { onReady: async () => {}, unavailable: flag });
ok("a firmware file is not read for LFO4", opened === null && read === 0);
const built = await buildAndOffer({}, new Map(), { filename: "dn2.syx", suffix: "lfo4",
  into: element("div"), button: null, unavailable: flag });
ok("LFO4 builds nothing and offers no download", built === null);

// (b) the notice is shown in place of the file chooser
withdrawPage(flag, document);
const shown = elements.drop.replacedBy;
ok("the notice replaces the file chooser", shown && text(shown).includes(TITLE) && text(shown).includes(BODY));
ok("the build bar is removed", elements.bar.removed === true);
const card = element("article");
card.tagEl = element("span"); card.firstP = element("p");
markCard(card, flag, document);
ok("the mod list marks the card and adds the notice",
   card.tagEl.textContent === "Unavailable for now" && text(card.firstP.sibling).includes(BODY));

// (c) a mod that is not withdrawn still builds
ok("another mod has no entry", flagFor("lfolength") === null && flagFor("moddest") === null);
await openFirmware(file, { onReady: async () => {}, unavailable: flagFor("lfolength") });
ok("a firmware file is read as before for a mod that is on offer", read === 1);
const into = element("div");
await buildAndOffer({}, new Map(), { filename: "dn2.syx", suffix: "x", into, button: null,
  unavailable: flagFor("lfolength") });
ok("a build for a mod that is on offer goes ahead (a stub image fails its own checks)",
   into.children.length > 0);

// fxmod is withdrawn the same way, with its own notice
const fx = flagFor("fxmod");
ok("fxmod carries an entry with its title and the date", fx?.since === "2026-10-10"
   && fx.title === "LFO modulation of the FX is unavailable for now" && fx.reason.includes("back up your projects"));
read = 0;
ok("a firmware file is not read for fxmod",
   await openFirmware(file, { onReady: async () => {}, unavailable: fx }) === null && read === 0);
ok("fxmod builds nothing and offers no download", await buildAndOffer({}, new Map(),
   { filename: "dn2.syx", suffix: "fxmod", into: element("div"), button: null, unavailable: fx }) === null);
ok("with its entry removed fxmod is on offer", flagFor("fxmod", {}) === null);

// (d) removing the entry restores LFO4
ok("with the entry removed LFO4 is on offer", flagFor("lfo4", {}) === null);
