# pleskal UI Review

A review of the user interface for site visitors and logged-in users (account
management + event publishing). Findings are ranked by importance. Each finding
includes a suggested implementation intended to be handed to a coding agent.
No changes have been made — this document is the only deliverable.

**Scope reviewed:** `templates/` (base, events, accounts, partials),
`static/js/*.js`, `static/css/input.css`, `config/middleware.py` (CSP),
`events/forms.py`, `events/models.py`, relevant views.

**Constraint honored throughout:** keep the established aesthetic — cream
surface, dotted background, `--blue` ink, Playfair Display italics, uppercase
letter-spaced labels, sharp corners, offset box shadows. None of the fixes
below require visual redesign; they are corrections and refinements inside the
existing design language.

---

## Summary

| # | Importance | Finding |
|---|---|---|
| H1 | **High** | The site's own CSP blocks shipped UI behavior: both web fonts, the price-note toggle, the calendar-dropdown close, and "Clear filters" |
| H2 | **High** | Filter chips are invisible to keyboard users (no focus indicator) and filter controls have no programmatic labels |
| H3 | **High** | Legibility: 10.4 px UI text, and several color pairs fail WCAG contrast (4 of 8 category badges, placeholders, checkbox borders) |
| H4 | **High** | Draft events are visually indistinguishable from published events in listings — `show_draft_badge` is passed but never rendered |
| M1 | Medium | Map modal has no focus trap; calendar dropdown has no Escape/keyboard close; mobile nav `aria-hidden` can desync |
| M2 | Medium | No skip link; event listings have no heading structure (titles and date separators are `<div>`s) |
| M3 | Medium | Screen-reader noise: decorative ornaments not hidden, duplicate image alt text, whole result list is an `aria-live` region |
| M4 | Medium | Filter panel UX: takes over the mobile viewport, and gives no feedback about active filters / result count |
| L1 | Low | Animations ignore `prefers-reduced-motion` |
| L2 | Low | Dead UI code: unused templates, orphaned CSS (moderation badges, `.stat-card`, `--star`), unused `my_events.html` |
| L3 | Low | Event form cannot express multi-day events even though the model supports it |
| L4 | Low | Ko-fi third-party script loads on every page |

---

## High importance

### H1. The site's own CSP blocks shipped UI behavior

**Problem.** `config/middleware.py` sends
`script-src 'self' https://storage.ko-fi.com` and
`style-src 'self' 'unsafe-inline' https://storage.ko-fi.com; font-src 'self'`
on every response, in every environment (the middleware is unconditional in
`config/settings.py:87`). Its own docstring says "no inline scripts needed" —
but the templates contain inline scripts and handlers, and load Google Fonts
cross-origin. All of these are silently blocked by the browser:

1. **Both display fonts never load.** `templates/base.html:34-36` links
   `fonts.googleapis.com` (blocked by `style-src`) and `fonts.gstatic.com`
   (blocked by `font-src 'self'`). Playfair Display and Instrument Sans — the
   backbone of the aesthetic — fall back to generic `serif`/`system-ui`
   everywhere.
2. **Price-note toggle on the event form is dead.**
   `templates/events/event_form.html:186-204` is an inline `<script>` blocked
   by `script-src 'self'`. The "Price note" field never hides when "Free
   event" is checked.
3. **Calendar dropdown never closes on outside click.**
   `templates/events/event_detail.html:195-205` is an inline `<script>`,
   blocked. The "Add to calendar" `<details>` stays open until re-clicked.
4. **"Clear filters" does not clear the form.**
   `templates/events/partials/event_filter_panel.html:117` uses an inline
   `onclick="...reset()"` attribute — inline event handlers are blocked by a
   CSP without `'unsafe-inline'`/`'unsafe-hashes'`. The `hx-get` still fires
   (htmx attributes are fine), so the *results* reset but every chip, date and
   checkbox stays visually active — a confusing state mismatch.

**Suggested implementation.**

