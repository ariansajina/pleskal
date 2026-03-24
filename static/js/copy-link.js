document.addEventListener("DOMContentLoaded", function () {
  var btn = document.getElementById("copy-link-btn");
  if (!btn) return;
  btn.addEventListener("click", function () {
    navigator.clipboard.writeText(window.location.href).then(function () {
      var original = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(function () {
        btn.textContent = original;
      }, 2000);
    });
  });
});
