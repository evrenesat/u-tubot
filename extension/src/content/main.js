export const ready = true;

function mark() {
  if (typeof document !== "undefined" && document.documentElement) {
    document.documentElement.dataset.utubot = "1";
    return true;
  }

  return false;
}

if (!mark() && typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", mark);
}
