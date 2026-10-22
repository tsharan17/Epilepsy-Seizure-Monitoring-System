"""SeizeIT2 evaluation of the multimodal device detectors (subject-level LOSO, SzCORE scoring).

Detectors (all on signals the v5 firmware computes, 1 value per second):
  FW      shipped firmware BLACKOUT entries (code-faithful replay, behind-the-ear EEG)
  EEG     DEV-BR on the firmware deviation:   S_e >= log r_e for D_e s
  MOV     MOV-BR on high-passed head acceleration: S_a >= log r_m AND rhythm >= q for D_m s
  FUSED   alarm when EEG or MOV condition holds (single merged alarm stream)
S_x = log(x / median of x over [t-329, t-30])  (no alarms before 330 s).
Parameters chosen by leave-one-subject-out: most sensitive setting with pooled training
FA/h <= target, applied to the held-out subject.
usage: python s2_eval.py S2OUT [--perm 200]
"""
import json, sys, re, collections
from pathlib import Path
import numpy as np, pandas as pd

EV = Path(__file__).resolve().parent.parent   # evaluation/ (chbmit, detectors, scoring, rigor, run_eval)
sys.path.insert(0, str(EV))
import rigor as RG                       # noqa
from scoring import PRE_S, POST_S        # noqa
MERGE = 90
WIN, LAG = 300, 30

R_E = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0]
D_E = [4, 6, 10, 15, 20, 30]
R_M = [2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0]
D_M = [3, 5, 10, 15, 20, 30]
Q_M = [0.0, 0.3, 0.4, 0.5]
TARGETS = [0.25, 0.5, 1.0]


