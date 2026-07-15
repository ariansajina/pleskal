// Clears the filter form to an empty state (not form.reset(), which would
// restore the server-rendered checked/value attributes — i.e. the currently
// active filters). The button keeps its own hx-get so results still refresh.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-clear-filters]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var form = document.getElementById(btn.getAttribute("data-clear-filters"));
      if (!form) return;

      form.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
        cb.checked = false;
      });
      form.querySelectorAll('input[type="search"], input[type="date"]').forEach(
        function (input) {
          input.value = "";
        }
      );
      var pastRadio = form.querySelector('input[name="past"][value="0"]');
      if (pastRadio) pastRadio.checked = true;
      form.querySelectorAll("[data-quick-date-filter]").forEach(function (chip) {
        chip.removeAttribute("data-active");
      });

      form.dispatchEvent(new Event("change"));
    });
  });
});
