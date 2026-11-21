/* Pure display contract. Reevaluate with wall-clock time, even without new metadata. */
function ffgDisplayState(metadata, now = Date.now()) {
    const a = metadata?.active, p = metadata?.policy;
    const unavailable = {state: 'unavailable', visible: false, label: 'Unavailable — no validated guidance'};
    if (!a || !p || metadata.usable === false && metadata.state === 'unavailable') return unavailable;
    const snapshot = Date.parse(a.snapshot_time), reference = Date.parse(a.reference_time);
    const snapshotLimit = Number(p.max_snapshot_age_hours), referenceLimit = Number(p.max_reference_age_hours);
    const tolerance = Number(p.future_tolerance_minutes) * 60000;
    if (![now, snapshot, reference, snapshotLimit, referenceLimit, tolerance].every(Number.isFinite)
        || snapshotLimit <= 0 || referenceLimit <= 0 || tolerance < 0
        || snapshot > now + tolerance || reference > now + tolerance) return unavailable;
    const expires = Math.min(snapshot + snapshotLimit * 3600000, reference + referenceLimit * 3600000);
    if (now >= expires || metadata.state === 'expired')
        return {state: 'expired', visible: false, expires, label: 'Expired — guidance hidden'};
    if (metadata.usable === false) return unavailable;
    if (metadata.last_attempt?.ok !== true || metadata.stale || metadata.state === 'retained')
        return {state: 'retained', visible: true, expires, label: 'Refresh failed — showing last validated guidance'};
    return {state: 'current', visible: true, expires, label: 'Within freshness limits'};
}
if (typeof module !== 'undefined') module.exports = {ffgDisplayState};
