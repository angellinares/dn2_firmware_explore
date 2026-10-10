/**
 * The notice shown before a modded image is saved.
 *
 * One subject: the reader sees how to protect their projects, then chooses to
 * download or to go back. `shell.js` hands every download link to
 * `guardDownload`; nothing else on a page needs to know the notice exists.
 */

export const NOTICE = {
  title: "Before you install this firmware",
  points: [
    ["Back up your projects.",
     "Use Elektron Transfer to copy every project on the +Drive to your computer."],
    ["Work in new projects, or in copies.",
     "On the modded firmware, create a new project, or save a project under a new name and work in that copy. Keep the original as it is."],
  ],
  confirm: "Download",
  cancel: "Not now",
};

function build(doc) {
  const dialog = doc.createElement("dialog");
  dialog.className = "notice";
  const title = doc.createElement("h2");
  title.textContent = NOTICE.title;
  const list = doc.createElement("ul");
  for (const [lead, rest] of NOTICE.points) {
    const item = doc.createElement("li");
    const strong = doc.createElement("strong");
    strong.textContent = lead;
    item.append(strong, " ", rest);
    list.append(item);
  }
  const form = doc.createElement("form");
  form.method = "dialog";
  const cancel = doc.createElement("button");
  cancel.value = "cancel";
  cancel.textContent = NOTICE.cancel;
  const confirm = doc.createElement("button");
  confirm.value = "confirm";
  confirm.className = "primary";
  confirm.textContent = NOTICE.confirm;
  form.append(cancel, confirm);
  dialog.append(title, list, form);
  return dialog;
}

/**
 * Make `link` show the notice on a click, and save the file only after the
 * reader confirms. The link keeps its `href` and `download`, so the confirmed
 * click is the browser's own download.
 */
export function guardDownload(link, doc = document) {
  let confirmed = false;
  link.addEventListener("click", (event) => {
    if (confirmed) { confirmed = false; return; }
    event.preventDefault();
    const dialog = build(doc);
    doc.body.append(dialog);
    dialog.addEventListener("close", () => {
      const go = dialog.returnValue === "confirm";
      dialog.remove();
      if (go) { confirmed = true; link.click(); }
    });
    dialog.showModal();
  });
}
