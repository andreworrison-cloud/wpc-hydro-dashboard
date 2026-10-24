WPC Hydrometeorological Dashboard — WFIGS Phase 4.1
Historical Year Selector Visibility Fix
=========================================================

Purpose
-------
Phase 4.0 successfully built the rolling 2021–2025 WFIGS archive, but the
historical-year dropdown was appended at the bottom of the Wildfire / Burn Scar
Context section rather than visually attached to the Historical Wildfire
Perimeters row. This small frontend-only patch makes the year selection explicit.

Replace on main
---------------
  app.js
  index.html
  tools/validate_dashboard.py

No backend/workflow/data-branch changes are required. Do not rerun the historical
archive builder just for this patch.

Changes
-------
* The Historical fire year dropdown is rendered immediately beneath the
  NIFC/WFIGS Historical Wildfire Perimeters row.
* The control has a slightly stronger amber outline/background so it reads as an
  actionable control rather than metadata.
* The historical layer description shows the currently selected year.
* Changing the dropdown updates that description immediately.
* index.html cache token advances to history-v1-1-year-selector.
* validator checks the Phase 4.1 selector placement/sync contract.

Recommended validation
----------------------
1. Replace the three files and commit.
2. Run Actions -> Validate Dashboard Interface.
3. Hard-refresh the dashboard.
4. Open Wildfire / Burn Scar Context.
5. Confirm the selector appears directly below Historical Wildfire Perimeters.
6. Select 2025, 2023, and 2021 while the historical layer is active and confirm
   old-year polygons clear before the selected year's viewport chunks render.
