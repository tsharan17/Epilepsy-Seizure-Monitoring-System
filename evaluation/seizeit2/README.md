# SeizeIT2 evaluation (multimodal, firmware v5)

SeizeIT2 (Bhagubai et al. 2025; OpenNeuro ds005873, CC0): 125 patients, 2,850 recordings, 11,626 h,
883 annotated seizures, behind-the-ear EEG (256 Hz) and a neck-worn accelerometer/gyroscope (25 Hz).

| script | does |
|---|---|
| `s2_extract.py` | streams each recording from OpenNeuro, runs the EEG through the device front-end model and the line-by-line v4 firmware port, computes the v5 motion features; keeps per-second features only |
| `s2_fix_mov.py` | re-extracts motion for recordings that have the neck accelerometer but no gyroscope |
| `s2_eval.py` | leave-one-patient-out evaluation: shipped firmware, DEV-BR, MOV-BR, OR-fusion, AND co-activation, convulsive (FBTC) mode, chance levels, Wilcoxon tests |
| `s2_tc_detail.py` | FBTC-level bootstrap CI, latency, sleep, McNemar tests |
| `verify_vera_cpp.py` | checks `firmware_v5/seizure_monitor_v5/vera_detect.h` against `s2_eval.py` |

Results: `../results_final/s2_results.json`, `s2_tc_detail.json`, `verify_cpp.json`, `seizeit2_meta.jsonl`.
The scripts import `chbmit.py`, `detectors.py`, `scoring.py`, `rigor.py` from `evaluation/` (set by `EV` at the top).
