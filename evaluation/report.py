"""
Aggregate records.jsonl (+ features/*.npz) into paper-ready tables and figures.

usage: python report.py --results results [--data ../data/chbmit]
writes: results/summary.json, results/tables/*.csv|.md, results/figures/*.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import score_record, summarise                     # noqa: E402

DET = {"py": "Python analyzer (LL+DAR+HFE, 2-of-3)", "fw": "ESP32 firmware (abs(x−EMA), μ+Kσ)"}
KIND = {"seizure_alarms": "BLACKOUT alarm", "any_alarms": "BROWNOUT-or-BLACKOUT alarm"}
C_PY, C_FW, INK, MUTED, SZ_FILL = "#2a78d6", "#eb6834", "#1f1f1e", "#6b6a64", "#d9d8d2"


def load(results: Path):
    rows = [json.loads(l) for l in (results / "records.jsonl").read_text().splitlines() if l.strip()]
    return [r for r in rows if not r.get("missing")]


def evaluate(rows, det, kind, channel):
    scored = []
    for r in rows:
        if r["channel"] != channel:
            continue
        s = score_record(r[det][kind], [tuple(x) for x in r["seizures"]], r["duration_s"])
        s["case"] = r["case"]; s["record"] = r["record"]
        scored.append(s)
    return summarise(scored), scored


def chance_sensitivity(rows, channel, fa_per_hour):
    """Expected sensitivity of a Poisson alarm process with the same rate."""
    from scoring import PRE_S, POST_S
    lam = fa_per_hour / 3600.0
    p = [1 - np.exp(-lam * (off - on + PRE_S + POST_S))
         for r in rows if r["channel"] == channel for on, off in r["seizures"]]
    return float(np.mean(p)) if p else np.nan


def fmt_row(name, s):
    lo, hi = s["latency_iqr"]
    return (f"| {name} | {s['detected']}/{s['seizures']} ({100*s['sensitivity']:.1f}%) | "
            f"{100*s['mean_case_sensitivity']:.1f}% | {s['false_alarms']} | {s['fa_per_hour']:.2f} | "
            f"{s['fa_per_24h']:.1f} | {s['latency_median']:.1f} [{lo:.1f}, {hi:.1f}] | {100*s.get('chance', np.nan):.1f}% |")


# ── feature discriminability ────────────────────────────────────────────────
def auc(pos, neg):
    from scipy.stats import mannwhitneyu
    pos, neg = np.asarray(pos), np.asarray(neg)
    pos, neg = pos[np.isfinite(pos)], neg[np.isfinite(neg)]
    if len(pos) < 5 or len(neg) < 5:
        return np.nan
    u = mannwhitneyu(pos, neg, alternative="two-sided").statistic
    return float(u / (len(pos) * len(neg)))


def feature_analysis(rows, results: Path, channel):
    """Pooled + per-patient AUC of each feature, ictal vs inter-ictal ticks."""
    fdir = results / "features"
    names = ["Line-length", "Delta/alpha ratio", "High-freq energy", "Firmware abs(x−EMA)"]
    pooled = {n: ([], []) for n in names}
    per_case = {}
    rng = np.random.default_rng(0)
    for r in rows:
        if r["channel"] != channel:
            continue
        f = fdir / f"{r['record']}_{channel}.npz"
        if not f.exists():
            continue
        z = np.load(f)
        t = z["ft"]
        def masks(tt):
            ict = np.zeros(len(tt), bool); far = np.ones(len(tt), bool)
            for on, off in r["seizures"]:
                ict |= (tt >= on) & (tt <= off)
                far &= ~((tt >= on - 300) & (tt <= off + 300))
            far &= tt > 120                                   # skip warm-up
            return ict, far
        ict, far = masks(t)
        fi, ff = masks(z["fw_t10"])
        series = [z["ll"], z["dar"], z["hfe"]]
        for n, x in zip(names[:3], series):
            pooled[n][0].append(x[ict]); pooled[n][1].append(x[far][rng.random(far.sum()) < 0.1])
        pooled[names[3]][0].append(z["fw_diff10"][fi])
        pooled[names[3]][1].append(z["fw_diff10"][ff][rng.random(ff.sum()) < 0.1])
        c = per_case.setdefault(r["case"], {n: ([], []) for n in names})
        for n, x in zip(names[:3], series):
            c[n][0].append(x[ict]); c[n][1].append(x[far])
        c[names[3]][0].append(z["fw_diff10"][fi]); c[names[3]][1].append(z["fw_diff10"][ff])
    out = {}
    for n in names:
        p = np.concatenate(pooled[n][0]) if pooled[n][0] else np.array([])
        q = np.concatenate(pooled[n][1]) if pooled[n][1] else np.array([])
        cases = [auc(np.concatenate(v[n][0]), np.concatenate(v[n][1])) for v in per_case.values()]
        cases = [a for a in cases if np.isfinite(a)]
        out[n] = dict(pooled_auc=auc(p, q), median_case_auc=float(np.median(cases)) if cases else np.nan,
                      cases=len(cases), ictal_median=float(np.median(p)) if len(p) else np.nan,
                      interictal_median=float(np.median(q)) if len(q) else np.nan,
                      _ictal=p, _inter=q)
    return out


# ── figures ─────────────────────────────────────────────────────────────────
def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED); ax.spines[s].set_linewidth(0.6)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.yaxis.label.set_color(INK); ax.xaxis.label.set_color(INK)
    ax.grid(axis="y", color="#e6e5df", linewidth=0.5); ax.set_axisbelow(True)


def fig_per_case(scored_py, scored_fw, path):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    pc_py, pc_fw = scored_py["per_case"], scored_fw["per_case"]
    cases = sorted(pc_py)
    x = np.arange(len(cases)); w = 0.38
    fig, axs = plt.subplots(2, 1, figsize=(9, 5.2), sharex=True)
    for ax, key, lab in ((axs[0], "sens", "Sensitivity (%)"), (axs[1], "fa", "False alarms / h")):
        for off, pc, col, name in ((-w/2, pc_py, C_PY, "Python analyzer"), (w/2, pc_fw, C_FW, "ESP32 firmware")):
            v = [100*pc[c]["n_det"]/pc[c]["n_sz"] if key == "sens" else pc[c]["n_fa"]/pc[c]["hours"] for c in cases]
            ax.bar(x+off, v, w-0.04, color=col, label=name)
        ax.set_ylabel(lab, fontsize=9); _style(ax)
    axs[0].legend(frameon=False, fontsize=8, ncol=2, loc="upper right")
    axs[1].set_xticks(x); axs[1].set_xticklabels(cases, rotation=60, fontsize=7)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_features(fa, path):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = list(fa)
    fig, axs = plt.subplots(1, len(names), figsize=(11, 2.8))
    for ax, n in zip(axs, names):
        a, b = fa[n]["_inter"], fa[n]["_ictal"]
        if len(a) == 0 or len(b) == 0:
            ax.set_axis_off(); continue
        both = np.concatenate([a, b]); both = both[np.isfinite(both)]
        logx = n in ("Line-length", "Firmware abs(x−EMA)", "High-freq energy")
        if logx:
            pos = both[both > 0]
            lo, hi = np.percentile(pos, 0.5), np.percentile(pos, 99.5)
            bins = np.geomspace(max(lo, 1e-6), hi, 60); ax.set_xscale("log")
        else:
            lo, hi = np.percentile(both, 0.5), np.percentile(both, 99.5)
            bins = np.linspace(lo, hi, 60)
        ax.hist(a, bins, density=True, color="#9a9990", alpha=0.8, label="inter-ictal")
        ax.hist(b, bins, density=True, histtype="step", color=C_PY, linewidth=1.6, label="ictal")
        ax.set_title(f"{n}\nAUC {fa[n]['pooled_auc']:.2f}", fontsize=8.5, color=INK)
        ax.set_yticks([]); _style(ax); ax.grid(False)
    axs[0].legend(frameon=False, fontsize=7)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def fig_example(rows, results, data_dir, channel, path):
    """One seizure: device-scale EEG + both detectors' state traces."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from chbmit import load_record, to_device_adc
    cand = [r for r in rows if r["channel"] == channel and r["seizures"]
            and (Path(data_dir) / f"{r['record']}.ch.json").exists()]
    if not cand:
        return False
    # prefer a seizure the Python analyzer detected
    def hit(r):
        on, off = r["seizures"][0]
        return any(on - 30 <= a <= off + 60 for a in r["py"]["seizure_alarms"])
    cand.sort(key=lambda r: (not hit(r), r["record"]))
    r = cand[0]; on, off = r["seizures"][0]
    rec = load_record(Path(data_dir), r["case"], r["record"], r["seizures"])
    adc = to_device_adc(rec.uv[channel], rec.fs)  # default front-end model
    z = np.load(results / "features" / f"{r['record']}_{channel}.npz")
    t0, t1 = max(0, on - 240), on + (off - on) + 240
    ts = np.arange(len(adc)) / 200.0; m = (ts >= t0) & (ts <= t1)
    fig, axs = plt.subplots(3, 1, figsize=(9, 4.6), sharex=True, gridspec_kw=dict(height_ratios=[2.2, 1, 1]))
    for ax in axs:
        ax.axvspan(on, off, color=SZ_FILL, zorder=0)
    axs[0].plot(ts[m], adc[m], color=INK, linewidth=0.35)
    axs[0].set_ylabel("ADC code", fontsize=8)
    axs[0].set_title(f"{r['record']} · {channel} · annotated seizure {on}–{off} s (shaded)", fontsize=9, color=INK)
    lab = ["NORMAL", "BROWN", "BLACK", "POST"]
    mt = (z["t"] >= t0) & (z["t"] <= t1)
    axs[1].step(z["t"][mt], z["state"][mt], where="post", color=C_PY, linewidth=1.2)
    mf = (z["fw_t10"] >= t0) & (z["fw_t10"] <= t1)
    axs[2].step(z["fw_t10"][mf], z["fw_state"][: len(z["fw_t10"])][mf], where="post", color=C_FW, linewidth=1.2)
    for ax, name in ((axs[1], "Python"), (axs[2], "Firmware")):
        ax.set_yticks(range(4)); ax.set_yticklabels(lab, fontsize=6.5); ax.set_ylabel(name, fontsize=8)
    axs[2].set_xlabel("time (s)", fontsize=8)
    for ax in axs:
        _style(ax)
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)
    return r["record"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--data", default=None, help="data dir (for example-trace figure)")
    ap.add_argument("--channel", default="FP1-F7")
    a = ap.parse_args()
    res = Path(a.results)
    (res / "tables").mkdir(parents=True, exist_ok=True); (res / "figures").mkdir(exist_ok=True)
    rows = load(res)
    chans = sorted({r["channel"] for r in rows})

    summary, md = {}, []
    hdr = ("| Detector · alarm | Seizures detected | Mean per-patient sens. | False alarms | FA/h | FA/24 h | "
           "Latency median [IQR] (s) | Chance sens. at same alarm rate |\n|---|---|---|---|---|---|---|---|")
    total_h = {}
    for ch in chans:
        md.append(f"\n### Channel {ch}\n\n{hdr}")
        for det in ("py", "fw"):
            for kind in ("seizure_alarms", "any_alarms"):
                s, _ = evaluate(rows, det, kind, ch)
                s["chance"] = chance_sensitivity(rows, ch, s["fa_per_hour"])
                summary[f"{ch}|{det}|{kind}"] = {k: v for k, v in s.items() if k != "per_case"}
                md.append(fmt_row(f"{DET[det]} · {KIND[kind]}", s))
                total_h[ch] = s["hours"]
    cases = sorted({r["case"] for r in rows})
    n_rec = len({r["record"] for r in rows})
    head = (f"# Vera detector evaluation on CHB-MIT\n\n{len(cases)} patients · {n_rec} recordings · "
            f"{max(total_h.values()):.1f} h · scoring: alarm within [onset−30 s, offset+60 s] = detection; "
            f"alarms <90 s apart merged; all other alarms = false alarms.\n")
    (res / "tables" / "main_results.md").write_text(head + "\n".join(md) + "\n")

    # per-patient table (primary channel, BLACKOUT alarm)
    s_py, _ = evaluate(rows, "py", "seizure_alarms", a.channel)
    s_fw, _ = evaluate(rows, "fw", "seizure_alarms", a.channel)
    lines = ["case,seizures,hours,py_detected,py_fa,py_fa_per_h,fw_detected,fw_fa,fw_fa_per_h"]
    for c in sorted(s_py["per_case"]):
        p, f = s_py["per_case"][c], s_fw["per_case"][c]
        lines.append(f"{c},{p['n_sz']},{p['hours']:.2f},{p['n_det']},{p['n_fa']},{p['n_fa']/p['hours']:.2f},"
                     f"{f['n_det']},{f['n_fa']},{f['n_fa']/f['hours']:.2f}")
    (res / "tables" / f"per_patient_{a.channel}.csv").write_text("\n".join(lines) + "\n")
    fig_per_case(s_py, s_fw, res / "figures" / f"per_patient_{a.channel}.png")

    # artifact rejection & ADC usage
    art = {}
    for ch in chans:
        rr = [r for r in rows if r["channel"] == ch]
        art[ch] = dict(artifact_epochs=int(sum(r["py"]["artifact_epochs"] for r in rr)),
                       ictal_artifact_frac=float(sum(r["py"].get("ictal_artifact_ticks", 0) for r in rr) /
                                                 max(1, sum(r["py"].get("ictal_ticks", 0) for r in rr))),
                       interictal_artifact_frac=float(sum(r["py"].get("interictal_artifact_ticks", 0) for r in rr) /
                                                      max(1, sum(r["py"].get("interictal_ticks", 0) for r in rr))),
                       ticks=int(sum(r["py"]["ticks"] for r in rr)),
                       adc_clip_frac_mean=float(np.mean([r["adc_clip_frac"] for r in rr])),
                       time_in_state_py=list(np.mean([r["py"]["occupancy"] for r in rr], 0)),
                       time_in_state_fw=list(np.mean([r["fw"]["occupancy"] for r in rr], 0)))
    summary["signal_stats"] = art

    # feature discriminability
    fa = feature_analysis(rows, res, a.channel)
    summary["feature_auc"] = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in fa.items()}
    fl = ["| Feature | Pooled AUC (ictal vs inter-ictal) | Median per-patient AUC | Ictal median | Inter-ictal median |",
          "|---|---|---|---|---|"]
    for k, v in fa.items():
        fl.append(f"| {k} | {v['pooled_auc']:.3f} | {v['median_case_auc']:.3f} (n={v['cases']}) | "
                  f"{v['ictal_median']:.3g} | {v['interictal_median']:.3g} |")
    (res / "tables" / f"feature_auc_{a.channel}.md").write_text("\n".join(fl) + "\n")
    fig_features(fa, res / "figures" / f"feature_distributions_{a.channel}.png")

    if a.data:
        ex = fig_example(rows, res, a.data, a.channel, res / "figures" / f"example_trace_{a.channel}.png")
        summary["example_record"] = ex

    summary["n_patients"] = len(cases); summary["n_recordings"] = n_rec
    summary["primary_channel"] = a.channel
    (res / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    print((res / "tables" / "main_results.md").read_text())
    print("\n".join(fl))


if __name__ == "__main__":
    main()
