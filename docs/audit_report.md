# Audit report and change log, paper (23 Oct 2026)

Venue verified (ieeeiclt2026.com, 23 Oct 2026): **IEEE Consumer Life Tech Conference (ICLT 2026)**, Sydney, 14-16 Dec 2026, EDAS N35554, regular-paper deadline 30 Oct 2026.
Topics include biosignal processing, wearable sensors, consumer-grade health monitoring devices, brain-computer interfaces -> in scope.
Rules: initial full paper <= 6 pages incl. references/appendix; **4 pages only if selected for IEEE Trans. Consumer Electronics or submitted to an Associated Journal**, otherwise up to 6;
**not double-blind** (names/affiliations stay; no biographies); IEEE Word/LaTeX conference template, US letter; final: PDF eXpress (Conference ID 67443X) then EDAS, IEEE copyright form via EDAS.
The CFP PDF itself was not readable by my tools; the submission-guidelines page was. AI-use policy: not stated on the pages I could read; the paper discloses AI assistance anyway.
=> Submit the 6-page version. paper/main.tex is 6 pages (at the limit). No 4-page version is shipped: the old one carried outdated numbers; make it only if you are selected for TCE.

## 1. FP1-FP2 reconstruction (verdict: arithmetic correct, empirically consistent, NOT independently validated)
* CHB-MIT contains no FP1-FP2. Code: `fetch_chbmit.py::_bipolar_path`; chain FP1-F7 + F7-T7 + T7-FT9 + FT9-FT10 + FT10-T8 - (F8-T8) - (FP2-F8) telescopes to FP1-FP2 (checked algebraically and by BFS over each file's channel list).
* Valid only if all seven channels come from one common reference with identical filtering; PhysioNet does not document this and the dataset has no redundant path across the head to test it.
* Headers of all 686 EDFs read (`audit_data/headers.json`): chain in 157/165 analysed files; 3 chb12 files are referential (direct FP1-FP2, valid); 5 files (chb13/15/16/18/19) lack FT9-FT10 and were excluded (so 160 recordings, 194 seizures).
* Checks on 5 EDFs from 5 patients (`audit_data/recon_test.json`): identical calibration across chain; duplicate T8-P8 is a bit-identical copy; P7-T7 + T7-P7 = 1 LSB; blink amplitude in derived channel 0.13-0.41x of FP1-F7 (common-mode cancels) versus 0.86-2.03x for a wrong-sign chain -> polarity supported; quantisation noise <= 0.45 uV rms (below the device's 0.8 uV LSB).
* Detector features are sign-invariant, so polarity cannot change the results anyway.
* Paper change: "exact FP1-FP2" removed everywhere; now "derived/reconstructed", assumption and checks stated. Native FP1-F7 / FP2-F8 results exist (`rigor_FP1-F7.json`, `rigor_FP2-F8.json`) - consider adding them as a reconstruction-free check.

## 2. Evaluation code
Reproduced: `rigor.py` re-run on the stored features: **0 differences** from `rigor_FP1-FP2.json` (52.1% @ 0.97 FA/h, CI 36-74%, chance 6.5%, etc.).
Verified correct: LOSO excludes the held-out subject (chb21 merged with chb01); baseline is causal (shifted 30 s); alarm timing causal; subject-level bootstrap; chance by circular shift.
Findings (fixed in text unless marked):
| # | Finding | Action |
|---|---|---|
| A | Detector form, window/lag, signal choice and the convulsive mode/grids/targets were chosen after seeing the data; LOSO covers only (r, D). Convulsive grid widened after a first pass gave 64.5%. | Disclosed; convulsive results labelled exploratory; CIs called optimistic |
| B | CHB-MIT uses 160 of 686 recordings (220.5 h): seizure files + 1 seizure-free per patient. FA/h not continuous-wear. | Disclosed |
| C | SeizeIT2 "FBTC/generalized" class = exactly `sz_foc_f2b` (55); no generalized types. | Called FBTC (focal-to-bilateral) |
| D | Convulsive chance level was computed over ALL seizures, not FBTC. | Recomputed class-specific: 2.0% mean (p95 5.8%) |
| E | McNemar ignores within-patient correlation (p ~ 1e-7 overstated). | Replaced by patient-level sign test (p = 1.5e-5 vs EEG, 2.1e-5 vs motion) |
| F | Co-activation could not fire in 386 recordings with no motion channel but their hours counted. | Re-run on the 2,464 motion recordings (10,903 h): **38/52 = 73.1% [61-83] at 0.51 FA/day** (was 42/55 = 76.4% at 0.48); EEG 32.7%, motion 25.0% |
| G | Re-selection on motion subset picks r_E=6, r_M=3, D=30 (110/115 folds), not the firmware default (4, 8, 30). | Disclosed; defaults give 42/52 at 0.51/day but are NOT held out |
| H | Wilcoxon comparisons of sensitivity at different FA rates (e.g. shipped analyzer 0.32 FA/h vs DEV-BR 0.5) are not like-for-like. | Open: interpret as indicative only |
| I | Alarm merge compares with last kept alarm, not last raw alarm (SzCORE variant). | Open, minor |
Not reproducible here: SeizeIT2 general-mode LOSO table (took hours; not re-run, but produced by the same verified code path; C++ vs Python alarms identical on 2,850 recordings).

## 3. Evidence tiers (what the paper now claims)
* Built/measured hardware: **none**. EEG front-end = "prototype design, nominal values"; MPU9250 = "designed, in firmware; not built or tested". Gain/clipping/rate robustness reworded as simulation.
* Software replay: all CHB-MIT and SeizeIT2 results. Host-only: C++ detector bit-exactness. Compile-only: EEG-plus-motion firmware (792 KB flash). Untimed on ESP32.
* AUTHOR CHECK: confirm the EEG device really exists as described (Table I). If it does not, change "prototype design" to "design".

## 4. Other consistency fixes
Title -> "A Low-Cost EEG and Head-Motion Epilepsy Seizure Alarm with Baseline-Normalized Detection and Code-Faithful Evaluation". "We built" -> "We designed" (intro, conclusion). Contribution 1 states motion sensor unbuilt. Abstract/discussion/conclusion use the motion-subset numbers. Figure 4b regenerated from the audit data (two targets). New Table V. Limitation list extended.

## 5. Unresolved issues
1. Repo not pushed (paper cites it) - push `firmware`, `evaluation` (incl. `audit_data`), `paper` before submitting, or change the availability statement.
2. FP1-FP2 chain unverifiable from the dataset: keep wording; optionally add native-channel results.
3. Convulsive result is exploratory (n = 52 seizures, 36 patients, design chosen post hoc); no independent test set.
4. Dataset mismatch (behind-the-ear EEG, neck sensor) and hospital setting.
5. Not timed on ESP32; no hardware data.
6. Zhang 2024 / clinical-wearable numbers quoted from earlier checks; re-verify before camera-ready.
7. Wi-Fi password `12345678` in firmware.
8. If selected for TCE/associated journal: 4-page version needed.

## 6. Submission checklist
- [ ] Decide author check in section 3 (v4 device exists?)
- [ ] Push repo
- [ ] Compile in Overleaf, confirm 6 pages (US letter)
- [ ] EDAS N35554 by 30 Oct 2026; names stay on paper; no biography
- [ ] If accepted: PDF eXpress (ID 67443X), copyright form, final PDF

## Final check, 23 Oct 2026 (late)
* CORRECTED a wrong citation: Zhang et al. 2024 (arXiv:2403.13066) reports 97.7% sensitivity at 0.4 false positives/24 h for wearable EEG+EMG (27 participants, 44 tonic-clonic seizures); the earlier "95.5% at 1.1 FA/day for EEG+accelerometry" was not supported by the abstract (95.5% there is accelerometry alone with 13.9 FPR). Both mentions fixed.
* VERIFIED: ILAE/IFCN guideline (Epilepsia 2021, epi.16818): phase-3 wearables for GTC/FBTC seizures 90-96% sensitivity, 0.2-0.67 false alarms/24 h.
* VERIFIED: repository github.com/tsharan17/Epilepsy-Seizure-Monitoring-System is public; it has firmware, paper, evaluation; it does NOT yet contain paper or the audit scripts (audit_data) -> push before submitting.
* CHB-MIT comparison sentence fixed (41.8% at 0.46 FA/h vs analyzer 5.7% at 0.32 FA/h, flagged indicative since operating points differ).
* Added a plain statement of the contribution and of what is not new (baseline normalization is prior art).
