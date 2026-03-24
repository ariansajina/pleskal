document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-quick-date-filter]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var form = document.getElementById('filter-form');
            form.querySelector('[name="date_from"]').value = btn.dataset.dateFrom;
            form.querySelector('[name="date_to"]').value = btn.dataset.dateTo;
            form.dispatchEvent(new Event('change'));
        });
    });
});
