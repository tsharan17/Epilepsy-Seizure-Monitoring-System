"""
Event-based scoring (SzCORE-style any-overlap with tolerances).

An *alarm* is the moment the detector enters an alarm state from a non-alarm
state.  Two alarm definitions are reported:
  • "seizure alarm"  : entry into BLACKOUT                (the urgent alert)
  • "any alarm"      : entry into BROWNOUT or BLACKOUT     (warning or urgent)
Alarms closer than MERGE_S to the previous alarm are merged (one alert).

A seizure is detected if an alarm falls in [onset − PRE_S, offset + POST_S].
Latency = first such alarm − onset (negative = before annotated onset).
Every alarm that falls in no seizure's window is a false alarm.
"""
from __future__ import annotations

import numpy as np

PRE_S = 30.0
POST_S = 60.0
MERGE_S = 90.0


def alarm_times(t, states, kind="seizure"):
    t = np.asarray(t); s = np.asarray(states)
    alarm = (s == 2) if kind == "seizure" else ((s == 1) | (s == 2))
    prev = np.concatenate([[False], alarm[:-1]])
    onsets = t[alarm & ~prev]
    merged = []
    for a in onsets:
        if not merged or a - merged[-1] >= MERGE_S:
            merged.append(float(a))
    return merged


def score_record(alarms, seizures, duration_s):
    det, lat = [], []
    used = set()
    for (on, off) in seizures:
        hits = [a for a in alarms if on - PRE_S <= a <= off + POST_S]
        det.append(bool(hits))
        lat.append(min(hits) - on if hits else np.nan)
        used.update(hits)
    fa = [a for a in alarms if a not in used]
    return dict(n_sz=len(seizures), detected=det, latency=lat,
                n_fa=len(fa), fa_times=fa, hours=duration_s / 3600.0)


def summarise(rows):
    """rows: list of dicts from score_record (+ 'case').  Pooled + per-case."""
    n_sz = sum(r["n_sz"] for r in rows)
    n_det = sum(sum(r["detected"]) for r in rows)
    hours = sum(r["hours"] for r in rows)
    n_fa = sum(r["n_fa"] for r in rows)
    lats = [l for r in rows for l in r["latency"] if not np.isnan(l)]
    per_case = {}
    for r in rows:
        c = per_case.setdefault(r["case"], dict(n_sz=0, n_det=0, n_fa=0, hours=0.0, lat=[]))
        c["n_sz"] += r["n_sz"]; c["n_det"] += sum(r["detected"])
        c["n_fa"] += r["n_fa"]; c["hours"] += r["hours"]
        c["lat"] += [l for l in r["latency"] if not np.isnan(l)]
    case_sens = [c["n_det"] / c["n_sz"] for c in per_case.values() if c["n_sz"]]
    return dict(
        seizures=n_sz, detected=n_det,
        sensitivity=n_det / n_sz if n_sz else np.nan,
        mean_case_sensitivity=float(np.mean(case_sens)) if case_sens else np.nan,
        hours=hours, false_alarms=n_fa, fa_per_hour=n_fa / hours if hours else np.nan,
        fa_per_24h=24 * n_fa / hours if hours else np.nan,
        latency_median=float(np.median(lats)) if lats else np.nan,
        latency_iqr=(float(np.percentile(lats, 25)), float(np.percentile(lats, 75))) if lats else (np.nan, np.nan),
        per_case=per_case,
    )
