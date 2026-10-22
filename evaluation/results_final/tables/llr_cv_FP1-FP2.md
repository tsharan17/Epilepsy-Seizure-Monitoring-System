# LL-ratio detector — patient-wise 2-fold CV (FP1-FP2)

| FA/h target (train) | Fold → params | Held-out sens. | Held-out FA/h | Held-out latency median (s) |
|---|---|---|---|---|
| ≤ 1.0 | fold0: r=2.0, D=15s; fold1: r=6.0, D=2s | 53/194 (27.3%) | 0.98 | 20.0 |
| ≤ 0.5 | fold0: r=2.5, D=15s; fold1: r=3.5, D=10s | 47/194 (24.2%) | 0.47 | 25.0 |
| ≤ 0.2 | fold0: r=3.0, D=15s; fold1: r=5.0, D=10s | 37/194 (19.1%) | 0.25 | 27.0 |
