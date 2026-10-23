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
tabs = {nm: E.Table(rows) for nm in ("EEG", "MOV", "COACT")}
for i, r in enumerate(rows):
    SE = np.nan_to_num(r["Se"], nan=-np.inf); SA = np.nan_to_num(r["Sa"], nan=-np.inf)
    for k in TE: tabs["EEG"].add(i, k, E.onsets(E.runlen_ok(SE >= np.log(k[0]), k[1])))
    for k in TM:
        a = (SA >= np.log(k[0])) & ((r["rh"] >= k[2]) if k[2] > 0 else True)
        tabs["MOV"].add(i, k, E.onsets(E.runlen_ok(a, k[1])))
    for (re_, rm, D) in TA:
        tabs["COACT"].add(i, (re_, rm, D), E.onsets(E.runlen_ok((SE >= np.log(re_)) & (SA >= np.log(rm)), D)))
    if i % 300 == 0: print("tables", i, flush=True)
res = dict(info=info, modes={})
rng = np.random.default_rng(0)
def f2b_flags(held):
    det, sub = [], []
    for h in held:
        r = rows[h["i"]]
        for k, c in enumerate(r["classes"]):
            if c == F2B: det.append(bool(h["detected"][k])); sub.append(h["subject"])
    return np.array(det), np.array(sub)
for t in (0.02, 0.05):
    for nm, tab in tabs.items():
        held, ch = E.loso(rows, tab, tab.keys(), t, cls=F2B)
        det, sub = f2b_flags(held)
        us = sorted(set(sub)); bs = []
        for _ in range(2000):
            pick = rng.choice(us, len(us)); bs.append(np.concatenate([det[sub==u] for u in pick]).mean())
        fa = sum(h["n_fa"] for h in held); h_ = sum(h["hours"] for h in held)
        # class-specific circular-shift null (only f2b detections counted)
        nul = np.zeros(perm)
        for p in range(perm):
            d = 0
            for h in held:
                r = rows[h["i"]]
                if F2B not in r["classes"] or not len(h["alarms"]): continue
                sh = (np.asarray(h["alarms"], float) + rng.uniform(0, r["duration_s"])) % r["duration_s"]
                for (on, off), c in zip(r["seizures"], r["classes"]):
                    if c == F2B: d += bool(np.any((sh >= on-PRE_S) & (sh <= off+POST_S)))
            nul[p] = d
        res["modes"][f"{nm}_{t}"] = dict(det=int(det.sum()), n=int(len(det)), sens=float(det.mean()),
            ci=[float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], fa=int(fa), hours=float(h_), fa_per_day=24*fa/h_,
            null_mean=float(nul.mean()/len(det)), null_p95=float(np.percentile(nul, 95)/len(det)), null_max=float(nul.max()/len(det)),
            p_null=float((1+np.sum(nul >= det.sum()))/(1+perm)), _det=det.tolist(), _sub=sub.tolist())
        m = res["modes"][f"{nm}_{t}"]
        print(nm, t, {k: (round(v,4) if isinstance(v,float) else v) for k, v in m.items() if not k.startswith("_")}, flush=True)
# subject-clustered paired comparison COACT vs EEG / MOV at each target
for t in (0.02, 0.05):
    a = res["modes"][f"COACT_{t}"]
    for o in ("EEG", "MOV"):
        b = res["modes"][f"{o}_{t}"]
        da, db, sub = np.array(a["_det"]), np.array(b["_det"]), np.array(a["_sub"])
        us = sorted(set(sub)); per = np.array([[da[sub==u].mean(), db[sub==u].mean()] for u in us])
        d = per[:, 0]-per[:, 1]; pos, neg = int((d>0).sum()), int((d<0).sum())
        p_sign = binomtest(pos, pos+neg, 0.5).pvalue if pos+neg else 1.0
        bd = []
        for _ in range(5000):
            pick = rng.choice(len(us), len(us)); bd.append(np.concatenate([da[sub==us[j]] for j in pick]).mean() - np.concatenate([db[sub==us[j]] for j in pick]).mean())
        n10 = int((da&~db).sum()); n01 = int((~da&db).sum())
        res[f"paired_COACT_vs_{o}_{t}"] = dict(subjects=len(us), subj_better=pos, subj_worse=neg, subj_tied=int((d==0).sum()), p_sign_subject=float(p_sign),
            diff=float(da.mean()-db.mean()), diff_ci=[float(np.percentile(bd,2.5)), float(np.percentile(bd,97.5))],
            seizure_mcnemar=dict(only_coact=n10, only_other=n01, p=float(binomtest(n10, n10+n01, 0.5).pvalue) if n10+n01 else 1.0))
        print("paired", o, t, res[f"paired_COACT_vs_{o}_{t}"], flush=True)
for m in res["modes"].values(): m.pop("_det"); m.pop("_sub")
outp.write_text(json.dumps(res, indent=1)); print("done")