- **Self-host the fonts** (consistent with the project's vendoring of HTMX and
  Leaflet, removes a third-party dependency and a GDPR-sensitive Google
  request, and is faster):
  - Download the used cuts as woff2 into `static/fonts/`: Playfair Display
    700/900 + italics, Instrument Sans 400/500/600 + 400 italic.
  - Declare `@font-face` rules (with `font-display: swap`) in a small
    `static/css/fonts.css` linked from `base.html`, or at the top of the
    existing inline `<style>` block (allowed by `style-src 'unsafe-inline'`,
    but font *files* load via `font-src 'self'`, which self-hosting satisfies).
  - Remove the three Google Fonts `<link>` tags from `base.html:34-36`.
- **Move the two inline scripts into static files** and load them with
  `{% static %}` + `defer`:
  - `static/js/event-form.js` — the price-note toggle. Don't template the
    element id; Django renders it as `id_is_free`, or better, mark the
    elements with `data-` attributes (`data-free-toggle`,
    `id="price-note-wrapper"` already exists) and query those.
  - Fold the details-close behavior into `static/js/share.js` (already loaded
    on the detail page) or a new `static/js/calendar-dropdown.js`. While
    there, also close on `Escape` (see M1).
- **Fix "Clear filters" properly.** `form.reset()` was subtly wrong even
  without CSP: it restores the *server-rendered* `checked`/`value` attributes,
  i.e. the currently-active filters, not an empty form. Replace the `onclick`
  with a `data-clear-filters` attribute handled in the shared filter JS
  (`static/js/quick-date-filters.js` is already loaded on both list and map
  pages, or introduce `filter-panel.js`): uncheck all checkboxes, empty
  `q`/`date_from`/`date_to`, reset the `past` radio to `0`, remove
  `data-active` from quick-date chips. Keep the existing `hx-get` on the
  button so the results still refresh.
- **Guard against regression:** add a test asserting no `onclick=`/`<script>`
  without `src` appears in rendered pages, or at minimum a comment in
  `config/middleware.py` pointing to this rule; the middleware docstring
  already states the intent.

---

### H2. Filter chips are unusable by keyboard/AT users; filter controls have no accessible names

**Problem.** The filter panel (shared by the home page, map page, and — same
pattern — the subscribe page) hides its real checkboxes
(`templates/base.html:411-417`: `opacity: 0; width: 1px`) and styles the
adjacent `.filter-chip` span. There is:

- **No focus indicator on the chip.** The hidden input receives focus, but no
  `:focus-visible + .filter-chip` rule exists, so a keyboard user tabbing
  through Category/Publisher chips sees nothing move on screen. The global
  `:focus-visible` outline (`base.html:112`) draws around the invisible 1px
  input.
- **No group labels.** "Search", "Category", "Publisher", "Date range" are
  plain `<span class="filter-panel__group-label">` elements
  (`event_filter_panel.html:29,45,58,78`) — screen readers announce a bare
  list of checkbox names ("Performance", "Workshop"…) with no indication of
  what the group means. The two date inputs have no accessible name at all.
- The search input's only label is its placeholder.

**Suggested implementation.** All markup-level, no visual change:

- Add to the base stylesheet:
  ```css
  .filter-checkboxes input[type="checkbox"]:focus-visible + .filter-chip {
    outline: 2px solid var(--blue);
    outline-offset: 2px;
  }
  ```
- Convert each chip group to `<fieldset class="filter-panel__group">` with
  `<legend class="filter-panel__group-label">Category</legend>`, and add a
  reset so it renders identically:
  ```css
  .filter-panel fieldset { border: none; margin: 0; padding: 0; min-width: 0; }
  .filter-panel legend { padding: 0; }
  ```
  Apply in `templates/events/partials/event_filter_panel.html` (Category,
  Publisher, Date range groups) and `templates/events/subscribe.html`
  (Category, Publisher).
- Search: turn the span into a real `<label for="filter-q">Search</label>` and
  give the input `id="filter-q"` (template takes `filter_form_id`, so use
  `id="{{ filter_form_id }}-q"` to keep the include reusable).
- Date inputs: `aria-label="From date"` / `aria-label="To date"` (the visible
  "Date range" legend + these gives a complete name).
- The "When" radio group in
  `templates/events/partials/when_filter_group.html` should likewise become a
  `fieldset`/`legend`.

---

### H3. Legibility: 10.4 px UI text and several WCAG contrast failures

**Problem.** Two related issues in the design tokens
(`templates/base.html:49-89, 258-320`):

