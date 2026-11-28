WFIGS Phase 4.2 — Multi-Year Historical Toggle + Bright Solid Cartography

Purpose
-------
Replaces the single-year historical dropdown with five independent year toggle buttons so WPC forecasters can overlay any combination of the rolling five completed wildfire years during regional flash-flood / burn-scar analysis.

Frontend changes
----------------
- Historical year controls are independent toggle buttons, not a dropdown.
- Multiple historical years can be displayed simultaneously.
- Newest completed year remains selected by default.
- Each rolling historical year receives a distinct bright color.
- Current, YTD, and historical wildfire perimeter outlines are solid for easier fire isolation on busy operational maps.
- Historical status/legend report all selected years together.
- Per-year lazy loading, acreage display thresholds, current-fire duplicate suppression, and backend provenance are preserved.
- Historical chunk cache is limited per year to avoid one selected year evicting another's cached regional data.

Files to replace on main
------------------------
app.js
index.html
tools/validate_dashboard.py

No WFIGS backend workflow rerun is required. The existing 2021–2025 history products on the wfigs-data branch are reused.
