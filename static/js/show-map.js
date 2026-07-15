document.addEventListener("DOMContentLoaded", function () {
  var btn = document.getElementById("show-map-btn");
  var modal = document.getElementById("map-modal");
  if (!btn || !modal) return;
  var iframe = modal.querySelector("#map-modal-iframe");
  var closeBtn = modal.querySelector(".map-modal__close");
  // Everything outside the modal, made inert while it's open so Tab can't
  // walk out of the dialog and screen readers see it as unreachable.
  var outsideEls = document.querySelectorAll(
    "body > header, body > main, body > footer"
  );

  function open() {
    var lat = parseFloat(btn.getAttribute("data-lat"));
    var lon = parseFloat(btn.getAttribute("data-lon"));
    if (isNaN(lat) || isNaN(lon)) return;
    var delta = 0.005;
    var bbox = [lon - delta, lat - delta, lon + delta, lat + delta].join(",");
    var src =
      "https://www.openstreetmap.org/export/embed.html?bbox=" +
      encodeURIComponent(bbox) +
      "&layer=mapnik&marker=" +
      encodeURIComponent(lat + "," + lon);
    iframe.setAttribute("src", src);
    modal.removeAttribute("hidden");
    outsideEls.forEach(function (el) {
      el.setAttribute("inert", "");
    });
    document.body.style.overflow = "hidden";
    if (closeBtn) closeBtn.focus();
    document.addEventListener("keydown", onKey);
  }

  function close() {
    modal.setAttribute("hidden", "");
    iframe.setAttribute("src", "");
    outsideEls.forEach(function (el) {
      el.removeAttribute("inert");
    });
    document.body.style.overflow = "";
    document.removeEventListener("keydown", onKey);
    btn.focus();
  }

  function onKey(e) {
    if (e.key === "Escape") close();
  }

  btn.addEventListener("click", open);
  modal.querySelectorAll("[data-close]").forEach(function (el) {
    el.addEventListener("click", close);
  });
});
