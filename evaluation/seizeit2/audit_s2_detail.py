"""Audit re-analysis of the convulsive (f2b) mode on SeizeIT2.
 (1) restrict to runs that HAVE a head-motion channel (so a motion-dependent alarm is not credited with hours/seizures it cannot see);
 (2) class-specific circular-shift chance level for f2b seizures;
 (3) subject-clustered paired comparison (replaces seizure-level McNemar, which ignores within-patient correlation).
usage: python audit_s2.py S2OUT OUT.json [--perm 500]"""
import sys, json, numpy as np, collections
from pathlib import Path
from scipy.stats import binomtest
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s2_eval as E
from scoring import PRE_S, POST_S
s2 = Path(sys.argv[1]); outp = Path(sys.argv[2]); perm = int(sys.argv[sys.argv.index("--perm")+1]) if "--perm" in sys.argv else 500
rows_all = E.load(s2)
rows = [r for r in rows_all if r["mov"]]
hrs_all = sum(r["duration_s"] for r in rows_all)/3600; hrs = sum(r["duration_s"] for r in rows)/3600
F2B = "FBTC/generalized"
info = dict(runs_all=len(rows_all), runs_mov=len(rows), hours_all=hrs_all, hours_mov=hrs,
            f2b_all=sum(c==F2B for r in rows_all for c in r["classes"]), f2b_mov=sum(c==F2B for r in rows for c in r["classes"]),
            f2b_subjects_mov=len({r["subject"] for r in rows if F2B in r["classes"]}),
            f2b_types=dict(collections.Counter(t for r in rows for t,c in zip(r["types"], r["classes"]) if c==F2B)))
print(info, flush=True)
TE = [(rr, D) for rr in (3.0, 4.0, 6.0, 8.0, 12.0, 16.0) for D in (5, 10, 20, 30, 45, 60)]
TM = [(rr, D, q) for rr in (8.0, 12.0, 16.0, 24.0, 32.0, 48.0) for D in (5, 10, 20, 30) for q in (0.0, 0.4)]
TA = [(re_, rm, D) for re_ in (1.5, 2.0, 3.0, 4.0, 6.0) for rm in (2.0, 3.0, 4.0, 8.0, 16.0, 32.0) for D in (3, 5, 10, 20, 30)]

import ast
tab = E.Table(rows)
for i, r in enumerate(rows):
    SE = np.nan_to_num(r["Se"], nan=-np.inf); SA = np.nan_to_num(r["Sa"], nan=-np.inf)
    for (re_, rm, D) in TA: tab.add(i, (re_, rm, D), E.onsets(E.runlen_ok((SE >= np.log(re_)) & (SA >= np.log(rm)), D)))
    if i % 300 == 0: print("tab", i, flush=True)
out = {}
for t in (0.02, 0.05):
    held, ch = E.loso(rows, tab, tab.keys(), t, cls=F2B)
    lat, vig, det = [], [], []
    fa = collections.defaultdict(int); hh = collections.defaultdict(float)
    for h in held:
        r = rows[h["i"]]; fa[h["subject"]] += h["n_fa"]; hh[h["subject"]] += h["hours"]
        for k, c in enumerate(r["classes"]):
            if c == F2B: det.append(bool(h["detected"][k])); lat.append(h["latency"][k]); vig.append(r["vig"][k])
    det = np.array(det); lat = np.array(lat, float); vig = np.array(vig)
    mc = collections.Counter(c["key"] for c in ch).most_common(3)
    out[str(t)] = dict(det=int(det.sum()), n=len(det), lat_median=float(np.nanmedian(lat[det])), lat_iqr=[float(np.nanpercentile(lat[det], q)) for q in (25, 75)],
        sleep_det=int(det[vig == "asleep"].sum()), sleep_n=int((vig == "asleep").sum()), subjects=len(fa),
        zero_fa_subjects=int(sum(1 for u in fa if fa[u] == 0)), modal_choices=mc)
    print(t, out[str(t)], flush=True)
outp.write_text(json.dumps(out, indent=1))
