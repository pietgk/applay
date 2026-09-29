# Jobs-list refresh: scroll/focus options for the server-rendered UI

Research for [wayfinder ticket #31](https://github.com/pietgk/apply/issues/31), part of the
[application communication & UI rework map](https://github.com/pietgk/apply/issues/26).

**Status:** Option 1 steps 1–2 landed with the shared two-pane shell (#40): rail anchors via
`local_ui.anchor_id` / `anchored_url`, `jobs_skip` PRG-redirects to the anchored URL, and the
rail scroller is `.pane-rail`. The server-rendered filters and sorting in #44 retain that
place-keeping without htmx, which is now an optional enhancement rather than a screen-delivery
dependency. Current place-keeping and shell-adoption contract: `AGENTS.md` (Local UI) and
`templates/local_ui/two_pane.html`. The code-grounding section below is the pre-change snapshot
that motivated the choice. Moving `acknowledge` off GET remains open.

## Question

Clicking a job in the `/jobs` UI re-renders the whole page and throws the jobs list back to the
top (lost scroll position and focus). What are the realistic fixes — URL fragments + redirect
anchors, htmx/Turbo-style partial swaps, or a client-side SPA rewrite — what does each cost given
the simple-files philosophy, and does the choice constrain the rest of the map (event timeline,
richer job cards, activity-sorted list, status dropdown, LLM-chat integration) or is it a
swappable detail?

## Where the problem actually lives (code grounding)

All claims below are against `src/apply/local_ui.py` and `templates/local_ui/`:

- Every rail item is a plain `<a href>` to `GET /jobs/<job_id>` (`jobs_detail`,
  `local_ui.py:520`), which calls `_render_jobs` → `render_template("jobs.html", …)` — a full
  document reload on every click.
- The jobs list is a **nested scroll container**, not the page scroller:
  `.jobs-rail { max-height: 74vh; overflow: auto; }` (`static/local_ui.css:82`). On a fresh
  navigation the new document's rail starts at offset 0 — no browser restores a subscroller on a
  *forward* navigation, so the scroll loss is structural, not a missing setting.
- Focus loss is concrete: the skip form's `reason` text input (`jobs.html:126`) is destroyed on
  every re-render, including the 400 error re-render in `jobs_skip` (`local_ui.py:549`).

Two hygiene findings that change the framing, independent of technology choice:

1. **`jobs_skip` has no Post/Redirect/Get.** It answers the POST with a 200 full re-render
   (`local_ui.py:573`), so browser refresh re-submits the skip and back-button triggers the
   form-resubmission warning. `jobs_interested` does redirect (`local_ui.py:547`). Any option
   chosen should fix this first.
2. **`jobs_detail` is a GET with a write side effect** — it calls `catalog.acknowledge`
   (`local_ui.py:527`), clearing the "New" badge. Every technique below that re-issues or
   prefetches GETs (browser prefetch, htmx boost, Turbo previews, SPA refetch-on-focus) will
   silently acknowledge jobs. Acknowledge is effectively idempotent-per-job so nothing breaks
   today, but it rules out aggressive prefetching and is worth moving to an explicit POST (or a
   beacon) whenever the route is next touched.

## Option 1 — URL fragments + PRG anchors (no dependencies)

Mechanics: give each rail item `id="job-{{ job_id }}"`, make the link
`{{ url_for('jobs_detail', job_id=…) }}#job-{{ job_id }}`, and make the skip POST redirect to the
same anchored URL (proper PRG). On load, fragment navigation scrolls the target into view — and
the scroll-into-view algorithm **scrolls ancestor scroll containers**, so the nested `.jobs-rail`
is scrolled until the clicked item is visible
([MDN: scrollIntoView "scrolls the element's ancestor containers"](https://developer.mozilla.org/en-US/docs/Web/API/Element/scrollIntoView);
fragment navigation invokes the same behavior per the
[HTML spec's "scroll to the fragment"](https://html.spec.whatwg.org/multipage/browsing-the-web.html#scroll-to-the-fragid)).

Supporting pieces:

- [`scroll-margin-top`](https://developer.mozilla.org/en-US/docs/Web/CSS/scroll-margin-top)
  (Baseline widely available since 2021) adds an outset when the item is scrolled into view, so
  the selected row lands below the sticky-ish group header instead of flush against the rail edge.
- [`:target`](https://developer.mozilla.org/en-US/docs/Web/CSS/:target) could style the selected
  row from the fragment alone, but the server already renders a `.sel` class (`jobs.html:28`), so
  it is redundant here. (Caveat for later: `:target` does not update on
  `pushState`/`replaceState`, so it combines poorly with htmx/Turbo URL pushing.)
- [`history.scrollRestoration`](https://developer.mozilla.org/en-US/docs/Web/API/History/scrollRestoration)
  defaults to `"auto"`, which already restores scroll on **back/forward** — it does nothing for
  forward link clicks, so it is not a fix by itself, only a reason not to break the back button.

What it fixes: the clicked item is always visible in the rail after the reload (near its previous
position — "item in view", not pixel-exact offset), page refresh after skip stops re-submitting,
and back/forward keep working natively. What it does not fix: focus and unsubmitted form state
are still lost (it is still a full reload), and the detail pane still flashes.

Cost: zero dependencies, zero JS, ~10 lines across `jobs.html` and the two handlers. Fully in the
spirit of the simple-files philosophy.

## Option 2 — htmx / Turbo partial swaps

### htmx

htmx is a single dependency-free file, "~16k min.gz'd", installable as one script tag with no
build step ([htmx.org](https://htmx.org/)) — it can be vendored into
`templates/local_ui/static/` next to `local_ui.css`, which fits the repo's philosophy (one
ordinary file, no toolchain).

Two escalation levels:

1. **`hx-boost` on `<body>`** — converts existing links/forms to AJAX body swaps and "degrades
   gracefully if javascript is not enabled"
   ([docs](https://htmx.org/docs/#boosting), [hx-boost](https://htmx.org/attributes/hx-boost/)).
   Caveats: boosted navigation defaults to `show:top` (scroll to top!), so you must set
   `hx-swap="innerHTML show:none"` to keep scroll ([hx-swap](https://htmx.org/attributes/hx-swap/));
   and its history feature snapshots pages into a localStorage cache
   ([docs: history](https://htmx.org/docs/#history)), which interacts with the
   `acknowledge`-on-GET side effect on cache misses. Boost alone is a mediocre fit here.
2. **Targeted swap (the real fix)** — make each rail item an `hx-get` that targets only the
   detail pane (`hx-target="#jobs-detail" hx-select="#jobs-detail" hx-push-url="true"`), and the
   skip/interested forms likewise. The rail DOM is then *never re-rendered on selection*, so its
   scroll position and any focused input survive trivially — nothing to restore because nothing
   was destroyed. htmx additionally "preserves focus between requests for inputs that have a
   defined id attribute" even inside swapped regions
   ([hx-swap: focus-scroll](https://htmx.org/attributes/hx-swap/)).
   [Out-of-band swaps](https://htmx.org/docs/#oob_swaps) (`hx-swap-oob` on elements with ids) let
   one response also move the `.sel` highlight and update group counts in the untouched rail.
   [Morph swaps (idiomorph)](https://htmx.org/docs/#morphing) exist as an extension if a
   whole-page refresh ever needs to preserve "focus, video state, etc." by merging instead of
   replacing — not needed for this fix.

Server-side cost: nearly none for the `hx-select` variant (routes keep returning the full page;
htmx extracts the pane). The cleaner end-state is splitting `jobs.html` into a rail partial and a
detail partial via `{% include %}` and returning just the partial when the `HX-Request` header is
present — a ~30-line refactor of `_render_jobs`. Responses stay plain HTML, so the existing
Flask-test-client tests keep asserting against rendered markup.

### Turbo, for comparison

Turbo Drive intercepts links/forms and swaps the body; on ordinary "application visits" it
"will scroll to the top of the page" unless the URL has an anchor, and only "restoration visits"
(back/forward) restore saved scroll
([Turbo handbook: Drive](https://turbo.hotwired.dev/handbook/drive)) — so Drive alone does not
fix forward-click scroll loss any better than fragments do. Turbo 8 page refreshes add idiomorph
morphing plus `<meta name="turbo-refresh-scroll" content="preserve">` to keep scroll, and
`data-turbo-permanent` to exempt elements from updates
([Turbo handbook: page refreshes](https://turbo.hotwired.dev/handbook/page_refreshes)). That is
capable, but Turbo is an ES-module bundle shaped around Rails conventions (frames, streams), and
everything it offers here is matched by htmx targeted swaps + the idiomorph extension with a
smaller conceptual surface. Not recommended for this repo.

## Option 3 — client-side SPA rewrite (React/Vue + JSON API)

What it would take: a JSON API layer mirroring `jobs_page_context`/`group_records_for_ui`
(`local_ui.py:360–467`), a node/vite build toolchain, a second codebase for components, and
client-side re-implementation of grouping/sorting/triage presentation that today lives in tested
Python. Scroll and focus are preserved "for free" because the list component never unmounts — but
that exact benefit is what an htmx targeted swap gives for one vendored file and zero build step.

The deeper mismatch: this app's state *is* the files (`job.md`, `meta.yaml`, `cv-*.md`,
`data/catalog/`), mutated by CLI commands and chat-driven agents, and the UI is a thin viewer
that re-reads them per request. An SPA holds a client-side copy of that state and must invalidate
it when files change underneath (chat marks a job applied, a fetch adds jobs) — polling or
push machinery that server-rendering gets for free by re-reading on every request. For a local
single-user tool this is all cost and no capability. Rejected.

## Does the UI technology choice matter to the wider map?

Checked against each planned screen:

| Map item | Fragments/PRG | htmx partials | SPA |
| --- | --- | --- | --- |
| Event-timeline screen, collapsible entries | fine (`<details>` is server-renderable, no JS) | fine; lazy-load long timelines if wanted | forces the event model into a JSON API first |
| Richer job cards: sort/filter | fine; filtering and sorting live server-side (`filter_job_feed` / `sort_job_feed`) and filters are query params | same, minus full-page flash | duplicates catalog logic in JS or makes it chatty |
| Activity-sorted applications list | fine | fine | same duplication |
| Status dropdown | form POST + PRG works; clunky but correct | natural: inline `hx-post`, swap the badge OOB | natural, but drags the API along |
| LLM-chat integration | The standing decision (see the [email-capture note](2026-07-22-email-capture-options.md)) is that **interaction lives in chat and the UI shows recorded state**. Chat/agents write files; a server-rendered UI reflects them on next request with zero machinery. | same — partial refresh of a pane is even pleasant here | worst fit: client state goes stale whenever chat writes files; needs refetch/push plumbing |

Conclusion: **between fragments and htmx the choice is a genuinely swappable detail** — both keep
rendering in Jinja, state in files, and logic in Python; every map item stays "a template plus a
route". They even compose: the fragment/PRG fix is not thrown away by adopting htmx later (it is
exactly the no-JS fallback that `hx-boost`-style progressive enhancement degrades to). **The SPA
is the one non-swappable choice** — it moves rendering and state ownership client-side, imposes a
JSON API contract on the file model, and duplicates grouping/triage logic; that is a one-way door
the map does not need. So the technology choice matters only as a door-closing question, and only
the SPA closes doors.

## Recommendation

**Keep fragments + PRG as the current contract (landed in #40 and retained by #44); consider
htmx targeted swaps if full-page reloads become a material usability problem; no SPA, no Turbo.**

Concretely, in order:

1. ~~Add `id="job-<id>"` to rail items, anchor the detail links (`…#job-<id>`), add
   `scroll-margin` — the clicked job stays in view in the rail after every click.~~ **Done in #40**
   (`anchor_id` / `anchored_url`, `.rail-item { scroll-margin-block }`).
2. ~~Fix `jobs_skip` to redirect (PRG) to the anchored URL instead of 200-re-rendering, so refresh
   stops re-submitting skips.~~ **Done in #40.**
3. If full-page reloads become a material usability problem, vendor `htmx.min.js` into `static/`,
   split `jobs.html` into rail + detail partials, and swap only the pane that changed
   (`hx-get`/`hx-target`, OOB swap for the rail highlight; target `.pane-detail`). Scroll and focus
   then survive because the rail is simply never destroyed.
4. Whenever `jobs_detail` is next touched, move `catalog.acknowledge` off the GET path (explicit
   POST or fire-and-forget beacon) so partial-swap/prefetch techniques can't mark jobs seen as a
   side effect.

## Sources

- [MDN — `Element.scrollIntoView()`](https://developer.mozilla.org/en-US/docs/Web/API/Element/scrollIntoView) (ancestor scroll containers are scrolled)
- [HTML Standard — scroll to the fragment](https://html.spec.whatwg.org/multipage/browsing-the-web.html#scroll-to-the-fragid)
- [MDN — `history.scrollRestoration`](https://developer.mozilla.org/en-US/docs/Web/API/History/scrollRestoration)
- [MDN — `scroll-margin-top`](https://developer.mozilla.org/en-US/docs/Web/CSS/scroll-margin-top)
- [MDN — `:target`](https://developer.mozilla.org/en-US/docs/Web/CSS/:target)
- [htmx — homepage (size/dependencies)](https://htmx.org/), [docs: boosting, history, OOB swaps, morphing](https://htmx.org/docs/), [`hx-boost`](https://htmx.org/attributes/hx-boost/), [`hx-swap`](https://htmx.org/attributes/hx-swap/)
- [Turbo handbook — Drive](https://turbo.hotwired.dev/handbook/drive), [Page refreshes with morphing](https://turbo.hotwired.dev/handbook/page_refreshes)
