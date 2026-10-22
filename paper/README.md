# ICLT 2026 paper (IEEE conference format)

`vera_iclt2026.pdf` is the compiled paper (6 pages, the regular-paper limit).

## Open in Overleaf
1. Zip this `paper` folder, then in Overleaf go to **New Project → Upload Project** and choose the zip.
2. Main document: `main.tex`. Compiler: pdfLaTeX. Bibliography: BibTeX (`refs.bib`, `IEEEtran.bst`).

## Where the numbers come from
Every result in the text and tables is a macro in `numbers.tex`, generated from the final evaluation (notebook v2 + `personalize.py` + `final_analysis.py`):

```
python ../evaluation/personalize.py   --results <results_dir> --channel FP1-FP2
python ../evaluation/final_analysis.py --results <results_dir>
python make_numbers.py <results_dir>
python make_figures.py <results_dir>
```
`<results_dir>` is the unzipped `vera_results.zip` with `vera_features.zip` unzipped into `features/`.
The small result files the paper uses are kept in `../evaluation/results_final/`.

## Still to fill in (shown in red as [TODO])
- Bill-of-materials cost
- Bench measurements: input-referred noise, battery life
- Acknowledgment (guide/funding)
- Check the `% VERIFY` entries in `refs.bib`
