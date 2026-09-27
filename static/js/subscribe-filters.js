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

    // webcal:// makes calendar apps subscribe instead of importing a one-off copy.
    function webcal(url) {
        return url.replace(/^https?:\/\//, 'webcal://');
    }

    function updateURLs() {
        var qs = buildParams().toString();
        var suffix = qs ? '?' + qs : '';
        var icalUrl = icalBase + suffix;
        var rssUrl  = rssBase  + suffix;
        document.getElementById('ical-url-display').textContent = icalUrl;
        document.getElementById('rss-url-display').textContent  = rssUrl;
        document.getElementById('ical-webcal-link').href = webcal(icalUrl);
        document.getElementById('ical-google-link').href =
            'https://calendar.google.com/calendar/r?cid=' + encodeURIComponent(webcal(icalUrl));
        document.getElementById('rss-open-link').href = rssUrl;
    }

    function selectText(el) {
        var range = document.createRange();
        range.selectNodeContents(el);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
    }

    function copyHandler(displayId, btn, statusId) {
        var status = document.getElementById(statusId);
        var timer;
        function show(msg) {
            status.textContent = msg;
            clearTimeout(timer);
            timer = setTimeout(function () { status.textContent = ''; }, 3000);
        }
        btn.addEventListener('click', function () {
            var el = document.getElementById(displayId);
            // navigator.clipboard is missing on insecure origins and can reject
            // (permissions); fall back to selecting the URL for a manual copy.
            function fallback() {
                selectText(el);
                show('Press Ctrl+C / ⌘C to copy');
            }
            if (!navigator.clipboard) { fallback(); return; }
            navigator.clipboard.writeText(el.textContent).then(function () {
                show('Copied!');
            }, fallback);
        });
    }

    filtersEl.addEventListener('change', updateURLs);
    copyHandler('ical-url-display', document.getElementById('ical-copy-btn'), 'ical-copy-status');
    copyHandler('rss-url-display',  document.getElementById('rss-copy-btn'), 'rss-copy-status');
    updateURLs();
});
