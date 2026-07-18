// Drives the "More filters (N)" badge on the filter-disclosure summary.
// Counts only filters that live inside the collapsible panel — the
// quickbar's own This week/Next week chips are excluded since they're
// always visible.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("form[data-today]").forEach(function (form) {
    var summary = form.querySelector("[data-filter-count-label]");
    var countEl = form.querySelector("[data-filter-count]");
    if (!summary || !countEl) return;

    function updateCount() {
      var count = 0;

      count += form.querySelectorAll(
        'input[type="checkbox"][name="category"]:checked'
      ).length;
      count += form.querySelectorAll(
        'input[type="checkbox"][name="publisher"]:checked'
      ).length;

      var free = form.querySelector('input[type="checkbox"][name="is_free"]');
      if (free && free.checked) count += 1;

      var wheelchair = form.querySelector(
        'input[type="checkbox"][name="is_wheelchair_accessible"]'
      );
      if (wheelchair && wheelchair.checked) count += 1;

      var search = form.querySelector('input[type="search"][name="q"]');
      if (search && search.value.trim() !== "") count += 1;

      var dateFrom = form.querySelector('[name="date_from"]');
      var dateTo = form.querySelector('[name="date_to"]');
      if (dateFrom && dateTo && dateFrom.value && dateTo.value) {
        // Scoped to the quickbar's own row (This week/Next week), not the
        // panel's date chips (This weekend/This month/Next month) — those
        // live inside .filter-panel, a sibling of that row, and should
        // count as an active panel filter like any other panel field.
        var quickbarChipActive = form.querySelector(
          ".filter-quickbar > .filter-checkboxes [data-quick-date-filter][data-active]"
        );
        if (!quickbarChipActive) count += 1;
      }

      countEl.textContent = count > 0 ? "(" + count + ")" : "";
      summary.setAttribute(
        "aria-label",
        count > 0
          ? "More filters, " + count + " active"
          : "More filters"
      );
    }

    form.addEventListener("change", updateCount);
    form.addEventListener("click", updateCount);
    updateCount();
  });
});
