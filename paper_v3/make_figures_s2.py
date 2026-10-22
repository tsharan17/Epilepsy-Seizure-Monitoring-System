"""SeizeIT2 figure: (a) general mode by seizure class, (b) convulsive mode FBTC sensitivity vs false alarms/day."""
import json, sys
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, numpy as np
from pathlib import Path
R = Path(sys.argv[1]); D = json.load(open(R / "s2_results.json")); T = json.load(open(R / "s2_tc_detail.json"))
M = D["methods"]
fig, (a, b) = plt.subplots(1, 2, figsize=(7.2, 2.35), dpi=300, gridspec_kw=dict(width_ratios=[1.35, 1]))
cls = [("FBTC/generalized", "FBTC"), ("focal motor", "focal\nmotor"), ("focal non-motor", "focal\nnon-motor"), ("vig:asleep", "during\nsleep")]
meths = [("FW", "shipped firmware\n(7.0 FA/h)", "#bbbbbb"), ("EEG_1.0", "EEG DEV-BR", "#4c72b0"), ("MOV_1.0", "motion MOV-BR", "#dd8452"), ("FUSED_1.0", "EEG or motion", "#55a868")]
x = np.arange(len(cls)); w = 0.2
for j, (k, lab, col) in enumerate(meths):
    v = [100 * M[k]["by_class"][c]["sens"] for c, _ in cls]
    a.bar(x + (j - 1.5) * w, v, w, color=col, label=lab, edgecolor="none")
a.set_xticks(x); a.set_xticklabels([l for _, l in cls], fontsize=6.5)
a.set_ylabel("Seizures detected (%)", fontsize=7); a.set_ylim(0, 105); a.tick_params(labelsize=6.5)
a.set_title("(a) general mode, $\\leq$1 FA/h (held-out patients)", fontsize=7.2)
a.legend(fontsize=5.6, frameon=False, ncol=2, loc="upper right")
for s in ("top", "right"): a.spines[s].set_visible(False)
# (b) convulsive mode: FBTC sensitivity vs FA/day for each target
tc = D["tc"]
for nm, lab, col, mk in (("EEG", "EEG only", "#4c72b0", "o"), ("MOV", "motion only", "#dd8452", "s"), ("COACT", "EEG AND motion", "#c44e52", "D")):
    pts = sorted((tc[f"{nm}_{t}"]["fa_per_day"], 100 * tc[f"{nm}_{t}"]["by_class"]["FBTC/generalized"]["sens"]) for t in (0.02, 0.05, 0.1, 0.2))
    b.plot([p[0] for p in pts], [p[1] for p in pts], marker=mk, ms=3.5, lw=1, color=col, label=lab)
b.axvspan(0.2, 0.67, color="#999", alpha=0.18, lw=0)
b.text(0.43, 6, "phase-3\nwearables\nFA range", fontsize=5.3, ha="center", color="#444")
b.set_xscale("log"); b.set_xlim(0.18, 6); b.set_ylim(0, 100)
b.set_xticks([0.25, 0.5, 1, 2, 4]); b.set_xticklabels(["0.25", "0.5", "1", "2", "4"])
from matplotlib.ticker import NullFormatter, NullLocator
b.xaxis.set_minor_formatter(NullFormatter()); b.xaxis.set_minor_locator(NullLocator())
b.set_xlabel("False alarms per day", fontsize=7); b.set_ylabel("FBTC detected (%)", fontsize=7); b.tick_params(labelsize=6.5)
b.set_title(f"(b) convulsive mode ({T['COACT_0.02']['n']} FBTC, {T['COACT_0.02']['n_subj']} patients)", fontsize=7.2)
b.legend(fontsize=5.8, frameon=False, loc="lower right")
for s in ("top", "right"): b.spines[s].set_visible(False)
plt.tight_layout(w_pad=1.2)
plt.savefig(Path(__file__).parent / "figures" / "seizeit2_results.png", bbox_inches="tight", pad_inches=0.02)
print("ok")
