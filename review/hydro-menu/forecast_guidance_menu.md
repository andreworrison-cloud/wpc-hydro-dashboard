# Consolidated HRRR / RRFS forecast guidance menu

The former GDI and six flash-flood sections now appear under one **HRRR / RRFS Forecast Guidance** parent. It has one Experimental badge and native radio controls for Model (HRRR, RRFS, HRRR/RRFS Blend) and Product family (Diagnostics, TLE, GDI).

All 66 existing controls remain registered with the same IDs, internal labels and layer objects: two deterministic diagnostics, eighteen TLE products and two GDI products per model. The TLE groups are FFG Exceedance (5), Heavy Rain & Persistence (6), and Timing & Trends (7). FFG Exceedance opens initially; the other groups open when used and remember their disclosure states.

Changing model transfers checked guidance products to their corresponding layers and carries their opacity. Existing deliberate multi-product overlays remain possible. GDI continues to preserve its selected absolute forecast time through its existing adapter. Changing product family browses its controls without turning on an unchecked layer. Context layers remain independently selectable.

The browser remembers model, family, last product in each family, disclosure states and checked guidance controls. Storage errors or obsolete values fall back to valid defaults. Preference writes are deduplicated, so GDI animation does not write storage every frame. Existing data-adapter expiry, checksum, completeness and source-time rules remain authoritative.

The active-product status displays the model, product, source cycle and valid time. It uses the GDI frame actually displayed, including retained verified frames, and the flash-flood adapter's published metadata. Unavailable or expired guidance receives an explicit status.

Search spans all models and families. Matching products open their groups; clearing search returns to the selected model and family. Search result headings retain model and family context even though ordinary product rows use shorter labels.

Validation includes nine DOM/controller scenarios covering registry preservation, three-model switching, opacity, multiple products, GDI product identity, search recovery, preference restoration and unavailable local storage; the existing flash-flood, GDI playback, legend/checkbox and CAM checks; and browser checks on the preview and live dashboard. No new data producer, model download, schedule, cache or artifact stream is introduced by this menu change.

Live publication and browser checks passed on 4 November 2026. The [verification record](forecast_guidance_verification_20261104.json) and [live menu image](forecast_guidance_live_20261104.jpg) document all 66 controls, model switching, source/valid-time labels, GDI hourly comparison at 00Z, and the Day 1 window.
