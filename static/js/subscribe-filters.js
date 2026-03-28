document.addEventListener('DOMContentLoaded', function () {
    var filtersEl = document.getElementById('subscribe-filters');
    if (!filtersEl) return;

    var icalBase = filtersEl.dataset.icalBase;
    var rssBase  = filtersEl.dataset.rssBase;

    function buildParams() {
        var params = new URLSearchParams();
        filtersEl.querySelectorAll('input[name="category"]:checked').forEach(function (cb) {
            params.append('category', cb.value);
        });
        filtersEl.querySelectorAll('input[name="publisher"]:checked').forEach(function (cb) {
            params.append('publisher', cb.value);
        });
        return params;
    }

    function updateURLs() {
        var qs = buildParams().toString();
        var suffix = qs ? '?' + qs : '';
        var icalUrl = icalBase + suffix;
        var rssUrl  = rssBase  + suffix;
        document.getElementById('ical-url-display').textContent = icalUrl;
        document.getElementById('rss-url-display').textContent  = rssUrl;
        document.getElementById('ical-open-link').href = icalUrl;
        document.getElementById('rss-open-link').href  = rssUrl;
    }

    function copyHandler(displayId, btn) {
        btn.addEventListener('click', function () {
            navigator.clipboard.writeText(document.getElementById(displayId).textContent).then(function () {
                var orig = btn.textContent;
                btn.textContent = 'Copied!';
                setTimeout(function () { btn.textContent = orig; }, 2000);
            });
        });
    }

    filtersEl.addEventListener('change', updateURLs);
    copyHandler('ical-url-display', document.getElementById('ical-copy-btn'));
    copyHandler('rss-url-display',  document.getElementById('rss-copy-btn'));
    updateURLs();
});
