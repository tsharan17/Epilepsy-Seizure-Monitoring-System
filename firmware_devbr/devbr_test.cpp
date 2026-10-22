// Verification harness: reads per-second deviation series and parameters,
// prints alarm times so they can be compared with the Python evaluation.
// input (stdin): r D n  followed by n floats (NaN allowed as "nan")
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "devbr.h"

int main() {
  float r; int D; long n;
  while (scanf("%f %d %ld", &r, &D, &n) == 3) {
    DevBR det(r, D);
    bool first = true;
    for (long i = 0; i < n; ++i) {
      char buf[64]; if (scanf("%63s", buf) != 1) return 1;
      float v = (strcmp(buf, "nan") == 0) ? NAN : strtof(buf, nullptr);
      if (det.pushSecond(v)) { printf(first ? "%.1f" : " %.1f", det.lastAlarmTime()); first = false; }
    }
    printf("\n");
  }
  return 0;
}
