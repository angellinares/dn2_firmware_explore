/**
 * What a withdrawn mod looks like on the site.
 *
 * One subject: turning an entry of `mods/availability.js` into the notice and
 * putting it where the download control would be. `shell.js` refuses to load or
 * build for a withdrawn mod; this module only draws.
 */

function build(flag, doc) {
  const box = doc.createElement("div");
  box.className = "note unavailable";
  const title = doc.createElement("p");
  const strong = doc.createElement("strong");
  strong.textContent = flag.title;
  title.append(strong);
  const reason = doc.createElement("p");
  reason.textContent = flag.reason;
  box.append(title, reason);
  return box;
}

/** On a mod's page: the notice replaces the file chooser, and the build bar goes. */
export function withdrawPage(flag, doc = document) {
  const drop = doc.getElementById("drop");
  drop?.replaceWith(build(flag, doc));
  doc.getElementById("bar")?.remove();
}

/** On the mod list: the card's tag says so and the notice follows its first paragraph. */
export function markCard(card, flag, doc = document) {
  const tag = card.querySelector(".tag");
  if (tag) { tag.className = "tag untested"; tag.textContent = "Unavailable for now"; }
  const notice = build(flag, doc);
  notice.style.marginTop = ".8rem";
  card.querySelector("p")?.after(notice);
}
