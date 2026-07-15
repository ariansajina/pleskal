// Closes the "Add to calendar" <details> dropdown on outside click or Escape,
// returning focus to the <summary> toggle when closed via keyboard.
document.addEventListener("DOMContentLoaded", function () {
  var details = document.querySelector("[data-calendar-dropdown]");
  if (!details) return;
  var summary = details.querySelector("summary");

  document.addEventListener("click", function (e) {
    if (details.open && !details.contains(e.target)) {
      details.open = false;
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && details.open) {
      details.open = false;
      if (summary) summary.focus();
    }
  });
});
