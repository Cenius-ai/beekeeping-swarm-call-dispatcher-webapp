# Five-minute demo walkthrough

Everything here runs offline against the seeded database.

## Before you start

```bash
bash install.sh
python3 app.py
```

Open <http://localhost:8050>. You should be bounced to `/signin`.

## 1. Sign in (30 seconds)

- The card prefills `cenius@cenius.ai` / `cenius` and states the same hint.
- Try `Show`, then press **Sign in**. You land on `/app/?tab=reports`.
- The header shows **Dana Whitfield · Coordinator** and the **Hotline live**
  indicator pulses.

*What to point at:* the guard. Log out, then open `/app/` directly — you are
returned to the sign-in screen, and `curl -X POST /app/_dash-update-component`
answers `401` and writes nothing.

## 2. Reports: log a swarm call (60 seconds)

1. In **Log a swarm call**, type a caller name and a phone like `07700 900123`.
2. Leave urgency on **Normal**, pick a cluster-size bucket, choose a site
   (e.g. *Fishponds Hive Yard*) and add a note.
3. Press **Log swarm call**.

The report appears at the top of the triage table as **New**, its KPI counts
move, the marker shows on the map in amber, and the row's *Logged by* column
names you.

*What to point at:* the failed-validation path — clear the name and type `123`
as the phone, submit, and watch the inline message while your other values stay
put. Submit the same call twice quickly: one row, not two.

## 3. Triage (30 seconds)

- Click the **Not found** chip: the table narrows to reports that ended that way,
  and the count on the chip stays visible.
- Click a row: the **Report detail** panel fills in for that report, on the right.
- Click a marker on the map: the same panel follows your click, and the table row
  stays highlighted.

*What to point at:* search for something that cannot match ("zzzz") to see the
"No reports match these filters" copy, then clear the search.

## 4. Dispatch a collector (90 seconds)

1. Move to the **Dispatch** tab. The selector already points at the newest call
   that needs a collector.
2. **Ranked collectors** lists available beekeepers, nearest first, with their
   coverage radius and phone.
3. Press **Confirm dispatch** on the first row, read the confirmation panel
   (report, collector, distance, time), then press **Confirm dispatch** again.
4. Go back to **Reports**: that report is now **Assigned** and its *Assigned
   volunteer* column names the collector. Its map marker is violet.

*What to point at:*

- Press confirm twice — the second attempt is refused with an inline error and
  the report keeps exactly one active dispatch.
- **Decline**, then **Cancel dispatch** on a fresh dispatch: both return the
  report to **New** and it reappears in the selector.
- **Reassign** to a different collector: the old dispatch stays in the history
  table as `reassigned`, and the *Assigned volunteer* column shows only the new
  one.

## 5. Volunteers (30 seconds)

- Flip a collector's availability toggle. The row updates instantly and survives
  a page refresh.
- Return to **Dispatch** and re-rank: that collector is gone from the candidate
  list.
- In the add form, enter a coverage radius of `90`. The form explains the 1–50 km
  limit and adds nothing.

## 6. Outcomes and the funnel (60 seconds)

1. Move to the **Outcomes** tab. The funnel shows `new → assigned → collected →
   rehomed`, and **Lost** and **Not found** sit beside it as their own bars.
2. Record an outcome against the report you just dispatched: choose
   **Rehomed — hived at an apiary**, give a cluster size and a hive/box, then
   pick a destination such as *Avon Valley Apiary*. Save.
3. The confirmation names the new status; the report's chip, map marker and
   funnel bucket all followed.

*What to point at:*

- Choose **Rehomed** and leave the destination empty — the save is blocked and
  the reason appears under the field.
- Choose **Not found** on another report: it becomes its own status with its own
  chip and its own grey marker colour, counted only in the *Not found* bar.

## 7. Reload (15 seconds)

Press `F5` anywhere. The URL keeps you on the same tab (`?tab=outcomes`), the
session still holds, and every record you created is still there — it lives in
`data.db`, not in memory.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Address already in use` | Another `python3 app.py` is still running; stop it first |
| Blank page after sign-in | Confirm `/static/theme.css` and `/static/app-behaviour.js` return `200` |
| Empty tables | Run `python3 -m seed` — it is idempotent and will not duplicate data |
