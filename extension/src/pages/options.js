export function renderOptions(target) {
  const heading = target.ownerDocument.createElement("h1");
  heading.textContent = "u·tubot";
  target.append(heading);
  return heading;
}

if (typeof document !== "undefined") {
  renderOptions(document.getElementById("utubot-options") ?? document.body);
}