# ICLT 2026 paper — revised version (paper_v2)

* `iclt2026_revised.pdf` — compiled paper (6 pages incl. references, US letter, IEEEtran conference).
* `SUBMISSION_AUDIT.md` — submission rules, change log, claim-by-claim audit, dataset accounting,
  unresolved issues, checklist, reviewer-risk assessment.
* The original manuscript is untouched in `../paper/`.

## Build (Overleaf or local)
Zip this folder → Overleaf **New Project → Upload Project**; main file `main.tex`, pdfLaTeX + BibTeX.

## Regenerating numbers and figures
All numbers are macros in `numbers.tex`. To rebuild from the evaluation outputs
(`<R>` = unzipped `vera_results.zip` with `vera_features.zip` unzipped into `<R>/features`):
```
python ../evaluation/rigor.py   --results <R> --channel FP1-FP2     # also FP1-F7, FP2-F8
python ../evaluation/ingrid.py  <R>
python make_numbers.py <R>      # add hw_robustness.json to <R> to enable Table IV
python make_figures.py <R>
```
Small result files used for the paper are in `../evaluation/results_final/`.
