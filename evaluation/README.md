# Evaluation on CHB-MIT

This folder replays public, expert-annotated scalp EEG (CHB-MIT, PhysioNet) through Vera's two detectors and scores them.

| File | What it does |
|---|---|
| `vera_chbmit_evaluation.ipynb` | One-click Kaggle notebook. It downloads data on Kaggle, runs everything and zips the results. |
| `fetch_chbmit.py` | Downloads CHB-MIT EDFs, keeps FP1-F7, FP2-F8 and Vera's own FP1-FP2 (rebuilt exactly from a chain of bipolar channels), then deletes each EDF. |
| `chbmit.py` | Summary parsing and the front-end model (µV → 0.5–40 Hz → 200 Hz → ×1000 → 12-bit ADC). |
| `detectors.py` | Replays `seizure_monitor.py` unmodified (fake serial + simulated clock), plus a line-by-line port of the ESP32 `loop()`. |
| `scoring.py` | Event scoring. An alarm in [onset−30 s, offset+60 s] counts as a detection; alarms <90 s apart are merged. |
| `run_eval.py` | Replays every recording and writes `results/records.jsonl` and per-tick feature traces. |
| `report.py` | Builds the main tables, per-patient results, feature AUCs, figures and a chance-level baseline. |
| `ablation.py` | Proposed line-length-ratio detector, chosen by patient-wise 2-fold cross-validation. |

## Run on Kaggle (recommended)
1. kaggle.com → **Create → New Notebook → File → Import Notebook** → upload `vera_chbmit_evaluation.ipynb`.
2. Right panel: **Internet → On** (phone-verified account required). Accelerator: None.
3. **Save Version → Save & Run All (Commit)**. It runs in the background on Kaggle (about 4–5 h), and you can close the tab.
4. Open the finished version → **Output**, and download `vera_results.zip`.

## Run locally
```
pip install numpy scipy pandas numba matplotlib requests pyserial
python fetch_chbmit.py --out ../data/chbmit
python run_eval.py --data ../data/chbmit --monitor ../seizure_monitor.py --out results/records.jsonl
python report.py --results results --data ../data/chbmit
python ablation.py --results results
```
Downloading needs about 6 GB of traffic, and the replay is CPU-heavy, so Kaggle is the better option.

## Citation for the data
Shoeb, A. *Application of Machine Learning to Epileptic Seizure Onset Detection and Treatment.* PhD thesis, MIT, 2009.
Goldberger, A. et al. PhysioBank, PhysioToolkit, and PhysioNet. *Circulation* 101(23):e215–e220, 2000.
