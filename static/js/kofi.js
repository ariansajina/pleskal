// Lazy-loads the Ko-fi donation widget on first interaction (or after a
// short delay), instead of pulling the third-party script + CSP exceptions
// in on every page load.
(function () {
  var loaded = false;

  function loadWidget() {
    if (loaded) return;
    loaded = true;
    events.forEach(function (evt) {
      window.removeEventListener(evt, loadWidget);
    });
    clearTimeout(timer);

    var script = document.createElement("script");
    script.src = "https://storage.ko-fi.com/cdn/scripts/overlay-widget.js";
    script.onload = function () {
      kofiWidgetOverlay.draw("pleskal", {
        type: "floating-chat",
        "floating-chat.donateButton.text": "",
        "floating-chat.donateButton.background-color": "#AAAADD",
        "floating-chat.donateButton.text-color": "#323842",
      });
    };
    document.body.appendChild(script);
  }

  var events = ["scroll", "mousemove", "touchstart", "keydown"];
  events.forEach(function (evt) {
    window.addEventListener(evt, loadWidget, { passive: true, once: true });
  });
  var timer = setTimeout(loadWidget, 4000);
})();
