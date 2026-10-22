"""
Draw the paper figures from a results folder (vera_results + features/ +
final.json from final_analysis.py).

usage: python make_figures.py <results_dir>
writes figures/operating_curve.png, figures/per_patient.png,
       figures/devbr_example.png, figures/feature_distributions.png
"""
import json
import shutil
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval" / "evaluation"))

C_PY, C_FW, C_DEV, C_LL, INK, MUTED, GRID, SZ = "#2a78d6", "#eb6834", "#1baf7a", "#8a8980", "#1f1f1e", "#6b6a64", "#e6e5df", "#dcdbd4"
plt.rcParams.update({"font.size": 8, "font.family": "DejaVu Sans"})
R = Path(sys.argv[1])
F = json.load(open(R / "final.json"))
P = "FP1-FP2"
f = F[P]["methods"]
out = Path("figures"); out.mkdir(exist_ok=True)


def style(ax, ygrid=True):
    ax.spines[["top", "right"]].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED); ax.spines[s].set_linewidth(0.6)
    ax.tick_params(colors=MUTED, labelsize=7.5)
    if ygrid:
        ax.grid(axis="y", color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)


def front(pts):
    order = np.argsort(pts[:, 0]); fr = []; best = -1
    for i in order:
        if pts[i, 1] > best:
            fr.append(pts[i]); best = pts[i, 1]
    return np.array(fr)


# ── 1. operating curve ──────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(3.45, 2.7))
for sig, col, lab in (("LL", C_LL, "LL-BR"), ("DEV", C_DEV, "DEV-BR")):
    pts = np.array([(g["fa_per_hour"], 100 * g["sensitivity"]) for g in F[P]["grid"][sig]])
    pts = pts[pts[:, 0] > 0]
    fr = front(pts)
    ax.plot(fr[:, 0], fr[:, 1], color=col, linewidth=1.3, label=f"{lab} (all settings, in-sample)")
cv = np.array([(f[k]["fa_per_hour"], 100 * f[k]["sensitivity"]) for k in ("DEV_1.0", "DEV_0.5", "DEV_0.2")])
ax.scatter(cv[:, 0], cv[:, 1], marker="D", s=24, facecolor="white", edgecolor=C_DEV, linewidth=1.3, zorder=6,
           label="DEV-BR, held-out patients")
for k, col, name in (("py_blackout", C_PY, "Analyzer BLACKOUT (shipped)"), ("py_any", C_PY, None),
                     ("fw_blackout", C_FW, "Firmware BLACKOUT (shipped)")):
    v = f[k]
    ax.scatter([v["fa_per_hour"]], [100 * v["sensitivity"]], s=40, color=col, zorder=7, edgecolor="white",
               linewidth=1.1, marker="o" if k != "py_any" else "s", label=name or "Analyzer any alarm (shipped)")
    ax.plot([v["fa_per_hour"]] * 2, [100 * v["chance"], 100 * v["sensitivity"]], color=col, linewidth=0.7,
            linestyle=":", zorder=5)
    ax.scatter([v["fa_per_hour"]], [100 * v["chance"]], s=28, marker="_", color=col, zorder=7, linewidth=1.5)
ax.set_xscale("log"); ax.set_xlim(0.05, 40); ax.set_ylim(0, 100)
ax.set_xlabel("False alarms per hour", fontsize=8); ax.set_ylabel("Seizures detected (%)", fontsize=8)
style(ax)
ax.legend(frameon=False, fontsize=5.9, loc="upper left", handletextpad=0.3, borderaxespad=0.1, labelspacing=0.3)
fig.tight_layout(pad=0.3); fig.savefig(out / "operating_curve.png", dpi=300); plt.close(fig)

# ── 2. per-patient sensitivity ──────────────────────────────────────────────
cases = sorted(f["DEV_1.0"]["per_case"])
def sens(k):
    pc = f[k]["per_case"]; return [100 * pc[c]["n_det"] / pc[c]["n_sz"] if c in pc else np.nan for c in cases]
x = np.arange(len(cases)); w = 0.27
fig, ax = plt.subplots(figsize=(7.1, 1.75))
for off, k, col, lab in ((-w, "py_any", C_PY, f"Analyzer, any alarm (shipped; {f['py_any']['fa_per_hour']:.2f} FA/h)"),
                         (0, "DEV_1.0", C_DEV, f"DEV-BR, held-out ({f['DEV_1.0']['fa_per_hour']:.2f} FA/h)"),
                         (w, "fw_blackout", C_FW, f"Firmware BLACKOUT (shipped; {f['fw_blackout']['fa_per_hour']:.1f} FA/h)")):
    ax.bar(x + off, sens(k), w - 0.04, color=col, label=lab)
