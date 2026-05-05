// Unified share / copy-link button for the event detail page.
// Uses navigator.share when available (mobile / PWA), falls back to
// copying the current URL to the clipboard otherwise.
document.addEventListener("DOMContentLoaded", function () {
  var btn = document.getElementById("share-btn");
  if (!btn) return;

  var title = btn.getAttribute("data-share-title") || document.title;
  var text = btn.getAttribute("data-share-text") || title;

  function flash(message) {
    var original = btn.getAttribute("data-original-label");
    if (!original) {
      original = btn.textContent;
      btn.setAttribute("data-original-label", original);
    }
    btn.textContent = message;
    setTimeout(function () {
      btn.textContent = original;
    }, 2000);
  }

  if (typeof navigator.share === "function") {
    btn.textContent = "Share";
    btn.addEventListener("click", function () {
      navigator
        .share({ title: title, text: text, url: window.location.href })
        .catch(function () {
          // User dismissed the share sheet or share was blocked; ignore.
        });
    });
    return;
  }

  btn.addEventListener("click", function () {
    if (!navigator.clipboard || !navigator.clipboard.writeText) return;
    navigator.clipboard.writeText(window.location.href).then(function () {
      flash("Copied!");
    });
  });
});
