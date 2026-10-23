# SeizeIT2 evaluation (EEG + head motion)

SeizeIT2 (Bhagubai et al. 2025; OpenNeuro ds005873, CC0): 125 patients, 2,850 recordings, 11,626 h, 883 annotated seizures, behind-the-ear EEG (256 Hz) and a neck-worn accelerometer/gyroscope (25 Hz). 386 recordings have no head-motion channel.

| Script | Does |
|---|---|
| `s2_extract.py` | Streams each recording from OpenNeuro, runs the EEG through the device front-end model and the firmware port, computes the motion features, and keeps per-second features only |
| `s2_fix_mov.py` | Re-extracts motion for recordings that have the accelerometer but no gyroscope |
| `s2_eval.py` | Leave-one-patient-out evaluation: initial firmware, EEG detector, motion detector, EEG-or-motion, EEG-and-motion, convulsive (FBTC) mode, chance levels, Wilcoxon tests |
| `s2_tc_detail.py` | FBTC-level bootstrap CI, latency, sleep and McNemar (all recordings; superseded for the paper by the audit scripts below) |
| `audit_s2.py` | Audit re-analysis of the convulsive mode on recordings **with** a motion channel, FBTC-specific chance level, patient-level paired tests |
| `audit_s2_detail.py` | Latency, sleep, zero-false-alarm patients and parameter choices for the audit analysis |
| `audit_s2_defaults.py` | Firmware default convulsive parameters applied to the motion subset (in-sample, not held out) |
| `verify_cpp_detector.py` | Checks `firmware/eeg_motion/.../baseline_detector.h` against `s2_eval.py` |

Outputs are in `../results/` (`s2_results.json`, `s2_tc_detail.json`, `verify_cpp.json`, `seizeit2_meta.jsonl`) and `../results/audit/`. The scripts import `chbmit.py`, `detectors.py`, `scoring.py` and `rigor.py` from the parent folder.

Notes: the convulsive mode, its grid and its targets were defined after the general mode was examined, so its results are exploratory; the paper's numbers are the audit ones (`../results/audit/audit_s2*.json`).