def lr(x):
    bg = pd.Series(x).rolling(WIN, min_periods=WIN // 2).median().shift(LAG).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.log(np.maximum(x, 1e-9) / np.maximum(bg, 1e-9))
    r[:WIN + LAG] = np.nan
    return r


def runlen_ok(mask, D):
    """True at t when mask held for the last D seconds."""
    m = mask.astype(np.int32)
    cs = np.concatenate([[0], np.cumsum(m)])
    out = np.zeros(len(m), bool)
    if len(m) >= D:
        out[D - 1:] = (cs[D:] - cs[:-D]) == D
    return out


def onsets(trig):
    on = np.flatnonzero(trig & ~np.concatenate([[False], trig[:-1]])) + 1.0
    out = []
    for a in on:
        if not out or a - out[-1] >= MERGE:
            out.append(float(a))
    return np.array(out)


def merge(al):
    al = np.sort(np.asarray(al, float)); out = []
    for a in al:
        if not out or a - out[-1] >= MERGE:
            out.append(a)
    return np.array(out)


def score(al, sz):
    """fast SzCORE scoring -> (detected bool array, n_fa, latencies)"""
    al = np.asarray(al, float)
    det = np.zeros(len(sz), bool); lat = np.full(len(sz), np.nan); used = np.zeros(len(al), bool)
    for k, (on, off) in enumerate(sz):
        h = (al >= on - PRE_S) & (al <= off + POST_S)
        if h.any():
            det[k] = True; lat[k] = al[h].min() - on; used |= h
    return det, int((~used).sum()), lat


def sz_class(t):
    if "f2b" in t or "_tc" in t or t.startswith("sz_gen"):
        return "FBTC/generalized"
    if "_m" in t.split("sz_foc_")[-1][:6] or "_m_" in t or t.endswith("_m"):
        return "focal motor"
    if "_nm" in t:
        return "focal non-motor"
    return "other/unknown"


def load(s2):
    meta = {}
    for l in open(s2 / "meta.jsonl"):
        x = json.loads(l)
        if "run" in x and (s2 / "feat" / f"{x['run']}.npz").exists():
            meta[x["run"]] = x
    rows = []
    for run, x in sorted(meta.items()):
        z = np.load(s2 / "feat" / f"{run}.npz")
        n = int(x["duration_s"])
        sz = [(s["on"], s["on"] + s["dur"]) for s in x["seizures"]]
        r = dict(run=run, case=run.split("_")[0], subject=run.split("_")[0], duration_s=x["duration_s"],
                 seizures=sz, types=[s["type"] for s in x["seizures"]], vig=[s.get("vig", "n/a") for s in x["seizures"]],
                 classes=[sz_class(s["type"]) for s in x["seizures"]], mov=bool(x.get("mov")),
                 fw=x["fw0"]["seizure_alarms"], fw_any=x["fw0"]["any_alarms"])
        r["Se"] = lr(z["dev0"][:n])
        if r["mov"]:
            r["Sa"] = lr(z["acc"][:n]); r["Sg"] = lr(z["gyr"][:n]); r["rh"] = np.nan_to_num(z["rhy"][:n], nan=0.0)
        rows.append(r)
    return rows


def masks_eeg(r):
    out = {}
    S = np.nan_to_num(r["Se"], nan=-np.inf)
    for rr in R_E:
        a = S >= np.log(rr)
        for D in D_E:
            out[(rr, D)] = runlen_ok(a, D)
    return out


def masks_mov(r, sig="Sa"):
    out = {}
    if not r["mov"]:
        n = len(r["Se"]); z = np.zeros(n, bool)
        return {(rr, D, q): z for rr in R_M for D in D_M for q in Q_M}
    S = np.nan_to_num(r[sig], nan=-np.inf)
    for rr in R_M:
        a = S >= np.log(rr)
        for q in Q_M:
            b = a & (r["rh"] >= q) if q > 0 else a
            for D in D_M:
                out[(rr, D, q)] = runlen_ok(b, D)
    return out


class Table:
    """per record, per parameter key: (detected array, n_fa, latency array, alarms)"""
    def __init__(self, rows):
        self.rows = rows; self.t = [dict() for _ in rows]

    def add(self, i, key, al):
        d, fa, lat = score(al, self.rows[i]["seizures"])
        self.t[i][key] = (d, fa, lat, al)

    def keys(self):
        return list(self.t[0].keys())


def loso(rows, tab, keys, target, cls=None):
    subj = np.array([r["subject"] for r in rows]); us = sorted(set(subj))
    sel = [np.array([c == cls for c in r["classes"]], bool) if cls else np.ones(len(r["seizures"]), bool) for r in rows]
    nsz = np.array([s_.sum() for s_ in sel]); hrs = np.array([r["duration_s"] / 3600 for r in rows])
    K = len(keys)
    det = np.array([[tab.t[i][k][0][sel[i]].sum() for k in keys] for i in range(len(rows))])   # rows x K
    fa = np.array([[tab.t[i][k][1] for k in keys] for i in range(len(rows))])
    # subject totals
    sidx = {u: np.flatnonzero(subj == u) for u in us}
    Sd = np.array([det[sidx[u]].sum(0) for u in us]); Sf = np.array([fa[sidx[u]].sum(0) for u in us])
    Sn = np.array([nsz[sidx[u]].sum() for u in us]); Sh = np.array([hrs[sidx[u]].sum() for u in us])
    Td, Tf, Tn, Th = Sd.sum(0), Sf.sum(0), Sn.sum(), Sh.sum()
    held, choice = [], []
    for j, u in enumerate(us):
        sens = (Td - Sd[j]) / max(Tn - Sn[j], 1); fah = (Tf - Sf[j]) / (Th - Sh[j])
        ok = fah <= target
        if not ok.any():
            kbest = int(np.argmin(fah))
        else:
            cand = np.flatnonzero(ok)
            best = cand[np.lexsort((fah[cand], -sens[cand]))[0]]
            kbest = int(best)
        choice.append(dict(subject=u, key=str(keys[kbest])))
        for i in sidx[u]:
            d, f, lat, al = tab.t[i][keys[kbest]]
            held.append(dict(n_sz=len(d), detected=list(map(bool, d)), n_fa=int(f), hours=float(hrs[i]),
                             latency=list(lat), subject=u, i=int(i), alarms=list(al)))
    return held, choice


def by_class(held, rows):
    c = collections.defaultdict(lambda: [0, 0])
    for h in held:
        r = rows[h["i"]]
        for k, d in enumerate(h["detected"]):
            for key in (r["classes"][k], "vig:" + r["vig"][k]):
                c[key][0] += int(d); c[key][1] += 1
    return {k: dict(det=v[0], n=v[1], sens=v[0] / v[1]) for k, v in c.items()}


def summ(held, rows, perm):
    m = RG.summarise(held, rows)
    m["fa_per_day"] = 24 * m["fa_per_hour"]
    m["by_class"] = by_class(held, rows)
    if perm:
        m["null"] = RG.null_test(held, rows, perm)
    m.pop("per_subject_full", None)
    return m


def main():
    s2 = Path(sys.argv[1]); perm = int(sys.argv[sys.argv.index("--perm") + 1]) if "--perm" in sys.argv else 200
    rows = load(s2)
    print(len(rows), "runs", len({r['subject'] for r in rows}), "subjects", sum(len(r['seizures']) for r in rows), "seizures",
          round(sum(r['duration_s'] for r in rows) / 3600), "h", flush=True)
    out = dict(n_runs=len(rows), n_subjects=len({r['subject'] for r in rows}),
               n_seizures=sum(len(r['seizures']) for r in rows), hours=sum(r['duration_s'] for r in rows) / 3600,
               n_mov_missing=sum(not r["mov"] for r in rows),
               class_counts=collections.Counter(c for r in rows for c in r["classes"]),
               type_counts=collections.Counter(t for r in rows for t in r["types"]),
               methods={}, choices={}, tests={})
    # shipped firmware
    sc = []
    for i, r in enumerate(rows):
        d, f, lat = score(r["fw"], r["seizures"])
        sc.append(dict(n_sz=len(d), detected=list(map(bool, d)), n_fa=f, hours=r["duration_s"] / 3600,
                       latency=list(lat), subject=r["subject"], i=i, alarms=list(r["fw"])))
    out["methods"]["FW"] = summ(sc, rows, perm)
    print("FW", round(100 * out["methods"]["FW"]["sensitivity"], 1), round(out["methods"]["FW"]["fa_per_hour"], 2), flush=True)
    # per-record trigger masks
    tE, tM, tG, tF, tA = Table(rows), Table(rows), Table(rows), Table(rows), Table(rows)
    FE = [(rr, D) for rr in (2.0, 3.0, 4.0, 6.0, 8.0) for D in (4, 10, 20, 30)]
    FM = [(rr, D, q) for rr in (4.0, 8.0, 12.0, 16.0, 24.0) for D in (5, 10, 20) for q in (0.0, 0.4)]
    for i, r in enumerate(rows):
        me = masks_eeg(r); mm = masks_mov(r, "Sa"); mg = masks_mov(r, "Sg")
        for k, m in me.items():
            tE.add(i, k, onsets(m))
        for k, m in mm.items():
            tM.add(i, k, onsets(m))
        for k, m in mg.items():
            tG.add(i, k, onsets(m))
        for ke in FE:
            for km in FM:
                tF.add(i, (ke, km), onsets(me[ke] | mm[km]))
        if r["mov"]:
            SE = np.nan_to_num(r["Se"], nan=-np.inf); SA = np.nan_to_num(r["Sa"], nan=-np.inf)
        for re_ in (1.5, 2.0, 3.0, 4.0):
            for rm in (2.0, 3.0, 4.0, 6.0, 8.0):
                c = (SE >= np.log(re_)) & (SA >= np.log(rm)) if r["mov"] else None
                for D in (4, 10, 20):
                    tA.add(i, (re_, rm, D), onsets(runlen_ok(c, D)) if c is not None else np.array([]))
        if i % 200 == 0:
            print(" masks", i, flush=True)
    for name, tab in (("EEG", tE), ("MOV", tM), ("MOVGYR", tG), ("FUSED", tF), ("COACT", tA)):
        keys = tab.keys()
        fw_t = round(out["methods"]["FW"]["fa_per_hour"], 2)
        out["fw_target"] = fw_t
        for t in TARGETS + ([fw_t] if name in ("EEG", "FUSED") else []):
            held, ch = loso(rows, tab, keys, t)
            key = f"{name}_{t}"
            out["methods"][key] = summ(held, rows, perm if t in (0.5, 1.0) else 0)
            if t == fw_t:
                out["methods"][f"{name}_atFW"] = out["methods"][key]
            out["choices"][key] = ch
            m = out["methods"][key]
            print(key, f"{100*m['sensitivity']:.1f}% @ {m['fa_per_hour']:.3f} FA/h ({m['fa_per_day']:.1f}/day) macro {100*m['macro_sensitivity']:.1f}%",
                  {k: round(100 * v['sens'], 1) for k, v in m['by_class'].items()}, flush=True)
    # ---- convulsive (FBTC) alarm mode: parameters chosen for FBTC sensitivity at very low FA/h ----
    tT = {nm: Table(rows) for nm in ("EEG", "MOV", "FUSED", "COACT")}
    TE = [(rr, D) for rr in (3.0, 4.0, 6.0, 8.0, 12.0, 16.0) for D in (5, 10, 20, 30, 45, 60)]
    TM = [(rr, D, q) for rr in (8.0, 12.0, 16.0, 24.0, 32.0, 48.0) for D in (5, 10, 20, 30) for q in (0.0, 0.4)]
    TF = [(e, m) for e in TE[::2] for m in TM[::2]]
    TA = [(re_, rm, D) for re_ in (1.5, 2.0, 3.0, 4.0, 6.0) for rm in (2.0, 3.0, 4.0, 8.0, 16.0, 32.0) for D in (3, 5, 10, 20, 30)]
    for i, r in enumerate(rows):
        SE = np.nan_to_num(r["Se"], nan=-np.inf)
        me = {k: runlen_ok(SE >= np.log(k[0]), k[1]) for k in TE}
        if r["mov"]:
            SA = np.nan_to_num(r["Sa"], nan=-np.inf)
            mm = {k: runlen_ok((SA >= np.log(k[0])) & ((r["rh"] >= k[2]) if k[2] > 0 else True), k[1]) for k in TM}
        else:
            z = np.zeros(len(SE), bool); mm = {k: z for k in TM}
        for k in TE: tT["EEG"].add(i, k, onsets(me[k]))
        for k in TM: tT["MOV"].add(i, k, onsets(mm[k]))
        for (ke, km) in TF: tT["FUSED"].add(i, (ke, km), onsets(me[ke] | mm[km]))
        for (re_, rm, D) in TA:
            c = ((SE >= np.log(re_)) & (SA >= np.log(rm))) if r["mov"] else np.zeros(len(SE), bool)
            tT["COACT"].add(i, (re_, rm, D), onsets(runlen_ok(c, D)))
    out["tc"] = {}
    for nm, tab in tT.items():
        for t in (0.02, 0.05, 0.1, 0.2):
            held, ch = loso(rows, tab, tab.keys(), t, cls="FBTC/generalized")
            m = summ(held, rows, perm if t in (0.02, 0.05) else 0)
            out["tc"][f"{nm}_{t}"] = m; out["choices"][f"TC_{nm}_{t}"] = ch
            v = m["by_class"].get("FBTC/generalized", {})
            print("TC", nm, t, f"FBTC {v.get('det')}/{v.get('n')} = {100*v.get('sens', float('nan')):.1f}%  FA/h {m['fa_per_hour']:.3f} ({m['fa_per_day']:.2f}/day)", flush=True)
    for t in (0.5, 1.0):
        for a, b in (("FUSED", "EEG"), ("FUSED", "MOV"), ("MOV", "EEG"), ("EEG", "FW"), ("COACT", "EEG"), ("FUSED", "FW")):
            ka = f"{a}_{t}"; kb = f"{b}_{t}" if b != "FW" else "FW"
            out["tests"][f"{ka}_vs_{kb}"] = RG.wilcoxon_subjects(out["methods"][ka], out["methods"][kb])
    for a in ("EEG", "FUSED"):
        out["tests"][f"{a}_atFW_vs_FW"] = RG.wilcoxon_subjects(out["methods"][f"{a}_atFW"], out["methods"]["FW"])
    (s2 / "s2_results.json").write_text(json.dumps(out, indent=1, default=lambda o: o if not isinstance(o, np.generic) else o.item()))
    print("done")


if __name__ == "__main__":
    main()
