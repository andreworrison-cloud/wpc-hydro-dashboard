WFIGS Phase 5.1 — Seasonal Wildfire Activity Curve Endpoint + Chart Polish
==========================================================================

Purpose
-------
Fix the Phase-5 chart behavior where missing future current-year values were
coerced by JavaScript from null to numeric zero. That caused both 2026 orange
curves to plunge to zero and continue across the unobserved remainder of the
year.

Files to replace on main
------------------------
- app.js
- index.html
- tools/validate_dashboard.py

No WFIGS backend/workflow files changed.
No Current, YTD, or Rolling History rebuild is required for this patch.
The existing seasonal_activity.json products are correct and are reused.

Behavior changes
----------------
1. Missing/null/blank current-year chart values remain missing rather than
   being converted to 0.
2. Weekly orange line ends at the last completed Jan-1-anchored 7-day period.
3. Cumulative orange line ends at the last complete UTC day.
4. Historical median and min-max envelope continue through the rest of the
   calendar year for context.
5. Each current-year curve now has a subtle vertical endpoint guide, an orange
   endpoint dot, and a compact endpoint date/period label.
6. Chart notes explicitly state that incomplete/future current-year dates are
   intentionally unplotted.
7. X-axis year length is leap-year aware.
8. Cache-busting token advanced to wfigs-seasonal-trends-v1-1.

Validation performed before packaging
-------------------------------------
- node --check app.js: PASS
- python -m py_compile tools/validate_dashboard.py: PASS
- Null-aware curve endpoint unit test: PASS
  * null / undefined / blank values are excluded from orange polyline
  * numeric zero remains a legitimate plotted value
  * 2026 day 251 resolves to Sep 8
- Static contract checks for endpoint-fix fragments and cache token: PASS

Note on full dashboard validator
--------------------------------
This patch package intentionally contains only the three replacement frontend
files. The complete tools/validate_dashboard.py also reads style.css and other
repo files that are not duplicated here. Run the normal GitHub
"Validate Dashboard Interface" workflow after committing these three files.

Expected live result
--------------------
For the current 2026 example shown during development:
- Cumulative 2026 line should stop at the Sep 8 endpoint rather than falling to
  zero after Sep 8.
- Weekly 2026 line should stop at the last fully completed 7-day period rather
  than continuing at zero through December.
- Historical median/range should continue through December.
