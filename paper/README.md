# Paper

*A Low-Cost EEG and Head-Motion Epilepsy Seizure Alarm with Baseline-Normalized Detection and Replay-Based Evaluation* (IEEE conference format, 6 pages including references).

* `main.tex`, `refs.bib`, `IEEEtran.cls/.bst` — source (compiles with pdflatex + bibtex, also on Overleaf)
* `iclt2026_epilepsy_alarm.pdf` — compiled paper
* `numbers.tex`, `numbers_s2.tex`, `numbers_audit.tex` — every number in the text and tables, generated from `../evaluation/results/`
* `make_numbers.py`, `make_numbers_s2.py`, `make_numbers_audit.py` — generate the number files
* `make_figures.py`, `make_figures_s2.py`, `make_example_s2.py`, `make_hw_figure.py` — figures

```
python make_numbers.py ../evaluation/results
python make_numbers_s2.py ../evaluation/results
python make_numbers_audit.py
python make_figures_s2.py ../evaluation/results
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

`make_figures.py` and `make_example_s2.py` need the large per-recording feature folders produced by the evaluation scripts (not stored here).