- **Type sizes.** `--text-xs: 0.65rem` (10.4 px) is used for badges, form
  labels, filter chips, and the footer of every card; `--text-sm: 0.75rem`
  (12 px) for nav links, event meta, errors, and alerts. 10–12 px uppercase,
  letter-spaced text is genuinely hard to read, especially for the
  older/low-vision slice of a general-public events audience.
- **Contrast failures** (measured against WCAG 2.1 AA, 4.5:1 for text this
  small):

  | Pair | Ratio | Verdict |
  |---|---|---|
  | Open practice badge `#0891B2` on `#CFFAFE` | 3.29:1 | fail |
  | Social badge `#EA580C` on `#FFF7ED` | 3.35:1 | fail |
  | Free badge `#059669` on `#ECFDF5` | 3.58:1 | fail |
  | Performance badge `#E11D48` on `#FFF1F2` | 4.28:1 | fail |
  | Placeholder `--cream-dim #C8C4B4` on `#F4F0E8` | 1.54:1 | fail |
  | Checkbox border `--border #AAAADD` on `#F4F0E8` | 1.94:1 | fail (3:1 applies to UI component boundaries) |
  | Workshop `#2563EB`, talk `#64748B`, worksharing `#9333EA`, draft, other, `--ink-muted`, `--blue` | ≥4.55:1 | pass |

**Suggested implementation.** Token-level changes only; the palette keeps its
hue relationships and the badges keep their pale tinted backgrounds:

- Bump the two smallest steps: `--text-xs: 0.7rem` (11.2 px) and
  `--text-sm: 0.8125rem` (13 px). Leave `--text-base` and up unchanged. This
  is a one-line-each change that preserves the hierarchy; spot-check the
  header nav and card footers afterwards for wrapping.
- Darken the failing badge foregrounds one Tailwind step (verified ratios on
  their existing backgrounds):
  - `--c-perf: #BE123C` (5.72:1 on `#FFF1F2`)
  - `--c-op: #0E7490` (4.79:1 on `#CFFAFE`)
  - `--c-social: #C2410C` (4.88:1 on `#FFF7ED`)
  - `--c-free: #047857` (5.21:1 on `#ECFDF5`)
  These variables are also used for solid-on-white button/alert text
  (`.btn--danger`, `.alert--error`, "Free admission" on the detail page),
  where darker only helps.
- Placeholders: replace `--cream-dim` as placeholder color with a muted
  violet that reads as "hint" but is legible, e.g. `#75719F` (4.0:1), or
  simply `color: var(--ink-muted); opacity: 0.75`.
- Checkbox/chip borders: darken `--border` to `#6B69AD` (4.35:1) **or**, if
  that shifts the aesthetic more than wanted, keep `--border` for hairlines
  and introduce `--border-strong: #6B69AD` used only for interactive control
  borders (`.form-check input`, `.filter-chip`, `.form-input` underline).

---

### H4. Draft events are indistinguishable from published events in listings

**Problem.** `templates/accounts/publisher_profile.html:37` renders the
owner's drafts with
`{% include "events/partials/event_card.html" with event=event show_draft_badge=True %}`,
but `templates/events/partials/event_card.html` never references
`show_draft_badge` — the flag is dead, and `.badge--draft`
(`base.html:277`) is orphaned CSS. The only place draft status is visible is
the banner on the detail page. On the profile page the "Drafts" section
heading helps, but the moment a user glances at a card (or the section
boundary scrolls off screen) there is no per-event signal, and the card is
visually identical to a live event.

**Suggested implementation.** In
`templates/events/partials/event_card.html`, inside the `.event-tags` footer
next to the category badge:

```django
{% if event.is_draft %}<span class="badge badge--draft">Draft</span>{% endif %}
```

Keying off `event.is_draft` directly (rather than the include flag) is safe —
every public queryset already excludes drafts, so the badge can only ever
appear to the owner — and it also covers any future listing that forgets to
pass the flag. Remove the now-unused `show_draft_badge=True` argument from
`publisher_profile.html`, or keep the flag as an explicit opt-in if you prefer
`{% if show_draft_badge and event.is_draft %}`. Add a factory-based template
test: profile page with a draft renders the badge, public list never does.

---

## Medium importance

### M1. Dialog and disclosure keyboard behavior

**Problem.**

