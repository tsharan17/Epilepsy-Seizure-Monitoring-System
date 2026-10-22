# ICLT 2026 — multimodal paper (EEG + MPU9250), paper_v3

* `iclt2026_multimodal.pdf` (`main.tex`) — 5 pages incl. references (limit 6). **Submit this one.**
* `iclt2026_multimodal_4page.pdf` (`main4.tex`) — 4-page version, only for the TCE / associated-journal route.
* `SUBMISSION_AUDIT.md` — what changed, where every number comes from, what you must do before submitting.
* `iclt2026_multimodal_overleaf.zip` — upload to Overleaf (New Project → Upload Project).
* The EEG-only paper stays in `../paper_v2/`.

All numbers are macros: `numbers.tex` (CHB-MIT, from `../paper_v2`) and `numbers_s2.tex` (SeizeIT2).

## Regenerate (cloud or any machine with ~80 GB of bandwidth; not needed for editing)
```
python ../evaluation/seizeit2/s2_extract.py S2OUT --workers 4   # streams OpenNeuro ds005873 (CC0), keeps ~0.5 GB of features
python ../evaluation/seizeit2/s2_fix_mov.py S2OUT                # recordings with accelerometer but no gyroscope
python ../evaluation/seizeit2/s2_eval.py S2OUT --perm 200        # LOSO, 125 patients -> s2_results.json
python ../evaluation/seizeit2/s2_tc_detail.py S2OUT              # FBTC detail -> s2_tc_detail.json
python ../evaluation/seizeit2/verify_vera_cpp.py S2OUT ../firmware_v5/test/vera_detect_test 100000 '[[2.0,20,24.0,20,0.4,4.0,8.0,30]]'
python make_numbers_s2.py S2OUT
python make_figures_s2.py S2OUT; python make_example_s2.py S2OUT; python make_hw_figure.py
```
(`s2_*.py` expect `../evaluation/` modules — `chbmit.py`, `detectors.py`, `scoring.py`, `rigor.py` — on the path; adjust `EV` at the top if you move them.)
