# ICLT 2026 submission audit (22 Oct 2026)

Revised manuscript: `paper_v2/iclt2026_revised.pdf` (6 pages, US letter, IEEEtran conference).
The previous manuscript (`paper/main.tex`, `paper/iclt2026_paper.pdf`) is preserved unchanged.

## 0. Submission route (checked on ieeeiclt2026.com, 22 Oct 2026)

| Item | Official rule | Consequence |
|---|---|---|
| Initial submission length | "2-page, or up to 6-page for full papers and 1page for poster-papers, including appendix, references, and all other contents" | Full paper ≤ 6 pages **including references** → revised paper is exactly 6. |
| 4-page rule | Final version limited to 4 pages "if you are selected to submit the paper to the Transactions on Consumer Electronics or if you intend to submit a full length of your paper to any of the Associated Journals. Otherwise, the length is up to 6 pages." | Applies only after selection, or if you choose the associated-journal route. **Not applicable to the initial submission.** A 4-page version (`main4.tex` → `iclt2026_4page.pdf`) is ready for that case; submit the 6-page paper now. |
| Template / paper size | IEEE conference template (Word or LaTeX), US letter, no author biographies | Met (`IEEEtran` conference, letterpaper). |
| Review anonymity | Authors need not remove names | Names kept. |
| PDF | Initial: no PDF eXpress needed. Final: PDF eXpress (Conference ID **67443X**) then upload to EDAS; IEEE copyright form via EDAS | Do this at camera-ready. |
| Deadlines | Regular paper **30 Oct 2026** (extended); poster 1 Nov; notification 15 Nov; conference 14–16 Dec | — |
| Submission system | EDAS: https://edas.info/N35554 | — |
| Ambiguities | The flyer says posters are 2 pages; the website says 1 page. The page gives no abstract/keyword rules or Xplore statement. | Not relevant to a full paper; check EDAS when submitting. |

## C. Change log (substantive revisions)