- **Map modal** (`templates/events/event_detail.html:176-187`,
  `static/js/show-map.js`): good foundations (`role="dialog"`,
  `aria-modal="true"`, Escape closes, focus moves in and restores on close) —
  but there is **no focus trap**: Tab walks out of the modal into the page
  behind the backdrop while `aria-modal` tells AT the rest of the page is
  inert. It isn't.
- **"Add to calendar" `<details>` dropdown** (`event_detail.html:102-110`):
  no Escape close and no outside-click close in practice (see H1.3); focus
  can leave the open dropdown, which then floats over content.
- **Mobile nav** (`static/js/nav.js`): toggling sets `aria-hidden` on
  `.site-nav`. If a user closes the menu on mobile (nav gets
  `aria-hidden="true"`) and rotates/resizes to desktop, the CSS shows the nav
  but it remains hidden from AT.

**Suggested implementation.**

- In `show-map.js`, trap Tab within `.map-modal__panel` (the classic
  first/last focusable cycle — the panel only has the iframe and the Close
  button, so this is ~10 lines), or set `inert` on `header` + `main` +
  `footer` while open and remove it on close (`inert` is supported in all
  evergreen browsers and is simpler than a manual trap).
- In the (newly externalized, per H1) calendar-dropdown script: close the
  `<details>` on `Escape` and return focus to the `<summary>`; the
  outside-click close comes along for free once the script actually runs.
