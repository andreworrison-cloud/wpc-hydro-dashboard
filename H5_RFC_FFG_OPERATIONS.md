# Official RFC FFG production operations

The dashboard uses RFC-issued 1-, 3-, and 6-hour numerical FFG distributed by WPC. Dashboard colors and Web Mercator rendering are derived displays; they are not original RFC map images. Native numerical data and provenance are retained separately.

## Publication

`Publish Official RFC FFG` runs on main, via manual dispatch or changes to its production code. It restores and atomically publishes `data/rfc-ffg`. Review publishing remains isolated on `data/rfc-ffg-review`. The dashboard reads the production public metadata pointer. A source failure retains the last valid generation; a product expires at the earlier of snapshot + 3 hours and reference cycle + 9 hours. Expired layers are hidden. Source snapshot, GRIB reference cycle, and retrieval time remain separate; individual RFC issue times are unavailable.

## cron-job.org configuration

Create one enabled job named `WPC official RFC FFG hourly`, timezone UTC, at minute 50 every hour (cron expression `50 * * * *`). No GitHub cron schedule duplicates this trigger.

- URL: `https://api.github.com/repos/andreworrison-cloud/wpc-hydro-dashboard/actions/workflows/publish_rfc_ffg.yml/dispatches`
- Method: POST
- Body: `{"ref":"main"}`
- Header `Accept`: `application/vnd.github+json`
- Header `Content-Type`: `application/json`
- Header `X-GitHub-Api-Version`: `2026-03-10`
- Header `Authorization`: `Bearer <fine-grained GitHub token>`

Create the token for this repository only, with Actions read/write permission and an appropriate expiration. Enter it directly in the scheduler; never commit it or paste it into chat. The workflow's own GitHub token supplies Contents write permission for publication. Test the scheduler request, then verify the corresponding Actions run and metadata update. HTTP success confirms dispatch acceptance, not ingest completion. External scheduling does not eliminate GitHub runner queue delays.

## Operational checks and recovery

Check the Actions run conclusion and `data/rfc-ffg/public/metadata.json`: state, usable, last_attempt, snapshot_time, reference_time, coverage, and freshness. Inspect 1-, 3-, and 6-hour layers and legends in the live dashboard. Source outages should report retention or expiration; they must not silently substitute older newly discovered input. Enable scheduler failure notifications, and monitor Actions failures separately.

To pause updates, disable the cron-job.org job. To retry, manually run `Publish Official RFC FFG` on main. Keep the last validated data branch intact. Roll back application changes through a reviewed revert rather than replacing main or rewriting data history.

The publisher retains 48 generation directories at the branch tip. Git history still retains older binary objects: this is not a bounded archive. Monitor repository growth and migrate scientific archives to object storage before long-term accumulation becomes excessive. Current coverage checks compare an established observed baseline; an independent expected-land coverage mask remains outstanding.
