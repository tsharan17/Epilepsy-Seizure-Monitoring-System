// Host-side verification of motion.h and vera_detect.h against the Python evaluation.
// mode "motion": stdin = lines "ax ay az gx gy gz" (25 Hz); stdout = per second "acc gyr rhythm"
// mode "detect": stdin = header "rE DE rM DM qM movOk rEc rMc DC", n, then per second "dev acc rhythm"
//                ("nan" allowed); stdout = alarm times (one per line), then "END"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include "../seizure_monitor_v5/motion.h"
#include "../seizure_monitor_v5/vera_detect.h"

static float pf(const char* s) { return (strncmp(s, "nan", 3) == 0) ? NAN : (float)atof(s); }

int main(int argc, char** argv) {
  if (argc > 1 && !strcmp(argv[1], "motion")) {
    MotionFeatures m; float v[6];
    while (scanf("%f %f %f %f %f %f", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]) == 6)
      if (m.push(v[0], v[1], v[2], v[3], v[4], v[5])) printf("%.9g %.9g %.9g\n", m.acc_act, m.gyr_act, m.rhythm);
    return 0;
  }
  char a[64], b[64], c[64];
  while (true) {
    VeraParams p; int mo;
    if (scanf("%f %d %f %d %f %d %f %f %d", &p.rE, &p.DE, &p.rM, &p.DM, &p.qM, &mo, &p.rEc, &p.rMc, &p.DC) != 9) break;
    int n; if (scanf("%d", &n) != 1) break;
    VeraDetector d(p);
    for (int t = 0; t < n; ++t) {
      if (scanf("%63s %63s %63s", a, b, c) != 3) return 1;
      if (d.pushSecond(pf(a), pf(b), pf(c), mo != 0) != VeraDetector::NONE) printf("E %.1f\n", d.lastAlarmTime());
      if (d.convulsive) printf("C %.1f\n", d.lastConvulsiveTime());
    }
    printf("END\n");
  }
  return 0;
}
