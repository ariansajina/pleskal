document.addEventListener('DOMContentLoaded', function () {
    var buttons = document.querySelectorAll('[data-quick-date-filter]');
    var form = document.getElementById('filter-form');

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
});
