// The download notice (site/js/app/notice.js) under node, with a document just large
// enough for it: a first click shows the notice and saves nothing; "Not now" saves
// nothing; "Download" lets one click through. Run by test/test_js_notice.py.
import { guardDownload, NOTICE } from "../site/js/app/notice.js";

function element(tag) {
  const el = { tag, children: [], listeners: {}, textContent: "", returnValue: "", open: false,
    append(...kids) { this.children.push(...kids); },
    addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); },
    remove() { doc.body.children = doc.body.children.filter((c) => c !== this); },
    showModal() { this.open = true; },
    close(value) { this.returnValue = value; this.open = false; for (const fn of this.listeners.close ?? []) fn(); },
  };
  return el;
}
const doc = { createElement: element, body: element("body") };

let saved = 0;
const link = element("a");
link.click = () => {
  const event = { prevented: false, preventDefault() { this.prevented = true; } };
  for (const fn of link.listeners.click) fn(event);
  if (!event.prevented) saved++;
};
guardDownload(link, doc);

const ok = (name, pass) => { console.log(`${pass ? "OK  " : "FAIL"} ${name}`); if (!pass) process.exitCode = 1; };
const text = (el) => el.textContent + el.children.map((c) => (typeof c === "string" ? c : text(c))).join("");

link.click();
const first = doc.body.children[0];
ok("the first click shows the notice and saves nothing", saved === 0 && first?.open === true);
ok("it tells the reader to back up and to work in new projects or copies",
   NOTICE.points.every(([lead]) => text(first).includes(lead)));
first.close("cancel");
ok("Not now saves nothing and removes the notice", saved === 0 && doc.body.children.length === 0);
link.click();
doc.body.children[0].close("confirm");
ok("Download saves the file once", saved === 1 && doc.body.children.length === 0);
link.click();
ok("the next click shows the notice again", saved === 1 && doc.body.children[0]?.open === true);
