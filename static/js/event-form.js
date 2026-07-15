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
