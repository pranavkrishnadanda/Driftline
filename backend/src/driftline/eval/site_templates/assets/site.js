// Theme: follow the system unless the viewer picked one. Runs in <head> to avoid a flash.
(function () {
  var KEY = "driftline-report-theme";
  var root = document.documentElement;
  function read() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function write(value) {
    try { localStorage.setItem(KEY, value); } catch (e) { /* storage blocked: still switch */ }
  }
  var saved = read();
  if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);

  function current() {
    var set = root.getAttribute("data-theme");
    if (set) return set;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.addEventListener("DOMContentLoaded", function () {
    var button = document.querySelector(".theme-toggle");
    if (!button) return;
    function label() {
      var next = current() === "dark" ? "light" : "dark";
      button.setAttribute("aria-label", "Switch to " + next + " theme");
      button.setAttribute("title", "Switch to " + next + " theme");
    }
    label();
    button.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      write(next);
      label();
    });
  });
})();
