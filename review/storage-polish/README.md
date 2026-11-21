# Dashboard workflow and storage polish — 4 November 2026

The pre-maintenance inventory observed 14,999,307,193 bytes of Actions artifacts, 6,252,888,356 bytes of caches, and a 94,204,932-byte live Pages payload. GitHub reported 1,179,759 KiB for Git repository storage. These are separate storage pools; the public inventory cannot inspect account billing, bandwidth, or charges already accrued.

## Execution efficiency

Ubuntu is GitHub's temporary hosted Linux runner. Older workflows installed Ubuntu's ecCodes package as well as the Python package's bundled binary. Radar production had already been using the bundled ecCodes 2.50.0 library, while the apt copy was 2.45.0. The system installation was an inherited setup step that had become redundant. It caused delay, rather than adding files to the published repository.

The remaining nine copies of that redundant system-install step are removed. Dependency installation uses binary wheels, the working ecCodes/eccodeslib versions are explicit, and each affected workflow runs a decoder self-check. Python 3.10 retains its available 2.48.2 binary; newer runtimes use 2.50.0, with the same Python interface. CI checks binary availability and an actual synthetic GRIB encode/decode round trip on Python 3.10, 3.11 and 3.12. Meteorological calculations, map resolution and operational schedules are preserved. The RALA pip cache now uses its own dependency file instead of the unrelated generic environment.

## Persistent storage policy

- SPoRT provenance uploads contain status, source identities and the numerical index. Full PNG suites are already in the bounded publication and are no longer duplicated in every provenance artifact.
- The full current numerical history remains on the verified history-free `data/sport-lis` branch. Secondary numeric backup artifacts expire after three days; maintenance preserves the newest two. Backup cleanup requires a complete authoritative numerical index and usable H7 state.
- Pull requests retain offline science/display checks. Full SPoRT live-data retrieval and dashboard bundles are manual exports with three-day retention.
- Existing hourly GDI housekeeping waits for the producing workflow to finish, keeps the newest companion cache, and keeps the newest two forecast, Day 1, RAP and native CAM cache copies. Unrecognized namespaces, pip caches and PR caches remain protected.
- Artifact housekeeping recognizes exact producer names, confirms the original workflow and completed run, protects open-review branches, generated bundles less than an hour old and Pages staging bundles less than ten minutes old, and retains the newest two bundles per family. Only completed historical Pages staging bundles are eligible; the served site and its current snapshots are not deleted.
- Housekeeping reuses the existing four daily SPoRT production completions and offers manual dispatch. No additional cron polling is introduced. Inventory scans merge up to three bounded rescans by immutable artifact ID when uploads move pagination boundaries. Deletions are paced below secondary mutation-rate limits.
- Every maintenance run records before/after inventories and a small two-day receipt. Operating budgets are 8 billion bytes for caches, 2 billion bytes for artifacts, and 512 MiB for each published snapshot. These are local alert thresholds, not statements of the account's included GitHub allowance.

All observed operational data branches were root snapshots with no parents. GitHub controls garbage collection of unreachable Git objects; force-publishing a bounded snapshot is not an immediate server-side garbage-collection guarantee.

## Validation

Twenty-two artifact/operating-budget tests and eight cache tests pass, including protected reviews, active deployments, current backups, incomplete numerical history, namespace boundaries and age limits. The existing 59 SPoRT science/publication tests and dashboard validation also pass locally. Remote binary-install, decoder self-check and synthetic GRIB round-trip jobs pass on all three supported Python runtimes. The final production maintenance and operating-budget checks pass.

## Verified production outcome

[PR #39](https://github.com/andreworrison-cloud/wpc-hydro-dashboard/pull/39) deployed the dependency and retention changes. [PR #40](https://github.com/andreworrison-cloud/wpc-hydro-dashboard/pull/40) added bounded inventory rescans. Two initial maintenance attempts stopped before artifact deletion when concurrent uploads moved the inventory pages. The corrected [production run 41938200535](https://github.com/andreworrison-cloud/wpc-hydro-dashboard/actions/runs/41938200535) completed successfully, including all operating-budget checks.

| Storage pool | Initial follow-up inventory | After maintenance |
| --- | ---: | ---: |
| Actions artifacts | 13.97 GiB | 1.20 GiB |
| Actions caches | 5.82 GiB | 3.59 GiB |
| Published Pages files | 89.84 MiB | 89.89 MiB |
| GitHub-reported Git storage | 1.125 GiB | 1.125 GiB |

The run deleted 234 obsolete artifacts totaling 13,951,007,993 bytes (12.99 GiB). Concurrent production uploads mean the net storage change differs from the total bytes deleted. The full per-ID [cleanup receipt](cleanup_20261104.json), [immediate pre-cleanup inventory](production_before_20261104.json), and [post-cleanup inventory](after_20261104.json) are retained here. The downloaded receipt ZIP was verified against GitHub's SHA-256 digest before extracting its three JSON files.

The 344,898,904-byte SPoRT snapshot retained all 23 indexed numerical source versions. All 12 operational data branches were complete root snapshots, each below 512 MiB. Radar retained 37 frames from 18:00:39Z through 00:00:39Z, published at an observation age of 2.21 minutes. The served website remained approximately 90 MiB. Repository-level Git size is a separate GitHub-reported metric; neither artifact cleanup nor cache deletion forces immediate Git object garbage collection.

This inventory cannot certify account-wide charges, included plan allowances, billing stop-spend settings, other repositories or Pages bandwidth. The operating budgets above are explicit local safeguards, not billing guarantees. GitHub's [cache rules](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching), [Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits) and [billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions) describe the distinct pools and allowances.
