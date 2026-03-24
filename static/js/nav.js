document.addEventListener('DOMContentLoaded', function () {
  var toggle = document.querySelector('.nav-toggle');
  if (!toggle) return;
  toggle.addEventListener('click', function () {
    var nav = toggle.closest('.site-header').querySelector('.site-nav');
    var open = nav.classList.toggle('open');
    toggle.setAttribute('aria-expanded', open);
    nav.setAttribute('aria-hidden', !open);
  });
});
