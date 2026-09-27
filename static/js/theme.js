// Light/dark theme toggle. Loaded synchronously in <head> (not deferred) so a
// saved choice is applied before first paint. Without a saved choice the page
// follows the system setting via prefers-color-scheme; a choice sets
// data-theme on <html>, which base.html's CSS gives precedence. The choice
// lives only in this browser's localStorage.
(function () {
  var KEY = "theme";
  var root = document.documentElement;
  var systemDark = window.matchMedia("(prefers-color-scheme: dark)");

  // The theme-color metas carry one colour per scheme (selected by their
  // media attribute); a saved choice has to pin both to its own colour.
  var metas = Array.prototype.slice.call(
    document.querySelectorAll('meta[name="theme-color"][media]'),
  );
  var metaDefaults = metas.map(function (meta) {
    return meta.content;
  });
  function themeColor(theme) {
    for (var i = 0; i < metas.length; i++) {
      if (metas[i].media.indexOf(theme) !== -1) return metaDefaults[i];
    }
    return null;
  }

  function readSaved() {
    try {
      var value = localStorage.getItem(KEY);
      return value === "light" || value === "dark" ? value : null;
    } catch (e) {
      return null; // storage blocked: fall back to the system setting
    }
  }

  // The current choice ("light", "dark", or null = follow the system).
  // Kept in memory too, so the toggle still works for this page view when
  // storage is blocked.
  var saved = readSaved();

  function systemTheme() {
    return systemDark.matches ? "dark" : "light";
  }

  function effectiveTheme() {
    return saved || systemTheme();
  }

  function apply() {
    if (saved) {
      root.setAttribute("data-theme", saved);
    } else {
      root.removeAttribute("data-theme");
    }
    metas.forEach(function (meta, i) {
      meta.content = (saved && themeColor(saved)) || metaDefaults[i];
    });
    var button = document.querySelector(".theme-toggle");
    if (button) {
      var label =
        effectiveTheme() === "dark"
          ? "Switch to light mode"
          : "Switch to dark mode";
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
    }
  }

  function toggle() {
    var next = effectiveTheme() === "dark" ? "light" : "dark";
    // Picking the system's own theme clears the choice, so the page goes
    // back to following the system setting.
    saved = next === systemTheme() ? null : next;
    try {
      if (saved) {
        localStorage.setItem(KEY, saved);
      } else {
        localStorage.removeItem(KEY);
      }
    } catch (e) {
      // Storage blocked: the switch lasts for this page view only.
    }
    apply();
  }

  apply();

  if (systemDark.addEventListener) {
    systemDark.addEventListener("change", apply);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.querySelector(".theme-toggle");
    if (!button) return;
    button.addEventListener("click", toggle);
    button.hidden = false;
    apply();
  });
})();
