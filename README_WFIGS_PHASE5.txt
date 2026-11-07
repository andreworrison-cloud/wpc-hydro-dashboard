WFIGS Phase 5 — CONUS Seasonal Wildfire Activity Trends
========================================================

Purpose
-------
Adds two operational CONUS wildfire-activity trend graphics to the WPC Real-Time
Hydrometeorological Dashboard while preserving all Phase-4.3 perimeter behavior:

1) Weekly New Wildfire Discoveries
   - current-year line
   - rolling previous-five-completed-years median
   - historical min-max envelope

2) Cumulative YTD Wildfire Discoveries
   - current-year daily cumulative line through the last complete UTC day
   - rolling five-year median
   - historical min-max envelope

The trend tool is a dashboard utility, not a new map layer, so the registered layer
count remains 140.

Scientific definition
---------------------
The activity metric is the count of UNIQUE, DEDUPLICATED WFIGS WF incident identities
by attr_FireDiscoveryDateTime, restricted to the 48 contiguous U.S. states plus the
District of Columbia using attr_POOState.

Important: this is NOT acreage burned, burn severity, valid-polygon count, active-fire
count, or the number of polygons currently visible at a map zoom. It is intentionally
computed before geometry filtering so an unrepairable perimeter does not erase a real
fire discovery from the seasonal activity statistic.

Weekly periods are 7-day bins anchored on January 1 UTC. The incomplete current period
is not plotted against a full historical week. The current cumulative series is carried
through the last complete UTC day, avoiding a partial-day comparison bias.

Data products
-------------
YTD workflow writes:
  static/wfigs/ytd/seasonal_activity.json

Rolling-history workflow writes:
  static/wfigs/history/YYYY/seasonal_activity.json
  static/wfigs/history/seasonal_activity.json

The historical root product contains the rolling five-year weekly min/median/max and
daily cumulative min/median/max baseline. No additional cron job is required.

Existing cron-job.org cadence remains appropriate:
  Current WFIGS: every 5 minutes
  YTD WFIGS: every 6 hours  -> refreshes current-year trend data
  Rolling 5-Year History: weekly -> refreshes historical baseline

Dashboard UI
------------
Within Wildfire / Burn Scar Context, a new control appears below the historical-year
buttons:

  CONUS SEASONAL WILDFIRE ACTIVITY
  Open <current year> vs rolling 5-year activity trends

The floating trend panel contains:
  - current YTD discovery count through last complete UTC day
  - matched historical median YTD count
  - departure from median
  - Weekly New Wildfire Discoveries chart
  - Cumulative YTD Wildfire Discoveries chart
  - explicit metric/science note

Files in this patch
-------------------
app.js
index.html
fetch_wfigs_operational.py
fetch_wfigs_history.py
tools/validate_dashboard.py
tools/validate_wfigs_phase2.py
tools/validate_wfigs_history.py
tools/validate_wfigs_trends.py
.github/workflows/update_wfigs_current.yml   (unchanged workflow, included for validator completeness)
.github/workflows/update_wfigs_ytd.yml
.github/workflows/update_wfigs_history.yml
README_WFIGS_PHASE5.txt

Deployment / first build
------------------------
1. Replace/add the files above on main and commit them together.
2. Run Validate Dashboard Interface.
3. Run Update WFIGS Rolling 5-Year Wildfire History once with force_rebuild=false.
   - Processor version changes to wfigs_history_v1_2, so the five years rebuild once
     and create annual seasonal-activity files plus the rolling baseline.
4. Run Update WFIGS Year-To-Date Wildfire Perimeters once with force_rebuild=false.
   - Operational processor changes to wfigs_phase2_operational_v1_4, so YTD rebuilds
     once and creates current-year seasonal_activity.json.
5. The Current WFIGS cron run will also rebuild Current once because the shared
   operational processor version changed. Current does not feed these two trend charts.
6. Hard-refresh the dashboard and open the new seasonal-trend control.

After the first build, the existing cron-job.org schedules maintain the trend inputs;
no fourth scheduler is needed.

Validation completed before packaging
-------------------------------------
- app.js Node syntax check: PASS
- Python compilation: PASS
- workflow YAML parse: PASS
- dashboard registry: 140 total / 140 unique IDs
- direct ArcGIS calls from browser: none
- WFIGS Phase-5 trend static frontend contract: PASS
- synthetic current-year YTD seasonal activity generation: PASS
- synthetic rolling five-year historical baseline generation: PASS
- WFIGS Phase-5 seasonal activity validator: PASS
- WFIGS Phase-2 YTD validator against synthetic Phase-5 product: PASS
- WFIGS Phase-4 history validator against synthetic Phase-5 product: PASS
- zero-feature national-overview regression case: PASS

No change was made to the wildfire-perimeter colors, multi-year toggle behavior,
CONUS overview thresholds, viewport chunking, or the Current/YTD/history scheduler
cadence.
