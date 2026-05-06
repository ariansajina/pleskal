document.addEventListener('DOMContentLoaded', function () {
    var forms = document.querySelectorAll('form[data-today]');

    forms.forEach(function (form) {
        var buttons = form.querySelectorAll('[data-quick-date-filter]');
        if (!buttons.length) return;

        function syncActiveState() {
            var currentFrom = form.querySelector('[name="date_from"]').value;
            var currentTo = form.querySelector('[name="date_to"]').value;
            buttons.forEach(function (btn) {
                if (currentFrom && currentTo &&
                    btn.dataset.dateFrom === currentFrom &&
                    btn.dataset.dateTo === currentTo) {
                    btn.setAttribute('data-active', '');
                } else {
                    btn.removeAttribute('data-active');
                }
            });
        }

        buttons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var alreadyActive = btn.hasAttribute('data-active');
                if (alreadyActive) {
                    form.querySelector('[name="date_from"]').value = form.dataset.today || '';
                    form.querySelector('[name="date_to"]').value = '';
                } else {
                    form.querySelector('[name="date_from"]').value = btn.dataset.dateFrom;
                    form.querySelector('[name="date_to"]').value = btn.dataset.dateTo;
                }
                syncActiveState();
                form.dispatchEvent(new Event('change'));
            });
        });

        syncActiveState();

        // When switching past/upcoming, clear or restore date_from so it doesn't
        // accidentally activate the date-range filter and bypass the toggle.
        var pastRadios = form.querySelectorAll('[name="past"]');
        pastRadios.forEach(function (radio) {
            radio.addEventListener('change', function () {
                var dateFromInput = form.querySelector('[name="date_from"]');
                var dateToInput = form.querySelector('[name="date_to"]');
                if (this.value === '1') {
                    // Switching to past: clear date range so it stays inactive
                    dateFromInput.value = '';
                    dateToInput.value = '';
                } else {
                    // Switching to upcoming: restore today as the lower bound
                    if (!dateFromInput.value) {
                        dateFromInput.value = form.dataset.today || '';
                    }
                }
                syncActiveState();
            });
        });
    });
});
