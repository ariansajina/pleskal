// Scroll a series' date strip so the current date is in view.
document.querySelectorAll("[data-date-strip]").forEach(function (strip) {
  var current = strip.querySelector(".date-tile--current");
  if (!current) return;
  var right = current.offsetLeft - strip.offsetLeft + current.offsetWidth;
  if (right > strip.clientWidth * 0.8) {
    strip.scrollLeft = right - strip.clientWidth * 0.5;
  }
});
