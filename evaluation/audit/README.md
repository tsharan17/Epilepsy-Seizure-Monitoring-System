# Audit of the CHB-MIT FP1–FP2 derivation

| Script | Does |
|---|---|
| `fetch_edf_headers.py` | Reads only the EDF headers (labels, calibration) of all CHB-MIT recordings via HTTP range requests → `../results/audit/chbmit_edf_headers.json` |
| `montage_check.py` | On sample recordings: derives FP1–FP2 from the bipolar chain and checks calibration, duplicate channels, polarity (eye-blink cancellation versus a wrong-sign chain) and quantization noise → `../results/audit/recon_test.json` |

Findings: the chain telescopes to FP1−FP2 if all channels share one reference; 157 of 165 analysed recordings have the chain, 3 chb12 recordings are referential (direct FP1−FP2), and 5 recordings lacking FT9-FT10 are excluded. Polarity is supported (blink amplitude in the derived channel is 0.13–0.41 of FP1-F7; 0.86–2.03 for a wrong-sign chain). The derivation cannot be verified against a measured FP1–FP2 because the dataset contains none. See `../../docs/audit_report.md`.

```
python fetch_edf_headers.py
python montage_check.py chb01/chb01_03.edf chb05/chb05_06.edf
```
