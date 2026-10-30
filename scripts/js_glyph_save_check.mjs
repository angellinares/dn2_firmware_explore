// The glyph editor's and animator's files out (site/js/glyph-tools/glyph_tools.js) under node:
// the date and time in download names, the viewer's choice to turn it off, the download link
// (in the document while it is clicked, its URL freed later) and a save through a file handle
// that fails. Run by test/test_glyph_save.py.
import { readFileSync } from "node:fs";
import vm from "node:vm";

const ROOT = new URL("../", import.meta.url);
const revoked = [];
const ctx = { Blob, URL: { createObjectURL: (b) => { ctx.lastBlob = b; return "blob:1"; }, revokeObjectURL: (u) => revoked.push(u) } };
vm.runInNewContext(readFileSync(new URL("site/js/glyph-tools/glyph_tools.js", ROOT), "utf8"), ctx);
const T = ctx.GlyphTools;
const ok = (name, pass) => { console.log(`${pass ? "OK  " : "FAIL"} ${name}`); if (!pass) process.exitCode = 1; };

// 1. The name: name_yymmdd-hhmmss.ext, local time, every field 2 digits.
const at = new Date(2026, 9, 30, 14, 15, 2);
ok("the date and time go before the extension, after the name's own parts",
   T.stampName("glyph-anims.js", at) === "glyph-anims_261030-141502.js"
   && T.stampName("reloadconfirm_16x16_6.bin", at) === "reloadconfirm_16x16_6_261030-141502.bin"
   && T.stampName("sinesquare_3x_dark.gif", at) === "sinesquare_3x_dark_261030-141502.gif");
ok("month, day, hour, minute and second 1 to 9 get a leading zero, and so does the year",
   T.stampName("a.json", new Date(2009, 0, 2, 3, 4, 5)) === "a_090102-030405.json"
   && T.stampName("a.json", new Date(2031, 8, 9, 9, 9, 9)) === "a_310909-090909.json"
   && T.stampName("a.json", new Date(2026, 11, 31, 23, 59, 59)) === "a_261231-235959.json");
ok("a name with no extension gets the stamp at its end", T.stampName("glyphs", at) === "glyphs_261030-141502");
ok("with the option on the download name has the stamp; off, it is the name as it was",
   T.downloadName("glyphs.js", { stamp: true, date: at }) === "glyphs_261030-141502.js"
   && T.downloadName("glyphs.js", { stamp: false, date: at }) === "glyphs.js");

// 2. The viewer's choice: on by default, kept in localStorage, and the page works without it.
const store = (items = {}) => ({ getItem: (k) => items[k] ?? null, setItem: (k, v) => { items[k] = v; }, items });
const mine = { localStorage: store() };
ok("on by default; off and on again are kept", T.stampNames(mine) === true
   && (T.setStampNames(false, mine), T.stampNames(mine) === false && mine.localStorage.items["glyph-tools.stamp-names"] === "off")
   && (T.setStampNames(true, mine), T.stampNames(mine) === true));
const broken = { get localStorage() { throw new Error("blocked"); } };
let threw = false;
try { T.setStampNames(false, broken); } catch { threw = true; }
ok("blocked or missing storage reads as on, and a write to it does not throw",
   T.stampNames(broken) === true && T.stampNames({}) === true && !threw);

// 3. The download link.
function fakeDoc(win) {
  const body = { kids: [], append(a) { this.kids.push(a); a.parent = this; } };
  const doc = {
    body, defaultView: win,
    createElement: () => {
      const a = { style: {}, remove() { body.kids = body.kids.filter((k) => k !== a); a.parent = null; },
        click() { a.inBodyAtClick = body.kids.includes(a); a.clicked = true; } };
      return a;
    },
  };
  return { doc, body };
}
const timers = [];
const win = { localStorage: store(), setTimeout: (fn, ms) => timers.push([fn, ms]) };
const { doc, body } = fakeDoc(win);
const name = T.download(doc, "text", "glyph-anims.js");
ok("the download returns the stamped name, and the blob is octet-stream unless a type is given",
   /^glyph-anims_\d{6}-\d{6}\.js$/.test(name) && ctx.lastBlob.type === "application/octet-stream"
   && (T.download(doc, new Uint8Array(2), "x.gif", "image/gif"), ctx.lastBlob.type === "image/gif"));
T.setStampNames(false, win);
ok("with the option off the download keeps its plain name", T.download(doc, "t", "glyphs.js") === "glyphs.js");
ok("the link is in the document when it is clicked, then removed; its URL is freed later, not at once",
   (() => {
     const made = [];
     const d2 = { ...doc, createElement: () => { const x = doc.createElement(); made.push(x); return x; } };
     T.download(d2, "t", "a.bin");
     const x = made[0];
     return x.clicked && x.inBodyAtClick && !body.kids.includes(x) && revoked.length === 0
       && timers.length > 0 && timers.at(-1)[1] >= 1000 && (timers.at(-1)[0](), revoked.at(-1) === "blob:1");
   })());

// 4. Saving through a file handle: a failure comes back as the error, never as a save.
async function handles() {
  const wrote = [];
  const good = { createWritable: async () => ({ write: async (d) => wrote.push(d), close: async () => wrote.push("closed") }) };
  const lost = { createWritable: async () => { throw Object.assign(new Error("The request is not allowed"), { name: "NotAllowedError" }); } };
  const full = { createWritable: async () => ({ write: async () => { throw new Error("disk full"); }, close: async () => {} }) };
  const r1 = await T.writeHandle(good, "abc"), r2 = await T.writeHandle(lost, "abc"), r3 = await T.writeHandle(full, "abc");
  ok("a write through a handle gives null when it worked, and the error when permission is lost or the write fails",
     r1 === null && wrote.join() === "abc,closed" && r2?.name === "NotAllowedError" && r3?.message === "disk full");
}
await handles();

// 5. The pages: no page reads a size or a count from a file name, so stamped files import as before.
for (const page of ["site/glyph-editor.html", "site/glyph-animator.html"]) {
  const text = readFileSync(new URL(page, ROOT), "utf8");
  ok(`${page}: Save keeps the work unsaved when the write fails, and no import parses a file name`,
     text.includes("GlyphTools.writeHandle(handle, text)") && !text.includes("createWritable")
     && !/\.name\.(match|split|replace)\(/.test(text) && text.includes('GlyphTools.stampOption($("stamp-box"))'));
}
