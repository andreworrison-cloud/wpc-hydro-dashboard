# MRMS RALA timeliness repair — 4 November 2026

The successful 22:37 UTC workflow spent nearly thirteen minutes installing Ubuntu system packages before retrieving radar. Its apt transfer alone took 12 minutes 58 seconds (58.1 MB at 74.7 kB/s). Subsequent five-minute dispatches waited behind this run. The radar build itself took about five seconds and the winter supplement about seven seconds. This can push a previously published ten-minute sample beyond the browser's twenty-minute observation-age limit while GitHub ultimately reports success.

The installed Python wheels already provided ecCodes 2.50.0, which was the decoder reported by production; the apt copy was 2.45.0. The workflow now installs the same working Python/binary wheels directly, with a three-minute dependency-step budget. ECMWF documents the bundled binary in its [official installation instructions](https://github.com/ecmwf/eccodes-python#installation). The existing cron-job.org dispatch and history-free data branch remain the production path.

The build now records age using its completion clock. Immediately before publication, the full package is validated again against the twenty-minute observation-age limit, after optional winter processing. A `publication_validation` receipt records the check. Neither a successful build nor a newer generation timestamp can make an old observation fresh.

The browser now bounds metadata/body requests and image preloads, including image decode, so a stuck operation cannot indefinitely hold the refresh lock. Failed initial image loading leaves the manifest version retryable. Failed polls also re-evaluate the age of the retained observation and hide expired data using the existing twenty-minute cutoff.

The empty Experimental Models menu placeholder has been removed. Existing experimental products remain in their populated product families.

The [investigation record](investigation_20261104.json) contains source/run timestamps. Regression checks cover four publication-age cases and six browser refresh/recovery scenarios, plus existing radar playback, archive selection, winter classification and dashboard checks. Reflectivity values, palette, rendering resolution, ten-minute sampling and 2/4/6-hour playback are preserved. No new data archive or periodic artifact upload is introduced.
