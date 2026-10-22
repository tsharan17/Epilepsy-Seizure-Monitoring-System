# DEV-BR embedded detector (C++)

`devbr.h` is a header-only implementation of the DEV-BR baseline-ratio detector described in the paper.
It is meant for the ESP32 firmware, but **it has not yet been integrated into the firmware or tested on the device**.

* Input: the firmware's existing per-sample deviation `diff = |x − (int)baseline|`.
* Every second: δ = mean diff; β = median of δ over seconds [t−329, t−30];
  alarm when δ ≥ r·β for D consecutive seconds (alarms < 90 s apart suppressed; none before 330 s).
* RAM: 330 + 300 floats ≈ 2.5 KB.  Work: one `std::nth_element` over 300 values per second.

## Verification (done)
`devbr_test.cpp` + `verify_against_python.py` feed the per-second deviation series of all 160 FP1–FP2
CHB-MIT recordings, at 5 parameter settings, through the C++ class and the Python evaluation code:
800 / 800 alarm lists identical.

```
g++ -O2 -std=c++17 -o devbr_test devbr_test.cpp
python verify_against_python.py <results folder with records.jsonl and features/>
```

## Integration sketch (NOT applied to the shipped firmware)
```cpp
#include "devbr.h"
DevBR devbr(1.25f, 20);           // r, D chosen by leave-one-subject-out CV at <=1 FA/h
...
// in loop(), after `int diff = abs(eegValue - (int)g_baseline);`
if (devbr.pushSample(diff)) { /* raise alarm: LED, GPIO18 pulse, /status */ }
```
Note: `pushSample` counts 200 samples as one second.  Because the real loop is paced by `delay(5)`
and runs slower than 200 Hz, a deployed version should close each second with `millis()` instead.