ax.set_xticks(x); ax.set_xticklabels(cases, rotation=60, fontsize=6.5, ha="right", rotation_mode="anchor")
ax.set_ylabel("Sensitivity (%)", fontsize=7.5); ax.set_ylim(0, 100)
style(ax)
ax.legend(frameon=False, fontsize=6.5, ncol=3, loc="lower left", bbox_to_anchor=(0, 1.0), handletextpad=0.4)
fig.tight_layout(pad=0.3); fig.savefig(out / "per_patient.png", dpi=300); plt.close(fig)

# ── 3. DEV-BR illustration on one seizure ───────────────────────────────────
import personalize as PZ
rows = [json.loads(l) for l in (R / "records.jsonl").read_text().splitlines() if l.strip()]
rows = [r for r in rows if r["channel"] == P and not r.get("missing") and r["seizures"]]
r_, D_ = None, None
rr, D = f["DEV_1.0"]["chosen"][0][1], f["DEV_1.0"]["chosen"][0][2]
th = np.log(rr)
for r in sorted(rows, key=lambda r: r["record"]):
    on, off = r["seizures"][0]
    if on < 900 or off - on < 30:
        continue
    S = PZ.scores_for(R / "features" / f"{r['record']}_{P}.npz", r["duration_s"])
    al = PZ.alarms(S["DEV"], th, D)
    hit = [a_ for a_ in al if on - 30 <= a_ <= off + 60]
    fa = [a_ for a_ in al if abs(a_ - on) < 900 and not (on - 30 <= a_ <= off + 60)]
    if hit and not fa:
        r_, S_, al_ = r, S, al
        break
z = np.load(R / "features" / f"{r_['record']}_{P}.npz")
n = int(r_["duration_s"])
dev = PZ.per_second(z["fw_t10"], z["fw_diff10"], n)
import pandas as pd
bg = pd.Series(dev).rolling(PZ.BG_WIN, min_periods=PZ.BG_WIN // 2).median().shift(PZ.BG_LAG).to_numpy()
on, off = r_["seizures"][0]
t0, t1 = int(on - 420), int(off + 300)
tt = np.arange(t0, t1)
fig, axs = plt.subplots(2, 1, figsize=(3.45, 2.6), sharex=True, gridspec_kw=dict(height_ratios=[1.1, 1]))
for ax in axs:
    ax.axvspan(on, off, color=SZ, zorder=0, linewidth=0)
axs[0].plot(tt, dev[t0:t1], color=INK, linewidth=0.7, label="DEV (1-s mean)")
axs[0].plot(tt, bg[t0:t1], color=C_DEV, linewidth=1.2, label="lagged median baseline")
axs[0].set_yscale("log"); axs[0].set_ylabel("ADC units", fontsize=7.5)
axs[0].legend(frameon=False, fontsize=6, loc="upper left")
ratio = np.exp(S_["DEV"][t0:t1])
axs[1].plot(tt, ratio, color=INK, linewidth=0.7)
axs[1].axhline(rr, color=C_DEV, linewidth=1.0, linestyle="--")
axs[1].text(t0 + 5, np.nanmax(ratio) * 0.72, f"threshold r = {rr},\nheld for D = {D} s", color=C_DEV, fontsize=6.3, va="top")
for a_ in al_:
    if t0 <= a_ <= t1:
        axs[1].axvline(a_, color=C_FW, linewidth=1.3)
        axs[1].text(off + 25, np.nanmax(ratio) * 0.8, f"alarm {a_ - on:+.0f} s\nafter onset", color=C_FW, fontsize=6.3, va="top")
axs[1].set_ylabel("DEV / baseline", fontsize=7.5); axs[1].set_xlabel(f"time in {r_['record']} (s)", fontsize=7.5)
for ax in axs:
    style(ax, ygrid=False)
fig.tight_layout(pad=0.3); fig.savefig(out / "devbr_example.png", dpi=300); plt.close(fig)
print("example:", r_["record"], r_["seizures"][0], "alarms", [a for a in al_ if t0 <= a <= t1])

src = R / "figures" / f"feature_distributions_{P}.png"
shutil.copy(src, out / "feature_distributions.png")
print("figures written")
