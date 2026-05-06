// Leaflet-backed map for the /map/ page.
//
// - Reads initial pin payload from the <script id="event-map-pins"> JSON block
//   emitted via Django's json_script filter.
// - Re-reads the payload after HTMX swaps the results container, and syncs
//   the Leaflet marker layer without reinitialising the map view.
// - Mobile tab toggling between the map and the list.

(function () {
  "use strict";

  // Copenhagen city centre as the default view.
  var DEFAULT_CENTER = [55.6761, 12.5683];
  var DEFAULT_ZOOM = 12;

  var mapInstance = null;
  var markerLayer = null;
  var hasFitBoundsOnce = false;

  function readPins() {
    var node = document.getElementById("event-map-pins");
    if (!node) return [];
    try {
      var data = JSON.parse(node.textContent || "[]");
      return Array.isArray(data) ? data : [];
    } catch (err) {
      return [];
    }
  }

  function escapeHtml(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatDate(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    try {
      return d.toLocaleString(undefined, {
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (e) {
      return d.toISOString();
    }
  }

  function buildEventEntry(event) {
    var lines = [];
    lines.push(
      '<div class="map-popup-title">' + escapeHtml(event.title) + "</div>",
    );
    var when = formatDate(event.start_datetime);
    var meta = [];
    if (when) meta.push(escapeHtml(when));
    if (event.category_display) meta.push(escapeHtml(event.category_display));
    if (meta.length) {
      lines.push('<div class="map-popup-meta">' + meta.join(" · ") + "</div>");
    }
    if (event.url) {
      lines.push(
        '<a class="map-popup-link" href="' +
          escapeHtml(event.url) +
          '">View event →</a>',
      );
    }
    return '<li class="map-popup-event">' + lines.join("") + "</li>";
  }

  function buildPopup(group) {
    var events = Array.isArray(group.events) ? group.events : [];
    var parts = [];
    if (group.venue_name) {
      parts.push(
        '<div class="map-popup-venue">' +
          escapeHtml(group.venue_name) +
          (events.length > 1 ? " (" + events.length + ")" : "") +
          "</div>",
      );
    }
    parts.push(
      '<ul class="map-popup-list">' +
        events.map(buildEventEntry).join("") +
        "</ul>",
    );
    return parts.join("");
  }

  function renderMarkers(groups) {
    if (!mapInstance) return;
    if (markerLayer) {
      markerLayer.clearLayers();
    } else {
      markerLayer = window.L.layerGroup().addTo(mapInstance);
    }

    var latLngs = [];
    groups.forEach(function (group) {
      var lat = Number(group.lat);
      var lng = Number(group.lng);
      if (!isFinite(lat) || !isFinite(lng)) return;
      var events = Array.isArray(group.events) ? group.events : [];
      if (!events.length) return;
      var title =
        events.length === 1
          ? events[0].title
          : (group.venue_name || "") + " (" + events.length + " events)";
      var marker = window.L.marker([lat, lng], { title: title });
      marker.bindPopup(buildPopup(group), { maxWidth: 320 });
      marker.addTo(markerLayer);
      latLngs.push([lat, lng]);
    });

    if (latLngs.length && !hasFitBoundsOnce) {
      try {
        var bounds = window.L.latLngBounds(latLngs);
        mapInstance.fitBounds(bounds.pad(0.15), { maxZoom: 15 });
        hasFitBoundsOnce = true;
      } catch (e) {
        // ignore bounds errors and keep the default view
      }
    }
  }

  function initMap() {
    var el = document.getElementById("event-map");
    if (!el || !window.L || mapInstance) return;

    var imagePath = el.getAttribute("data-leaflet-image-path");
    if (imagePath) {
      window.L.Icon.Default.prototype.options.imagePath = imagePath;
    }

    mapInstance = window.L.map(el, {
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      scrollWheelZoom: true,
    });

    window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(mapInstance);

    renderMarkers(readPins());
  }

  function refresh() {
    if (!mapInstance) return;
    renderMarkers(readPins());
  }

  function setupMobileTabs() {
    var tabs = document.querySelectorAll("[data-map-tab]");
    var panes = document.querySelectorAll("[data-map-pane]");
    if (!tabs.length || !panes.length) return;

    function show(name) {
      tabs.forEach(function (btn) {
        var active = btn.getAttribute("data-map-tab") === name;
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-selected", active ? "true" : "false");
      });
      panes.forEach(function (pane) {
        var match = pane.getAttribute("data-map-pane") === name;
        if (match) {
          pane.removeAttribute("hidden");
        } else {
          pane.setAttribute("hidden", "");
        }
      });
      if (name === "map" && mapInstance) {
        // Leaflet needs invalidateSize after its container becomes visible.
        setTimeout(function () {
          mapInstance.invalidateSize();
        }, 50);
      }
    }

    function syncVisibility() {
      if (window.matchMedia("(max-width: 900px)").matches) {
        var active = document.querySelector("[data-map-tab].active");
        show(active ? active.getAttribute("data-map-tab") : "map");
      } else {
        panes.forEach(function (pane) {
          pane.removeAttribute("hidden");
        });
      }
    }

    tabs.forEach(function (btn) {
      btn.addEventListener("click", function () {
        show(btn.getAttribute("data-map-tab"));
      });
    });

    window.addEventListener("resize", syncVisibility);
    syncVisibility();
  }

  function boot() {
    initMap();
    setupMobileTabs();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  document.body.addEventListener("htmx:afterSwap", function (evt) {
    if (evt.target && evt.target.id === "event-map-results") {
      refresh();
    }
  });
})();
