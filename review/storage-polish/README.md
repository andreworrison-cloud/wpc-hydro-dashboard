# Dashboard workflow and storage polish — 4 November 2026

The pre-maintenance inventory observed 14,999,307,193 bytes of Actions artifacts, 6,252,888,356 bytes of caches, and a 94,204,932-byte live Pages payload. GitHub reported 1,179,759 KiB for Git repository storage. These are separate storage pools; the public inventory cannot inspect account billing, bandwidth, or charges already accrued.

## Execution efficiency

Ubuntu is GitHub's temporary hosted Linux runner. Older workflows installed Ubuntu's ecCodes package as well as the Python package's bundled binary. Production had already been using the bundled ecCodes 2.50.0 library, while the apt copy was 2.45.0. The system installation was an inherited setup step that had become redundant. It caused delay, rather than adding files to the published repository.

The remaining nine copies of that redundant system-install step are removed. Dependency installation uses binary wheels, the working ecCodes/eccodeslib versions are explicit, and each affected workflow runs a decoder self-check. CI checks binary availability and an actual synthetic GRIB encode/decode round trip on Python 3.10, 3.11 and 3.12. Meteorological calculations, map resolution and operational schedules are preserved. The RALA pip cache now uses its own dependency file instead of the unrelated generic environment.

## Persistent storage policy

- SPoRT provenance uploads contain status, source identities and the numerical index. Full PNG suites are already in the bounded publication and are no longer duplicated in every provenance artifact.
- The full current numerical history remains on the verified history-free `data/sport-lis` branch. Secondary numeric backup artifacts expire after three days; maintenance preserves the newest two. Backup cleanup requires a complete authoritative numerical index and usable H7 state.
- Pull requests retain offline science/display checks. Full SPoRT live-data retrieval and dashboard bundles are manual exports with three-day retention.
- Existing hourly GDI housekeeping waits for the producing workflow to finish, keeps the newest companion cache, and keeps the newest two forecast and Day 1 cache copies. Unrecognized namespaces, pip caches and PR caches remain protected.
- Artifact housekeeping recognizes exact producer names, confirms the original workflow and completed run, protects open-review branches and artifacts less than an hour old, and retains the newest two bundles per family. Only completed historical Pages staging bundles are eligible; the served site and its current snapshots are not deleted.
- Housekeeping reuses the existing four daily SPoRT production completions and offers manual dispatch. No additional cron polling is introduced. Deletions are paced below secondary mutation-rate limits.
- Every maintenance run records before/after inventories and a small two-day receipt. Operating budgets are 8 billion bytes for caches, 2 billion bytes for artifacts, and 512 MiB for each published snapshot. These are local alert thresholds, not statements of the account's included GitHub allowance.

All observed operational data branches were root snapshots with no parents. GitHub controls garbage collection of unreachable Git objects; force-publishing a bounded snapshot is not an immediate server-side garbage-collection guarantee.

## Validation

Twenty artifact/operating-budget tests and seven cache tests pass, including protected reviews, active deployments, current backups, incomplete numerical history, namespace boundaries and age limits. The existing 59 SPoRT science/publication tests and dashboard validation also pass locally. Remote decoder checks and the first production maintenance receipt are recorded after deployment.
