/* Register the pleskal service worker.
 * Kept in a separate static file (not inline) so the strict CSP
 * `script-src 'self'` policy is satisfied without nonces or hashes.
 */
(function () {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", function () {
    navigator.serviceWorker
      .register("/service-worker.js", { scope: "/" })
      .catch(function () {
        /* Registration failures are non-fatal; the site works without the SW. */
      });
  });
})();
