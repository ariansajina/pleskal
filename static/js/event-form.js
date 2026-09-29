// Toggle the "Price note" field visibility based on the "Free event" checkbox.
document.addEventListener("DOMContentLoaded", function () {
  var isFreeCheckbox = document.querySelector("[data-free-toggle]");
  var priceNoteWrapper = document.getElementById("price-note-wrapper");
  if (!isFreeCheckbox || !priceNoteWrapper) return;

  function updatePriceNoteVisibility() {
    priceNoteWrapper.style.display = isFreeCheckbox.checked ? "none" : "block";
  }

  updatePriceNoteVisibility();
  isFreeCheckbox.addEventListener("change", updatePriceNoteVisibility);
});

// Repeat controls (templates/events/partials/repeat_fields.html): show only
// what the chosen option needs, label the date-dependent options for the
// chosen date (as events/forms.py does server-side), and hide the section
// when an edit applies to only one occurrence of a repeating event.
document.addEventListener("DOMContentLoaded", function () {
  var section = document.querySelector("[data-repeat-section]");
  var select = document.getElementById("id_repeat");
  var dateInput = document.getElementById("id_date");
  var unitSelect = document.getElementById("id_repeat_unit");
  if (!section || !select || !dateInput || !unitSelect) return;

  var WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  var ORDINALS = ["first", "second", "third", "fourth", "fifth"];
  var custom = section.querySelector("[data-repeat-custom]");
  var ends = section.querySelector("[data-repeat-ends]");
  var scopeInputs = document.querySelectorAll("input[name='scope']");

  function parseDate(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    return match ? new Date(+match[1], +match[2] - 1, +match[3]) : null;
  }

  function setAvailable(input, available, fallbackValue) {
    input.disabled = !available;
    input.hidden = !available;
    if (!available && (input.selected || input.checked)) {
      if (input.tagName === "OPTION") select.value = fallbackValue;
      else document.querySelector("input[name='repeat_monthly'][value='" + fallbackValue + "']").checked = true;
    }
  }

  function relabel() {
    var day = parseDate(dateInput.value);
    if (!day) return;
    var weekday = WEEKDAYS[(day.getDay() + 6) % 7];
    var nth = Math.floor((day.getDate() - 1) / 7) + 1;
    var daysInMonth = new Date(day.getFullYear(), day.getMonth() + 1, 0).getDate();
    var isLast = day.getDate() + 7 > daysInMonth;
    var presets = {
      weekly: "Weekly on " + weekday,
      monthly_day: "Monthly on day " + day.getDate(),
      monthly_nth: "Monthly on the " + ORDINALS[nth - 1] + " " + weekday,
      monthly_last: "Monthly on the last " + weekday,
    };
    Array.prototype.forEach.call(select.options, function (option) {
      if (presets[option.value]) option.textContent = presets[option.value];
      if (option.value === "monthly_nth") setAvailable(option, nth <= 4, isLast ? "monthly_last" : "");
      if (option.value === "monthly_last") setAvailable(option, isLast, nth <= 4 ? "monthly_nth" : "");
    });
    var monthly = {
      day: "On day " + day.getDate(),
      nth: "On the " + ORDINALS[nth - 1] + " " + weekday,
      last: "On the last " + weekday,
    };
    section.querySelectorAll("[data-monthly-option]").forEach(function (label) {
      var value = label.getAttribute("data-monthly-option");
      label.querySelector("[data-monthly-label]").textContent = monthly[value];
      if (value === "last") {
        label.hidden = !isLast;
        setAvailable(label.querySelector("input"), isLast, "day");
      }
    });
    // A new custom weekly rule starts on the chosen date's weekday.
    var weekdayBoxes = section.querySelectorAll("input[name='repeat_weekdays']");
    var anyChecked = Array.prototype.some.call(weekdayBoxes, function (box) { return box.checked; });
    if (!anyChecked && weekdayBoxes.length) weekdayBoxes[(day.getDay() + 6) % 7].checked = true;
  }

  function update() {
    var value = select.value;
    custom.hidden = value !== "custom";
    ends.hidden = value === "";
    section.querySelectorAll("[data-repeat-unit]").forEach(function (group) {
      group.hidden = group.getAttribute("data-repeat-unit") !== unitSelect.value;
    });
    if (scopeInputs.length) {
      var scope = document.querySelector("input[name='scope']:checked");
      section.hidden = !scope || scope.value === "this";
    }
  }

  // Typing an end date or a count picks the matching "Ends" option.
  [["id_repeat_until", "on"], ["id_repeat_count", "after"]].forEach(function (pair) {
    var input = document.getElementById(pair[0]);
    if (!input) return;
    input.addEventListener("focus", function () {
      var radio = document.querySelector("input[name='repeat_ends'][value='" + pair[1] + "']");
      if (radio && !radio.checked) {
        radio.checked = true;
        radio.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  });

  relabel();
  update();
  dateInput.addEventListener("change", function () { relabel(); update(); });
  select.addEventListener("change", update);
  unitSelect.addEventListener("change", update);
  scopeInputs.forEach(function (input) { input.addEventListener("change", update); });
});
