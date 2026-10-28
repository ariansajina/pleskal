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

// "Instagram story" button: shares the event's story image (its card on a
// 1080x1920 canvas) through the share sheet, where Instagram opens it in the
// story editor. A web page can't attach Instagram's link sticker, so the
// event link is copied too, ready to paste into one. The button stays hidden
// except on phones and tablets that can share files: desktop browsers can
// share files too, but there's no Instagram app there to share to.
document.addEventListener("DOMContentLoaded", function () {
  var btn = document.getElementById("story-btn");
  if (!btn || typeof navigator.canShare !== "function") return;
  if (!window.matchMedia("(pointer: coarse) and (hover: none)").matches) return;

  var probe = new File([""], "story.jpg", { type: "image/jpeg" });
  if (!navigator.canShare({ files: [probe] })) return;
  btn.hidden = false;

  var label = btn.textContent;
  var pending = null;
  var file = null;

  // Start the download on touch, so the image is usually in hand by the
  // click: share() must run while the tap still counts as a user gesture.
  function load() {
    if (!pending) {
      pending = fetch(btn.href)
        .then(function (response) {
          if (!response.ok) throw new Error(response.status);
          return response.blob();
        })
        .then(function (blob) {
          file = new File([blob], btn.getAttribute("download"), {
            type: "image/jpeg",
          });
          return file;
        })
        .catch(function (error) {
          pending = null;
          throw error;
        });
    }
    return pending;
  }

  function share() {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(window.location.href).catch(function () {});
    }
    return navigator.share({ files: [file] });
  }

  btn.addEventListener("pointerdown", function () {
    load().catch(function () {});
  });

  btn.addEventListener("click", function (event) {
    event.preventDefault();
    if (file) {
      btn.textContent = label;
      share().catch(function () {});
      return;
    }
    btn.textContent = "Preparing…";
    load()
      .then(function () {
        btn.textContent = label;
        return share().catch(function (error) {
          // The download outlasted the tap's user gesture: ask for another.
          if (error && error.name === "NotAllowedError") {
            btn.textContent = "Tap again to share";
          }
        });
      })
      .catch(function () {
        btn.textContent = label;
        window.location.href = btn.href;
      });
  });
});
