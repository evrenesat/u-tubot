export function renderPopup(target) {
  const heading = target.ownerDocument.createElement("h1");
  heading.textContent = "u·tubot";
  target.append(heading);
  return heading;
}

if (typeof document !== "undefined") {
  renderPopup(document.getElementById("utubot-popup") ?? document.body);
}