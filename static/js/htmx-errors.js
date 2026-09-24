// HTMX leaves the page untouched on 4xx/5xx responses (it does not swap error
// bodies), so without this a rate-limited or failed filter/search request just
// looks like the results silently stopped updating. Surface it instead.
document.addEventListener('DOMContentLoaded', function () {
  var banner = document.getElementById('htmx-error');
  if (!banner) return;
  var text = banner.querySelector('[data-htmx-error-text]');

  function show(message) {
    text.textContent = message;
    banner.hidden = false;
  }

  document.body.addEventListener('htmx:responseError', function (evt) {
    var status = evt.detail.xhr ? evt.detail.xhr.status : 0;
    if (status === 429) {
      show('Too many requests in a short time. Please wait a minute and try again.');
    } else {
      show('Something went wrong loading this. Please try again.');
    }
  });

  document.body.addEventListener('htmx:sendError', function () {
    show('Could not reach pleskal. Check your connection and try again.');
  });

  document.body.addEventListener('htmx:beforeRequest', function () {
    banner.hidden = true;
  });
});