| # | Change | Reason |
|---|---|---|
| 1 | **Title** → "A Low-Cost Single-Channel EEG Seizure Alarm: Code-Faithful Evaluation and an Embedded Baseline-Ratio Detector" | The old title made "gain-invariant" its central claim, but that had not been measured for DEV-BR; the new title puts the hardware first. |
| 2 | **Primary validation → leave-one-subject-out (LOSO)**, 23 subjects; chb01 and chb21 merged into one subject everywhere (folds, bootstrap, Wilcoxon). | The old 2-fold split by case number kept chb01/21 together but bootstrapped and tested over 24 *cases*, not subjects. |
| 3 | **Nested signal selection** (LL/DEV/FUSE chosen inside each training fold). DEV was chosen in 69/69 folds on FP1–FP2. | DEV had been picked after seeing held-out results; nesting removes that selection bias. |
| 4 | **Parameter grid widened** (r adds 1.25, 1.75; D adds 30 s). | The old grid's optimum sat at its edge. |
| 5 | **Headline numbers changed** (FP1–FP2, ≤1 FA/h): **old** 47.4 % (CI 30–71) at 0.87 FA/h (2-fold, old grid) → **new** 52.1 % (CI 36–74) at 0.97 FA/h (LOSO). ≤0.5 FA/h: old 41.8 % @ 0.40 → new 41.8 % @ 0.46. The 2-fold split re-run on the new grid gives 52.1 % @ 0.95. All are reported in the paper. | Consequence of #2–#4; nothing is replaced silently. |
| 6 | **Chance level**: Poisson formula → **empirical circular-shift null** (1000 permutations), which preserves alarm count and spacing. Firmware chance: 51.5 % (Poisson) → 56.6 % (empirical). | Firmware alarms are clustered, so the Poisson assumption does not hold. |
| 7 | **Subject-macro sensitivity** added next to pooled sensitivity. | chb12 contributes 40 of 194 seizures (21 %). |
| 8 | **Ablations** added (lag 0/10/60 s, window 60/120/600 s, mean vs median, no normalization). | Requested; result: normalization is essential (52 % → 33 % without it), and the median is not essential (mean ≈ same). |
| 9 | **Equations corrected** to match code: baseline over seconds **[t−329, t−30]** (old text: t−330 ≤ τ < t−30), alarm stamped at **t+1**, 90-s suppression, no alarms before 330 s. | Exact match to `personalize.py` / `rigor.py`. |
| 10 | **Memory claim** "≈1 KB / 1.2 KB" → **2.5 KB**, measured from an actual C++ implementation (`firmware_devbr/devbr.h`) that reproduces all 800/800 Python alarm lists. | The earlier figure was an estimate that ignored the lag history and the sort scratch. |
| 11 | **"We are moving DEV-BR into the firmware" removed.** Replaced with "has not yet been integrated or timed on the ESP32". | Not done. |
| 12 | **Implementation-status table (Table I)** added: built / firmware / replay-evaluated / binary-only / verified offline / not measured. | Requested separation of built, simulated and proposed parts. |
| 13 | **Hardware limitations disclosed**: LM358 headroom ≈150 mV at 3.3 V (datasheet), BioAmp run at 3.3 V (vendor documents 5 V), default ESP32 ADC attenuation, `delay(5)`-paced sampling. | Found in the code and schematic audit. |
| 14 | **Bench TODOs removed** from the text (noise, battery life, BOM); now stated as "not measured". | No measurements exist; none were invented. |
| 15 | **Gain-invariance claim narrowed** to constant scaling absent quantization or saturation; robustness test moved to an add-on notebook (`evaluation/vera_hw_robustness.ipynb`). The paper switches automatically to a results table once `hw_robustness.json` exists. | Not yet measured for DEV-BR. |
| 16 | **Novelty reframed**: cites Logesparan et al. 2011/2015 (line-length normalization with median/delayed memories). DEV-BR is presented as an application to the firmware's existing signal, not a new principle. | Prior art found in the reference audit. |
| 17 | **Clinical comparison made explicit**: about 23 false alarms/day versus 0.2–0.67/day for phase-3 GTCS wearables (ILAE–IFCN guideline). | Avoids overclaiming. |
| 18 | **Personalization paragraph removed.** | It was a 2-fold-only, inconsistent effect; it doesn't fit the page budget and wasn't re-validated. Code and results are kept in `evaluation/`. |
| 19 | **HFE explanation softened** to "plausible but untested". | Speculative. |
| 20 | **References fully verified** (Crossref / publisher). Fixes: Beniczky co-author "Yuping" Wang (not "Yiping"); SzCORE now the Epilepsia 66(S3):14–24 journal version; Frey pages 105–114; DOIs added; Logesparan ×2 and the TI LM358 datasheet added. All `% VERIFY` markers resolved. | Requested. |
| 21 | **Dataset description corrected**: "24 cases, mostly pediatric, 1.5–22 y"; chb24 has no subject info; seizure-free files are one per case (two for chb01, none for chb24). | Matches PhysioNet and the data actually used. |
| 22 | **Secondary-channel results now LOSO**, and the paper states that DEV-BR's advantage over LL-BR is **not significant** on FP1-F7/FP2-F8 (p ≈ 0.06). | Honest reporting. |
| 23 | **In-sample trade-off curve recomputed** on the CV grid. | Previously the held-out point lay above the in-sample frontier, which is impossible on a consistent grid. |
| 24 | **Hardware-robustness results added (Table IV)** from the Kaggle add-on run: gains ×500/×1000/×2000, LM358 1.8-V ceiling at ×1000 and ×2000, 3.1-V ADC range, 166.7-Hz loop. DEV-BR with frozen parameters: 50.0–52.1 % at 0.93–0.98 FA/h. Shipped firmware: 45.9–86.1 % at 7.36–24.37 FA/h. | Resolves former E2. Simulation only; stated as such. |
| 25 | **Title** → "…Code-Faithful Evaluation and a Hardware-Robust Embedded Detector". | "Hardware-robust" is now supported by Table IV (in simulation; the text says so). |
| 26 | **Alternative detectors tested and reported** (Table III, bottom): k-of-n persistence, dual time-scale rule, baseline carried across contiguous files, logistic regression (firmware-only and all features), gradient-boosted trees, all LOSO with inner-CV thresholds (`evaluation/variants.py`, `evaluation/fusion.py`). None consistently beat DEV-BR; boosted trees 44.3 % vs 41.8 % at ≤0.5 FA/h, not significant (4 better / 2 worse, p = 0.25), worse at ≤1 FA/h. | Requested attempt at a stronger classifier; reported whether or not it helped. |
| 27 | **Design principles** stated in the Discussion (validate shipped code; normalize to the wearer's delayed background; stop adding complexity once the signal is the bottleneck), and a positive but bounded conclusion. | Requested framing; every statement backed by Tables II–IV, limitations unchanged. |
| 28 | **Per-subject figure removed** from the 6-page paper to make room for Table IV (the per-subject Wilcoxon counts remain in the text). | Page limit. |
| 29 | **4-page version** `main4.tex` added (same `numbers.tex` / `refs.bib`; 11 references; no feature-distribution figure, shorter related work and limitations). | Only needed for the TCE / associated-journal route. |

## D. Experimental audit table

| Manuscript claim | Evidence in code / data | Verified? | Remaining issue |
|---|---|---|---|
| FP1+/FP2−, earlobe ground, BioAmp → LM358 → RC → ESP32 GPIO34 | `circuit_diagram.png`; firmware `EEG_PIN 34` | Yes (design docs + code) | Physical build not inspected by me |
| Gain ≈1000, pass-band 0.5–40 Hz | Circuit diagram text only | **Nominal only** | Not measured; vendor docs don't state them |
| BioAmp supply 3.3 V | Circuit diagram | Yes (as designed) | Vendor documents 5-V use; 3.3-V behaviour unverified |
| LM358 headroom ≈150 mV | TI datasheet: CM range & VOH ≈ V+−1.5 V (5-V spec) | Datasheet-derived | Not measured; clipping effect simulated only in the add-on |
| ~200 Hz sampling | `delay(SAMPLE_DELAY_MS=5)` + loop work | Nominal | True rate < 200 Hz, unmeasured; replay assumes 5 ms |
| 12-bit ADC, default attenuation | No `analogSetAttenuation` call | Yes | Range ≈ 0–3.1 V and nonlinear; model assumes linear 3.3 V |
| Firmware detector (EMA 0.01, Welford 0.995, μ+2.5/4σ, clamps, 20/15 counts, 400 hold, 90-s warm-up, 30-s re-adapt) | `.ino` lines 37–88, 459–548 | Yes, line by line | — |
| Alarm outputs: LED, GPIO18 500-ms pulse, REST /status, /eeg, /simulate; open AP | `.ino` handlers | Yes | Fixed password `12345678` |
| Analyzer: LL/DAR/HFE, 2-of-3, 7/8 ticks, floors 300/600, artifact 1500, freeze | `seizure_monitor.py` | Yes | `min_state_hold` defined but unused (not claimed) |
| Companion app features | README + APK only | **Not verifiable** | Flutter source absent from repo |
| Replay runs analyzer unmodified | `detectors.run_python_detector` (monkey-patched clock/serial; md5 of the file = GitHub version) | Yes | — |
| Firmware port faithful | `detectors._fw_loop` vs `.ino` | Yes (manual line check) | Not cross-checked against a hardware serial log |
| FP1–FP2 exact reconstruction | `fetch_chbmit._bipolar_path`; synthetic EDF test: max error 0.44 µV | Yes | — |
| 165 rec / 198 sz / 225.5 h; FP1–FP2 160 / 194 / 220.5 | `records.jsonl`, `fetch_log.jsonl` | Yes | — |
| 23 subjects, no subject leakage | `rigor.subject()`; LOSO folds by subject | Yes | chb24 subject identity unknown (treated as distinct) |
| Scoring: [on−30, off+60], 90-s merge, FA = unmatched alarms, FA/h over total time | `scoring.py` | Yes | Merge is relative to last *kept* alarm (SzCORE-compatible) |
| Analyzer 5.7 % @ 0.32 FA/h; firmware 75.3 % @ 18.29 | `rigor_FP1-FP2.json` | Yes | — |
| DEV-BR 52.1 % [36–74] @ 0.97 (LOSO) | `rigor_FP1-FP2.json` | Yes | 15 seizures fall in the 330-s cold start (54.2 % when excluded) |
| 21/23 better, 0 worse (p = 6×10⁻⁵) | `rigor` tests (Wilcoxon on subject sensitivities) | Yes | 2 ties dropped by Wilcoxon (default zero-method) |
| Empirical null p = 0.001 | 1000 circular shifts | Yes | 0.001 is the floor at 1000 permutations |
| Feature AUCs (LL 0.70, DEV 0.70, DAR 0.51, HFE 0.40) | `summary.json` (report.py) | Yes | Inter-ictal samples subsampled 10 % for the pooled AUC |
| Analyzer gain dependence 0.0 / 5.7 / 13.4 % | `gain_sweep.json` | Yes | — |
| DEV-BR gain invariance | Argument only | **Not measured** | Run `vera_hw_robustness.ipynb` |
| C++ DEV-BR = Python, 2.5 KB | `firmware_devbr/` harness: 800/800 identical | Yes (host, g++) | Not compiled for ESP32; not timed |
| Bench noise, battery life, BOM | none | **Absent** | Measure or leave out (paper says "not measured") |

### Dataset accounting (verified)

| Stage | Recordings | Seizures | Hours | Note |
|---|---|---|---|---|
| CHB-MIT recordings containing seizures | 141 | 198 | — | 24 cases |
| + seizure-free recordings | +24 | — | — | 1 per case; 2 for chb01; 0 for chb24 |
| Fetched & extracted (FP1-F7, FP2-F8) | 165 | 198 | 225.5 | 0 fetch errors; chb12_27–29 referential, handled |
| FP1–FP2 chain unavailable | −5 | −4 | −5.0 | chb13_40 (2 sz), chb16_18 (2 sz), chb15_01, chb18_01, chb19_01 |
| **FP1–FP2 primary set** | **160** | **194** | **220.5** | 23 subjects (chb01 + chb21 merged) |
| of which onset < 335 s (BR cold start) | — | 15 | — | reported |

## E. Unresolved issues (need you or another run)

1. **Push the new code to GitHub before submitting.** The paper's data-availability statement points to the repo, but `evaluation/`, `firmware_devbr/` and `paper_v2/` are currently untracked locally.
2. ~~Run the hardware-robustness notebook~~ — **done** (change log #24).
3. **Bench measurements** (optional for the initial submission, strongly recommended): actual sampling rate (count samples per `millis()` second), input-referred noise with shorted inputs, the BioAmp output DC level at 3.3 V, and the LM358 output ceiling. If measured, I'll add them; if not, the paper already says "not measured".
4. **Decide whether to fix the LM358 issue now** (e.g., a rail-to-rail buffer such as MCP6002, or remove the buffer). If changed, the paper's hardware description must change too.
5. **4-page route**: version prepared (`iclt2026_4page.pdf`); use only if selected for TCE or if you choose an associated journal.
6. **Acknowledgment**: add a guide or funding source if applicable. Keep the AI-use disclosure, which IEEE requires.
7. **Companion app**: either publish the Flutter source or keep the paper's "binary only; not evaluated".
8. **Optional strengthening** (not done): continuous multi-file replay to remove the cold-start penalty; comparison with one published lightweight detector (e.g., a Gotman-style detector); a hardware-in-the-loop replay through the ESP32 (DAC → ADC).

## F. IEEE / ICLT submission checklist

- [x] IEEE conference template (IEEEtran), US letter, two columns, ≤ 6 pages including references
- [x] Author names and affiliations present (allowed); no biographies
- [x] Abstract (single paragraph, no citations) and Index Terms
- [x] All figures referenced in the text, legible at print size; all tables have captions above
- [x] References complete, verified, with DOIs where available; no `% VERIFY` left
- [x] No placeholder text or [TODO] in the PDF (checked)
- [x] AI-use disclosure in the Acknowledgment
- [ ] Code pushed to GitHub so the data-availability statement is true
- [x] Hardware-robustness add-on run and Table IV regenerated
- [x] Fonts embedded (checked with `pdffonts`; all Type 1, embedded). PDF eXpress is only required at the final stage
- [ ] Submit on EDAS (https://edas.info/N35554) before 30 Oct 2026
- [ ] Final stage: PDF eXpress (ID 67443X) → EDAS upload → IEEE copyright form

## G. Reviewer-risk assessment (candid)

Most likely reasons for rejection, most serious first:
1. **No device data.** Every number comes from simulated replay of a clinical database; there is no recording, bench test or user study from the prototype. A consumer-technology venue may see the hardware contribution as unvalidated. *Mitigation:* the status table and limitations are explicit; bench measurements (item E3) would help most.
2. **Modest absolute performance.** About 52 % sensitivity at about 23 false alarms per day is far from clinical utility, and reviewers may question practical value. *Mitigation:* the paper frames the result as a validated improvement and a validation method, not a usable clinical alarm.
3. **Limited novelty of DEV-BR.** Baseline-normalized line-length is prior art (Logesparan 2011/2015). A reviewer may see DEV-BR as an incremental application. *Mitigation:* the novelty is reframed around code-faithful evaluation plus an embedded, verified implementation.
4. **Hardware design questions.** LM358 headroom at 3.3 V and BioAmp operation below its documented supply may draw criticism. *Mitigation:* disclosed; the add-on quantifies clipping sensitivity in simulation.
5. **Dataset fit.** A pediatric, clinical-amplifier dataset and a frontal channel the dataset never recorded directly (reconstructed). *Mitigation:* reconstruction is exact and secondary channels are reported.
6. **Simulated, not measured, robustness.** Table IV is a simulation. *Mitigation:* stated in the caption and limitations; bench item E3 would confirm it.

Overall: the paper is scientifically defensible as written and within the rules, but it is **not fully submission-ready until item E1 (push code) is done**. Acceptance cannot be predicted; the main risks are 1–3, and none can be removed without new measurements.
