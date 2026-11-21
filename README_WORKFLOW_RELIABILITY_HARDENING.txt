WPC Hydro Dashboard — Workflow Reliability Hardening v1
=======================================================

Purpose
-------
This package is a targeted workflow-reliability pass after GitHub-hosted Ubuntu
runners began failing `apt-get update` on an unrelated Google Chrome repository
with a Hash Sum mismatch.

This package DOES NOT change any meteorological/hydrologic algorithms, source
selection, rendering, schedules, dashboard layers, or scientific thresholds.

Already patched separately (do not replace again from this package)
---------------------------------------------------------------
- update_cam.yml
- update_ero_cam.yml
- update_rap.yml

Production/operational workflows patched here
---------------------------------------------
- update_mrms_rala.yml
  * disable unused Chrome apt source
  * clean apt list state
  * Acquire::Retries=3
  * libeccodes0 --no-install-recommends

- update_mrms_flash_24h.yml
  * same apt hardening
  * preserve its existing three-attempt publication loop, but guard pull/rebase
    failures so bash does not terminate before the next retry

- fetch_nldas_rsm.yml
  * same apt hardening

- update_lightningcast.yml
  * no apt exposure; instead hardens main-branch publication with three guarded
    pull/rebase/push attempts because concurrent dashboard writers can move main

- update_hrrr_tle.yml
  * no apt exposure; same guarded main-branch publication retry

Diagnostic workflows patched here
---------------------------------
- diagnostic_mrms_rala.yml
- diagnose_mrms_ffd.yml
- diagnose_mrms_ffd_24h.yml
- diagnose_mrms_crest_24h.yml

These diagnostics also called apt-get directly and could hit the same Chrome
repository failure even though they are not operational feeds.

No patch needed for the Chrome apt issue
----------------------------------------
The audited current workflow families below do not call apt-get:
- WFIGS Current / YTD / rolling-history workflows
- update_data.yml (WPC/FFD)
- fetch_nwm.yml
- fetch_sport.yml
- update_glm_mosaic.yml and the GLM diagnostic/Option-A workflows
- update_lightningcast.yml (patched only for git race resilience)
- update_hrrr_tle.yml (patched only for git race resilience)
- validate_dashboard.yml

Important limitation
--------------------
This hardening removes one class of seemingly random failures. It cannot prevent
failures caused by upstream NOAA/NASA/NIFC data latency, HTTP timeouts, GitHub
service outages, API throttling, genuinely missing model cycles, scientific
validation failures, or PyPI/network interruptions.

Install
-------
Copy the files in .github/workflows/ over the same repository paths and commit.
No Python/data files need to be changed for this package.

Recommended validation
----------------------
1. Let the RAP patch you are committing now complete first.
2. Commit this remaining-workflow package.
3. Manually test these three operational jobs first:
   - Update MRMS RALA Direct NOAA Loop
   - Update MRMS FLASH 24-Hour Maxima
   - Fetch NLDAS-2 Noah Relative Soil Moisture
4. Then manually test LightningCast and HRRR-TLE once if convenient.
5. Diagnostic workflows can simply remain hardened for the next time they are used.
