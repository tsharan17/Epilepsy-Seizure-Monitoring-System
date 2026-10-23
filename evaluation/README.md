# Evaluation

Replay of public, expert-annotated recordings through the Vera detectors, scored with event-based (SzCORE-style) rules. Everything here is **software replay**: public recordings are converted to the device's signals (front-end model, 200 Hz, 12-bit) and fed to the unmodified `analyzer/seizure_monitor.py` and a line-by-line Python/numba port of the firmware loop.

| Folder / file | What it is |
|---|---|
| `seizeit2/` | SeizeIT2 evaluation (EEG + head motion, 125 patients) and its audit re-analysis — see its README |
| `audit/` | Checks of the CHB-MIT FP1–FP2 derivation — see its README |
| `results/` | Stored outputs used by the paper (JSON, tables); `results/audit/` holds the audit outputs |
| `notebooks/` | Original Kaggle notebooks (CHB-MIT evaluation; front-end robustness simulation) |
| `fetch_chbmit.py` | Downloads CHB-MIT EDFs, keeps FP1-F7, FP2-F8 and a *derived* FP1–FP2 (signed sum of a chain of bipolar channels), then deletes each EDF |
| `chbmit.py` | Summary parsing and the front-end model (µV → 0.5–40 Hz → 200 Hz → ×1000 → 12-bit ADC) |
| `detectors.py` | Replays `seizure_monitor.py` unmodified (fake serial + simulated clock) plus the line-by-line firmware port |
| `scoring.py` | Event scoring: an alarm in [onset−30 s, offset+60 s] is a detection; alarms < 90 s apart are merged |
| `run_eval.py` | Replays every recording; writes `records.jsonl` and per-tick feature traces |
| `report.py`, `final_analysis.py` | Main tables, per-patient results, feature AUCs, figures, chance baselines |
| `rigor.py` | Leave-one-subject-out validation, subject bootstrap, circular-shift chance, ablations |
| `variants.py`, `fusion.py`, `personalize.py`, `multich.py`, `ablation.py`, `ingrid.py` | Additional analyses (detector variants, feature fusion, personalization, multi-channel, grids) |
| `hw_robustness.py` | Front-end robustness **simulation** (gain, clipping, ADC range, loop rate) |

## FP1–FP2 on CHB-MIT

CHB-MIT has no FP1–FP2 channel. `fetch_chbmit.py` derives it as FP1-F7 + F7-T7 + T7-FT9 + FT9-FT10 + FT10-T8 − (F8-T8) − (FP2-F8), which equals FP1−FP2 only if all channels share one reference and identical filtering. That cannot be confirmed from the dataset; see `audit/README.md` for the checks that were run.

## Run locally

```
pip install numpy scipy pandas numba matplotlib requests pyserial
python fetch_chbmit.py --out ../data/chbmit
python run_eval.py --data ../data/chbmit --monitor ../analyzer/seizure_monitor.py --out results/records.jsonl
python report.py --results results --data ../data/chbmit
python rigor.py --results results --channel FP1-FP2
```

Downloading needs about 6 GB of traffic and the replay is CPU-heavy; the Kaggle notebook in `notebooks/` runs it in the cloud (about 4–5 hours).

## Data citations

Shoeb, A. *Application of Machine Learning to Epileptic Seizure Onset Detection and Treatment.* PhD thesis, MIT, 2009.
Goldberger, A. et al. PhysioBank, PhysioToolkit, and PhysioNet. *Circulation* 101(23):e215–e220, 2000.
Bhagubai, M. et al. SeizeIT2: wearable dataset of patients with focal epilepsy. arXiv:2502.01224, 2025 (OpenNeuro ds005873).