- In `nav.js`, stop toggling `aria-hidden` entirely — `display: none` (the
  closed state's CSS) already removes the nav from the accessibility tree,
  and on desktop the nav is visible. Keep `aria-expanded` on the button.

### M2. No skip link, and event listings have no heading structure

**Problem.** Every page starts with the same sticky header and (on the list
pages) a dense filter panel; there is no skip link, so keyboard users tab
through the entire nav + every filter chip to reach content. Within results,
event titles are `<div class="event-title">` and day separators are
`<div class="section-rule">` (`event_card.html:5`,
`event_list_results.html:10`) — a screen-reader user cannot navigate the
calendar by headings, which is the primary way long lists are skimmed with AT.

**Suggested implementation.**

- Add as the first element inside `<body>` in `base.html`:
  ```html
  <a class="skip-link" href="#main-content">Skip to content</a>
  ```
  give `<main>` `id="main-content"`, and add the standard visually-hidden-
  until-focused CSS (position absolute, off-screen; on `:focus` restore
  position, style it like `.nav-btn--filled` so it matches the aesthetic).
- Make day separators headings: `<h2 class="section-rule">…</h2>` (the class
  already provides all styling; add `font-weight`/`font-size` resets if the
  UA h2 styles bleed through — the universal reset at `base.html:92` already
  zeroes margins).
- Make card titles `<h3 class="event-title">` inside the link. Same visual
  output (the class fully styles it), correct outline. Apply the same to
  `publisher_profile.html` drafts/lists (its section heading "Drafts" is
  already an `h2`, which slots in consistently).

### M3. Screen-reader noise

**Problem.** Several purely decorative elements are announced:

- Ornament rows `✦ · ✦ · ✦` on every hero (`page-hero__ornrow`, e.g.
  `event_list.html:8`, `login.html:9`) — read as "black four pointed star
  middle dot…".
- Every flash message is prefixed with a literal `✦` (`base.html:585`).
- Card thumbnails carry `alt="{{ event.title }}"`
  (`event_card.html:35`) inside a link that already contains the title —
  every card link is announced with the title twice. The detail-page image
  (`event_detail.html:124`) legitimately keeps the alt.
- The whole result list is a live region:
  `<div id="event-list" aria-live="polite">` (`event_list.html:23`) — after
  every filter keystroke settles, AT users get the entire page of cards
  re-announced.

**Suggested implementation.**

- `aria-hidden="true"` on all `page-hero__ornrow` divs (they're already
  `user-select: none`).
- In the messages block, wrap the star: `<span aria-hidden="true">✦</span>
  {{ message }}`.
- Card thumbnails: `alt=""` (decorative — the link text already names the
  event).
- Remove `aria-live` from `#event-list` / `#event-map-results`; instead add a
  small visually-hidden status element updated by the results partial, e.g.
  `<p class="sr-only" role="status">{{ page_obj.paginator.count }} event{{ … |pluralize }} shown</p>`
  at the top of `event_list_results.html` (add an `.sr-only` utility class —
  none exists yet). The `#htmx-indicator` live region can stay.

### M4. Filter panel UX on mobile; no active-filter feedback

**Problem.** On a phone, the home page shows hero → search → When → ~7
category chips → publisher chips → date range + 4 quick chips → 2 checkboxes →
Clear button before the first event appears — roughly two viewports of
controls for the most common intent ("what's on?"). And once filters are
applied there is no summary of *what* is active or *how many* results matched;
after H1's fix the chips show state, but a user who scrolled down sees no
trace.

**Suggested implementation.** (Keeps the panel exactly as-is on desktop.)

- Wrap the panel body in a native `<details class="filter-disclosure">` whose
  `<summary>` is styled as a full-width `.filter-chip`-like bar
  ("Filter events ✦"), and use CSS so it is **forced open and the summary
  hidden at ≥768 px**:
  ```css
  @media (min-width: 768px) {
    .filter-disclosure > summary { display: none; }
    .filter-disclosure > .filter-panel { display: flex !important; }
  }
  ```
  On mobile default it closed unless the request has active filters (the view
  already computes these; pass `filters_active` into the partial and render
  `open` conditionally). No JS required.
- Show a result count on the summary line and/or above the list ("23
  events"), sourced from `page_obj.paginator.count` — this doubles as the
  `role="status"` live region from M3.

---

## Low importance

### L1. Animations ignore `prefers-reduced-motion`

`base.html:93` sets `scroll-behavior: smooth` and `base.html:424` animates
every page load (`main { animation: fadeUp 0.3s ease both; }`). Wrap both:

```css
@media (prefers-reduced-motion: no-preference) {
  html { scroll-behavior: smooth; }
  main { animation: fadeUp 0.3s ease both; }
}
```

(and remove the unconditional declarations).

### L2. Dead UI code

Confirmed unused and safe to delete (grep shows no references):

- `templates/events/my_events.html` — `MyEventsView` is now a bare redirect
  to the publisher profile (`events/views.py:551-553`).
- `templates/partials/messages.html` — `base.html` renders messages inline.
- `templates/partials/pagination.html` — `event_list_results.html` has its
  own pagination (this stale copy also uses a Tailwind `mt-6` class the
  templates otherwise never rely on).
- Orphaned CSS in `base.html`: the entire "STATUS BADGES" block
  (`.status--pending/approved/rejected`, `.badge--moderator`,
  `.badge--approve-action`, `.badge--revoke-action` — there is no moderation
  workflow), `.stat-card*`, `--star`, and the duplicate badge aliases
  (`badge--wip`, `badge--work_in_progress`, `badge--open-practice`,
  `badge--open_practice` — the model's category values are single fixed
  strings). ~40 lines of head CSS on every page.

### L3. The event form cannot express multi-day events

`EventForm` (`events/forms.py:130-147`) combines one `date` with start/end
*times*, so `end_datetime` is always the same calendar day, while the model
and the scrapers happily store multi-day events (festivals, installations).
Community publishers must fake it (one event per day or omit the end).
Suggested: add an optional `end_date` field (defaulting to `date` when blank)
next to "End time" in `event_form.html`, and validate
`end > start` on the combined datetimes. Low because the audience is mostly
single-evening events — but it's the only data the form silently cannot enter.

### L4. Ko-fi widget script loads on every page

`base.html:604-605` loads `storage.ko-fi.com/cdn/scripts/overlay-widget.js`
(plus its polling `connect-src` traffic) on every view, including login and
event submission, where a floating donation bubble competes with the task.
Suggested: include it only on visitor-facing pages (list/detail/about), or
lazy-load it on first scroll/interaction via a few lines in `kofi.js`
(`IntersectionObserver` or a `setTimeout` after `load`). This also shrinks the
third-party surface the CSP has to carve exceptions for.

---

## Suggested implementation order

1. **H1** — restores broken functionality and the intended typography; do the
   font self-hosting first since it's the most visible.
2. **H4** and **M3** — small template-only wins.
3. **H2 + H3** — the accessibility core (markup + tokens).
4. **M1, M2** — keyboard/AT depth.
5. **M4**, then L1–L4 as cleanup.
