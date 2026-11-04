# Legacy FFG artifact cleanup — completed

The fixed cleanup proposal was executed following the user's request to continue the dashboard work and needed GitHub cleanup. Production verification completed on 4 November 2026 at 20:55 UTC.

- Permanently deleted: **335 fixed artifact IDs**, totaling **108,074,053,606 bytes (100.652 GiB)**. Every candidate passed metadata and repository/run checks before the first deletion; the final inventory confirmed all 335 IDs were absent.
- Scope: full `rfc-ffg-ingest` Actions artifacts larger than 100 MiB, from main-branch runs before the compact-upload deployment on 4 November 2026 at 19:49:45 UTC.
- Retained and read-back verified: newest full legacy package `rfc-ffg-ingest-41891094298-1` (artifact 13354200688, created 2026-11-04T18:51:35Z).
- Preserved: compact provenance uploads, published current/prior operational FFG data, source code, data branches and unrelated scientific/review artifacts. Other artifacts retain their original expiry dates.
- The one-time deletion workflow was removed after successful verification. The helper defaults to read-only preflight and accepts only the original plan checksum and fixed IDs.

The original [fixed cleanup plan](legacy_ffg_cleanup_plan_20261104.json) is preserved unchanged as the reviewed proposal. The [execution receipt](legacy_ffg_cleanup_receipt_20261104.json), [final storage audit](storage_audit_after_cleanup_20261104.json), and [successful production run](https://github.com/andreworrison-cloud/wpc-hydro-dashboard/actions/runs/41909745668) document the result. The production job had Actions write access and Contents read access.

The storage audit measures the repository's Git footprint, live site, caches and artifacts separately. It cannot verify account-wide billing, spending budgets, other repositories or bandwidth; deletion does not reverse accrued storage usage. GitHub may take 6–12 hours to update its storage usage display: [official billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions#example-artifact-storage-cost-calculation).
