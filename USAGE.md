# Using the dispatcher

A walkthrough of every surface, in the order a coordinator meets them.

## Signing in

Open <http://localhost:8050>. You land on `/signin`, which explains the product
and prefills the seeded coordinator credentials (the hint on the card reads
`Demo: cenius@cenius.ai / cenius`). Use **Show** to reveal the password, press
**Enter** or **Sign in** to submit, or take the **One-click demo sign-in** button.

Wrong credentials produce exactly one message — "Those credentials did not match.
Check the demo hint below." — whether the account exists or not. Ten failed
attempts from one address within fifteen minutes return `429` and a wait
message. **Sign out** in the app header clears the session server-side.

## Reports tab

The default tab. From top to bottom:

- **KPI strip** — open calls, dispatched, in transit, rehomed, lost, not found.
- **Swarm report triage** — status filter chips (`All reports`, `New`, `Assigned`,
  `Collected`, `Rehomed`, `Lost`, `Not found`) each carrying a live count. An
  urgency filter and a free-text search sit underneath. The table lists created
  time, caller, cluster size, status, urgency, **Logged by** and **Assigned
  volunteer** (blank unless the report has an active dispatch). Click any row —
  or its caller button — to select it.
- **Report detail** — every field of the selected call, including the logger and
  the active collector.
- **Swarm map** — one marker per report, coloured from the same canonical status
  list. `Not found` has its own grey legend entry. Click a marker to select the
  report. Straight-line geography on bundled data: no tiles, no token.
- **Log a swarm call** — the intake form. Caller name, phone (7–15 digits),
  urgency, cluster size, the named site picker and notes. Every choice field is a
  real browser `<select>` with real option values, prefilled with the common case
  so the form is completable as it stands. Enter submits from any text field.
  Saving adds the report at the top of the table as `new`, with you as the
  logger, and shows a confirmation. Submitting an identical call twice within a
  few seconds creates one row, not two.

Empty, loading and error states all render in place: filters that match nothing
show "No reports match these filters - clear a filter or log a new report.",
regions show a spinner while a callback is in flight, and a failed query shows a
red banner with a **Retry** button that keeps your active filter.

## Dispatch tab

- **Swarm calls** — pick a report. Options are labelled `Needs dispatch · …` for
  reports with no active dispatch and `Assigned · …` for those already covered,
  so an active dispatch stays reachable. The panel below restates the caller,
  site, cluster, urgency and logger.
- **Ranked collectors** — available beekeepers whose coverage radius reaches the
  site, nearest first, each row showing name, skills, coverage radius, phone and
  distance. Confirm a row to open the confirmation panel.
- **Dispatch actions** — restates the report, collector, distance and the time of
  confirmation. **Confirm dispatch** creates the dispatch, moves the report to
  `assigned` and records you as the confirming coordinator. **Back** cancels.

Once a report has an active dispatch the candidate rows are replaced by
"Already assigned to <collector> since <time>". **Reassign** re-enables the
candidate list for an explicit reassignment; **Decline** and **Cancel dispatch**
close the dispatch and return the report to `new` so it reappears in the
selector. Every one of these actions writes to the database and reports back
inline — including the refusal when a report already has an active dispatch.

- **Dispatch history** — every attempt on the selected report, including closed
  `declined`, `cancelled` and `reassigned` rows.

## Volunteers tab

The roster table shows each collector's phone, home coordinates, coverage radius,
skills, an availability toggle and the last-updated time. Flipping the toggle
writes immediately; the Dispatch ranking stops offering that collector at once,
and the change survives a refresh.

The add-collector form validates name, phone (7–15 digits), home location (from
the site list, so coordinates stay consistent) and a coverage radius between 1
and 50 km — entering 90 km explains the limit and creates nothing. An empty
roster shows "No volunteers yet - add your first collector before dispatching."
The coverage chart plots every collector's radius, accent bars being the ones
available right now.

## Outcomes tab

- **Pipeline funnel** — `new → assigned → collected → rehomed`.
- **Terminal buckets** — `lost` and `not found` as two separate bars, so neither
  inflates the funnel. A report that ends "not found" is counted only there.
- **Record an outcome** — pick the report, see the collector taken from its
  active dispatch, choose the result, optionally give the collection date, the
  actual cluster size, the hive/box and notes. Choosing **Rehomed** makes the
  destination mandatory and rejects the save without one. Saving moves the report
  to the matching status, closes the dispatch as completed and updates the chips,
  the map and the funnel.
- **Outcome history for the selected report** and the **season outcome log**.

With no outcomes recorded the funnel shows "No outcomes recorded yet - record a
collection to start the pipeline." and a failed query shows a banner with
**Retry**.

## Keyboard and accessibility

- Every control is a real `<button>`, `<a>` or native form element; nothing is a
  clickable `<div>`.
- Required choices are real `<select>` elements with real option values, never
  custom toggles or div-based pickers.
- **Enter** submits the nearest form from any text field.
- Focus is always visible (`:focus-visible` bloom), every input has a real label,
  every error message has `role="alert"`, and all animation is disabled under
  `prefers-reduced-motion`.

## Timestamps

Stored as UTC ISO-8601 and rendered in your browser's local timezone by
`static/app-behaviour.js`; the server-rendered fallback reads as UTC.
