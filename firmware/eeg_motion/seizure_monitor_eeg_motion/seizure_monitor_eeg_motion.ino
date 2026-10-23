/*
  seizure_monitor_eeg_motion.ino  (EEG + MPU9250 head-motion + on-device DEV-BR/MOV-BR alarm)
  ═══════════════════════════════════════════════════════════════════════════════
  Extends the EEG-only firmware with:
    1. MPU9250 IMU on I2C (SDA GPIO21, SCL GPIO22, AD0->GND = 0x68), 25 Hz, ±4 g, ±500 dps
    2. MotionFeatures (motion_features.h): per-second high-passed acceleration, gyro magnitude, 2-7 Hz rhythm
    3. BaselineDetector (baseline_detector.h), delayed-median baselines, one output per 90 s each:
         EVENT  = EEG DEV-BR  OR  motion MOV-BR          -> BROWNOUT (warning, LED blue)
         ALARM  = EEG AND motion co-activation          -> BLACKOUT (red LED + GPIO18 pulse)
       Parameters below are those selected in the SeizeIT2 evaluation.
    4. /status adds alarm source, log-ratios, IMU status and the measured EEG sampling rate
    5. "# [DET] ..." telemetry once per second (ignored by the Python analyzer)
  DETECTOR_MODE 0 keeps the EEG-only behaviour exactly (legacy state machine drives alarms).
  If the IMU is absent, the firmware runs EEG-only and reports "imu":"absent".

  GPIO: 34 EEG ADC · 35 battery · 2 heartbeat · 18 mobile trigger · 25/26/27 RGB
        21 I2C SDA (MPU9250) · 22 I2C SCL (MPU9250)
  WiFi AP: SSID Vera_EEG_Cap / PW 12345678 -> 192.168.4.1   (change the password before use)
  Requirements: Arduino IDE 2.x, esp32 by Espressif >= 2.0, no extra libraries.
  ═══════════════════════════════════════════════════════════════════════════════
*/

// ── Includes ──────────────────────────────────────────────────────────────────
#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include "mpu9250.h"
#include "motion_features.h"
#include "baseline_detector.h"

// ═════════════════════════════════════════════════════════════════════════════
//  SECTION 1 — COMPILE-TIME CONSTANTS  (all #defines
// ═════════════════════════════════════════════════════════════════════════════

// Pins
#define EEG_PIN          34
#define BATTERY_PIN      35
#define LED_HEARTBEAT     2
#define PIN_MOBILE_TRIG  18
#define RGB_GREEN        25
#define RGB_RED          26
#define RGB_BLUE         27

// WiFi
#define WIFI_SSID      "Vera_EEG_Cap"
#define WIFI_PASSWORD  "12345678"

// Sampling / EMA
#define SAMPLE_DELAY_MS   5
#define BAUD_RATE         115200
#define EMA_ALPHA         0.01f

// Adaptive thresholds
#define ADAPT_WARMUP_MS        90000UL
#define ADAPT_INTERVAL_MS      30000UL
#define ADAPT_Z_BROWNOUT       2.5f
#define ADAPT_Z_BLACKOUT       4.0f
#define THRESH_BROWNOUT_FLOOR  60
#define THRESH_BLACKOUT_FLOOR  120
#define THRESH_BROWNOUT_CEIL   1200
#define THRESH_BLACKOUT_CEIL   2400
#define WF_FORGET              0.995

// State-machine confirmation counts
#define CONFIRM_BROWNOUT  20
#define CONFIRM_BLACKOUT  15
#define POSTICTAL_HOLD    400

// Timing
#define HEARTBEAT_INTERVAL_MS  500
#define MOBILE_PULSE_MS        500

// RGB blink periods (ms)
#define LED_BROWNOUT_PERIOD    600
#define LED_BLACKOUT_PERIOD    150
#define LED_POSTICTAL_PERIOD   800

// Battery ADC calibration (1:1 divider: 4.2V->ADC~2606, 3.0V->ADC~1861)
#define BATT_ADC_MIN  1861
#define BATT_ADC_MAX  2606

// ── IMU + multimodal detector ─────────────────────────────────────────────
#define DETECTOR_MODE      1        // 1 = EEG-plus-motion alarm, 0 = EEG-only state machine
#define I2C_SDA           21
#define I2C_SCL           22
#define IMU_PERIOD_MS     40        // 25 Hz
#define EVENT_HOLD_MS     60000UL   // BROWNOUT shown for 60 s after an event
#define ALARM_HOLD_MS     60000UL   // BLACKOUT shown for 60 s after a convulsive alarm, then POST-ICTAL
#define POSTICTAL_HOLD_MS 60000UL
// Detector parameters: modal leave-one-subject-out choices on SeizeIT2 (125 patients)
//   general event (<=1 FA/h target):  EEG r=2.0 for 20 s  OR  motion r=24, rhythm>=0.4 for 20 s  (106/125 folds)
//   convulsive alarm (<=0.02 FA/h):   EEG r>=4.0 AND motion r>=8.0 for 30 s                     (122/125 folds)
#define EVT_EEG_RATIO   2.0f
#define EVT_EEG_SECS   20
#define EVT_MOV_RATIO   24.0f
#define EVT_MOV_SECS   20
#define EVT_MOV_RHYTHM   0.4f
#define CONV_EEG_RATIO  4.0f    // convulsive alarm: EEG ratio
#define CONV_MOV_RATIO  8.0f    //                   motion ratio
#define CONV_SECS   30      //                   persistence (s)

// EEG circular buffer size — 128 samples = 640 ms @ 200 Hz
#define EEG_BUF_SIZE  128

// ═════════════════════════════════════════════════════════════════════════════
//  SECTION 2 — ENUM  (must appear before ANY global or function that uses it)
// ═════════════════════════════════════════════════════════════════════════════

enum SeizureState : uint8_t {
  STATE_NORMAL    = 0,
  STATE_BROWNOUT  = 1,
  STATE_BLACKOUT  = 2,
  STATE_POSTICTAL = 3,
};

// ═════════════════════════════════════════════════════════════════════════════
//  SECTION 3 — ALL GLOBAL VARIABLES
//  (enum SeizureState must be declared above before any of these)
// ═════════════════════════════════════════════════════════════════════════════

// HTTP server
WebServer server(80);

// EEG circular buffer
static int  g_eegBuf[EEG_BUF_SIZE];
static int  g_eegBufHead = 0;
static bool g_eegBufFull = false;

// Simulation mode
static bool         g_simulationMode = false;
static SeizureState g_simulatedState = STATE_NORMAL;

// Live seizure state machine
float        g_baseline        = 0.0f;
int          g_threshBrownout  = 80;
int          g_threshBlackout  = 160;
SeizureState g_state           = STATE_NORMAL;
int          g_confirmBrownout = 0;
int          g_confirmBlackout = 0;
int          g_postictalCount  = 0;

// Timing
unsigned long g_startMs          = 0;
unsigned long g_lastAdaptMs      = 0;
unsigned long g_lastHeartbeatMs  = 0;
unsigned long g_seizureStartMs   = 0;
unsigned long g_lastBattLogMs    = 0;   // periodic battery log
bool          g_heartbeatOn      = false;

// Non-blocking mobile trigger pulse
bool          g_mobilePulseActive = false;
unsigned long g_mobilePulseEndMs  = 0;

// Non-blocking LED blink state
unsigned long g_ledLastMs  = 0;
bool          g_ledToggle  = false;

// EEG-plus-motion globals
MPU9250        g_imu;
bool           g_imuOk = false;
MotionFeatures g_motion;
BaselineDetector*  g_detector = nullptr;
unsigned long  g_lastImuMs = 0, g_secStartMs = 0, g_convAlarmMs = 0;
double         g_devSum = 0.0;  long g_devN = 0;
int            g_fsMeasured = 0;
float          g_lastDev = NAN;
int            g_lastSource = 0;      // 1 EEG, 2 MOTION, 3 BOTH
bool           g_convActive = false;      // convulsive alarm active
bool           g_eventActive = false;       // general event active
unsigned long  g_eventMs = 0;

// Welford EWMA estimator variables
double wf_n  = 0.0;
double wf_m  = 0.0;
double wf_M2 = 0.0;

// ═════════════════════════════════════════════════════════════════════════════
//  SECTION 4 — HELPER FUNCTIONS
//  All globals and the SeizureState enum are now fully declared above.
// ═════════════════════════════════════════════════════════════════════════════

// ── Simulation: single source of truth for display/LED/API ────────────────
// — only function that decides live vs simulated state.
// The state machine, Welford estimator, and serial output ALWAYS use g_state.
SeizureState effectiveState() {
  return g_simulationMode ? g_simulatedState : g_state;
}

// ── EEG circular buffer push ─────────────────────────────────────
void eegBufPush(int sample) {
  g_eegBuf[g_eegBufHead] = sample;
  g_eegBufHead = (g_eegBufHead + 1) % EEG_BUF_SIZE;
  if (!g_eegBufFull && g_eegBufHead == 0) g_eegBufFull = true;
}

// ── State label (for JSON + serial) ───────────────────────────────────────
const char* stateLabel(SeizureState s) {
  switch (s) {
    case STATE_BROWNOUT:  return "BROWNOUT";
    case STATE_BLACKOUT:  return "BLACKOUT";
    case STATE_POSTICTAL: return "POST-ICTAL";
    default:              return "NORMAL";
  }
}

// ── Welford EWMA estimator ────────────────────────────
void welfordUpdate(float x) {
  wf_n   = WF_FORGET * wf_n + 1.0;
  double d = x - wf_m;
  wf_m  += d / wf_n;
  wf_M2  = WF_FORGET * wf_M2 + d * (x - wf_m);
}

float welfordMean() { return (float)wf_m; }
float welfordStd()  { return (wf_n < 2.0) ? 0.0f : (float)sqrt(wf_M2 / wf_n); }

// ── Adaptive threshold recalculation ─────────────────
void recalcThresholds() {
  float mu    = welfordMean();
  float sigma = welfordStd();
  if (sigma < 1.0f) return;

  int nb = constrain((int)(mu + ADAPT_Z_BROWNOUT * sigma),
                     THRESH_BROWNOUT_FLOOR, THRESH_BROWNOUT_CEIL);
  int nk = constrain((int)(mu + ADAPT_Z_BLACKOUT * sigma),
                     THRESH_BLACKOUT_FLOOR, THRESH_BLACKOUT_CEIL);
  if (nk <= nb) nk = nb + 40;

  g_threshBrownout = nb;
  g_threshBlackout = nk;

  Serial.printf("# [THRESH] brownout=%d  blackout=%d  mu=%.1f  sigma=%.1f\n",
                nb, nk, mu, sigma);
}

// ── Battery percentage ────────────────────────────────
int readBatteryPercent() {
  int raw = analogRead(BATTERY_PIN);
  return constrain(map(raw, BATT_ADC_MIN, BATT_ADC_MAX, 0, 100), 0, 100);
}

// ── RGB LED primitives ────────────────────────────────
void setRGB(bool r, bool g, bool b) {
  digitalWrite(RGB_RED,   r ? HIGH : LOW);
  digitalWrite(RGB_GREEN, g ? HIGH : LOW);
  digitalWrite(RGB_BLUE,  b ? HIGH : LOW);
}

void setNormalLED()    { setRGB(false, true,  false); }  // solid green
void setBrownoutLED()  { setRGB(false, false, true);  }  // solid blue
void setBlackoutLED()  { setRGB(true,  false, false); }  // solid red
void setPostIctalLED() { setRGB(true,  false, true);  }  // purple (R+B)
void setOffLED()       { setRGB(false, false, false); }

// ── Non-blocking RGB LED update ───────────────────────────────────────────
// reads effectiveState() — simulation drives LEDs automatically.
// No extra switch block needed; no duplicated logic.
void updateLED(unsigned long now) {
  switch (effectiveState()) {
    case STATE_NORMAL:
      setNormalLED();
      break;
    case STATE_BROWNOUT:
      if (now - g_ledLastMs >= LED_BROWNOUT_PERIOD) {
        g_ledLastMs = now;
        g_ledToggle = !g_ledToggle;
        g_ledToggle ? setBrownoutLED() : setOffLED();
      }
      break;
    case STATE_BLACKOUT:
      if (now - g_ledLastMs >= LED_BLACKOUT_PERIOD) {
        g_ledLastMs = now;
        g_ledToggle = !g_ledToggle;
        g_ledToggle ? setBlackoutLED() : setOffLED();
      }
      break;
    case STATE_POSTICTAL:
      if (now - g_ledLastMs >= LED_POSTICTAL_PERIOD) {
        g_ledLastMs = now;
        g_ledToggle = !g_ledToggle;
        g_ledToggle ? setPostIctalLED() : setOffLED();
      }
      break;
  }
}

// ═════════════════════════════════════════════════════════════════════════════
//  SECTION 5 — HTTP HANDLERS
// ═════════════════════════════════════════════════════════════════════════════

// ── GET /status ────────────────────────────────────────────────────────────
// Added "simulation" field.  All other fields.
//
// Response:
//   {
//     "state":           "NORMAL",
//     "battery":         "72",
//     "connected":       "true",
//     "seizureDuration": "0",
//     "simulation":      "false",
//     "threshBrownout":  "95",
//     "threshBlackout":  "185"
//   }
void handleStatus() {
  int batt = readBatteryPercent();

  // Duration counts from live BLACKOUT entry — unaffected by simulation
  unsigned long durS = (g_state == STATE_BLACKOUT)
                       ? (millis() - g_seizureStartMs) / 1000UL
                       : 0UL;

  Serial.printf("# [HTTP] GET /status  eff=%s  sim=%s  batt=%d%%  dur=%lus\n",
                stateLabel(effectiveState()),
                g_simulationMode ? "true" : "false",
                batt, durS);

  const char* src = g_lastSource == 3 ? "BOTH" : g_lastSource == 2 ? "MOTION" : g_lastSource == 1 ? "EEG" : "NONE";
  char json[448];
  snprintf(json, sizeof(json),
    "{"
      "\"state\":\"%s\","
      "\"battery\":\"%d\","
      "\"connected\":\"true\","
      "\"seizureDuration\":\"%lu\","
      "\"simulation\":\"%s\","
      "\"threshBrownout\":\"%d\","
      "\"threshBlackout\":\"%d\","
      "\"detector\":\"%s\","
      "\"alarmSource\":\"%s\","
      "\"eegRatio\":\"%.2f\","
      "\"motionRatio\":\"%.2f\","
      "\"motion\":\"%.4f\","
      "\"imu\":\"%s\","
      "\"fs\":\"%d\""
    "}",
    stateLabel(effectiveState()),
    batt, durS,
    g_simulationMode ? "true" : "false",
    g_threshBrownout,
    g_threshBlackout,
    DETECTOR_MODE ? "eeg_motion" : "eeg_only",
    src,
    (g_detector && isfinite(g_detector->lrE)) ? exp(g_detector->lrE) : 0.0,
    (g_detector && isfinite(g_detector->lrM)) ? exp(g_detector->lrM) : 0.0,
    isfinite(g_motion.acc_act) ? g_motion.acc_act : 0.0f,
    g_imuOk ? "ok" : "absent",
    g_fsMeasured
  );

  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

// ── GET /eeg ─────────────────────────────────────────────────────
// Serialises the circular EEG buffer chronologically (oldest -> newest).
// No heap allocation; stack-local char array sized for worst case.
// Response: {"samples":[2048,2051,...]}
void handleEEG() {
  Serial.println("# [HTTP] GET /eeg");

  // Worst case: EEG_BUF_SIZE * 5 chars ("4095,") + framing + null ~= 660 B
  static char json[800];
  int pos = 0;

  pos += snprintf(json + pos, sizeof(json) - pos, "{\"samples\":[");

  int count = g_eegBufFull ? EEG_BUF_SIZE : g_eegBufHead;
  int start = g_eegBufFull ? g_eegBufHead : 0;  // oldest slot

  for (int i = 0; i < count; i++) {
    int idx  = (start + i) % EEG_BUF_SIZE;
    bool last = (i == count - 1);
    pos += snprintf(json + pos, sizeof(json) - pos,
                    last ? "%d" : "%d,",
                    g_eegBuf[idx]);
  }
  snprintf(json + pos, sizeof(json) - pos, "]}");

  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

// ── GET /simulate ────────────────────────────────────────────────
// Query param: state=NORMAL|BROWNOUT|BLACKOUT|POST-ICTAL
//
// state=NORMAL  -> exit simulation, restore live detection immediately.
// Any other     -> enter/update simulation with the requested state.
//
// Live EEG pipeline (ADC, EMA, Welford, state machine) is UNAFFECTED.
// LEDs and /status reflect the new effective state instantly.
//
// Response: {"simulation":"true","effectiveState":"BLACKOUT"}
void handleSimulation() {
  if (!server.hasArg("state")) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json",
      "{\"error\":\"Missing ?state= — use NORMAL|BROWNOUT|BLACKOUT|POST-ICTAL\"}");
    return;
  }

  String req = server.arg("state");
  req.toUpperCase();

  SeizureState newSim;
  if      (req == "NORMAL")     newSim = STATE_NORMAL;
  else if (req == "BROWNOUT")   newSim = STATE_BROWNOUT;
  else if (req == "BLACKOUT")   newSim = STATE_BLACKOUT;
  else if (req == "POST-ICTAL") newSim = STATE_POSTICTAL;
  else {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json",
      "{\"error\":\"Unknown state — use NORMAL|BROWNOUT|BLACKOUT|POST-ICTAL\"}");
    return;
  }

  unsigned long now = millis();

  if (newSim == STATE_NORMAL && g_simulationMode) {
    // EXIT simulation: restore live detection
    g_simulationMode = false;
    g_ledLastMs = now;
    g_ledToggle = true;
    Serial.println("# [SIM] Exited simulation -> live detection restored");
  } else if (newSim != STATE_NORMAL) {
    // ENTER or UPDATE simulation
    bool wasActive   = g_simulationMode;
    g_simulationMode = true;
    g_simulatedState = newSim;
    g_ledLastMs = now;
    g_ledToggle = true;
    Serial.printf("# [SIM] %s simulation: %s\n",
                  wasActive ? "Updated" : "Entered",
                  stateLabel(newSim));
  }

  char json[96];
  snprintf(json, sizeof(json),
    "{\"simulation\":\"%s\",\"effectiveState\":\"%s\"}",
    g_simulationMode ? "true" : "false",
    stateLabel(effectiveState())
  );

  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

// ═════════════════════════════════════════════════════════════════════════════
//  SETUP
// ═════════════════════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(BAUD_RATE);

  // Output pins
  pinMode(LED_HEARTBEAT,   OUTPUT);
  pinMode(PIN_MOBILE_TRIG, OUTPUT);
  pinMode(RGB_RED,         OUTPUT);
  pinMode(RGB_GREEN,       OUTPUT);
  pinMode(RGB_BLUE,        OUTPUT);

  digitalWrite(LED_HEARTBEAT,   LOW);
  digitalWrite(PIN_MOBILE_TRIG, LOW);
  setOffLED();

  // WiFi Access Point
  WiFi.softAP(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("# [WiFi] AP started — SSID: %s  IP: %s\n",
                WIFI_SSID, WiFi.softAPIP().toString().c_str());

  // IMU + detector
  g_imuOk = g_imu.begin(I2C_SDA, I2C_SCL, MPU9250::ADDR_LO);
  Serial.printf("# [IMU] MPU9250 %s (WHO_AM_I=0x%02X)\n", g_imuOk ? "found" : "NOT found - EEG-only", g_imu.whoami);
  BaselineParams vp; vp.rE = EVT_EEG_RATIO; vp.DE = EVT_EEG_SECS; vp.rM = EVT_MOV_RATIO; vp.DM = EVT_MOV_SECS; vp.qM = EVT_MOV_RHYTHM; vp.useMOV = g_imuOk;
  vp.rEc = CONV_EEG_RATIO; vp.rMc = CONV_MOV_RATIO; vp.DC = CONV_SECS;
  g_detector = new BaselineDetector(vp);

  // HTTP routes
  server.on("/status",   HTTP_GET, handleStatus);
  server.on("/eeg",      HTTP_GET, handleEEG);        //
  server.on("/simulate", HTTP_GET, handleSimulation); //
  server.begin();
  Serial.println("# [HTTP] Server on port 80 — routes: /status /eeg /simulate");

  // Baseline calibration (~1 s, 200 samples)
  Serial.println("# [BOOT] Calibrating baseline...");
  setRGB(false, false, true);   // solid blue during calibration
  long sum = 0;
  for (int i = 0; i < 200; i++) {
    sum += analogRead(EEG_PIN);
    delay(SAMPLE_DELAY_MS);
  }
  g_baseline = (float)(sum / 200);
  setOffLED();

  // Mild Welford seed
  for (int i = 0; i < 20; i++) welfordUpdate(10.0f);

  g_startMs     = millis();
  g_lastAdaptMs = millis();
  g_secStartMs  = millis();
  g_lastImuMs   = millis();

  Serial.printf("# [BOOT] Calibration done.  Baseline=%.1f\n", g_baseline);
  Serial.println("# [BOOT] Streaming: eegValue baseline diff state adaptThreshold");
}

// ═════════════════════════════════════════════════════════════════════════════
//  MAIN LOOP  (~200 Hz)
//  Step order and all existing logic.
//  additions are marked inline.
// ═════════════════════════════════════════════════════════════════════════════
void loop() {
  unsigned long now = millis();

  // A. WiFi / HTTP (non-blocking)
  server.handleClient();

  // B. Non-blocking mobile trigger release
  if (g_mobilePulseActive && now >= g_mobilePulseEndMs) {
    digitalWrite(PIN_MOBILE_TRIG, LOW);
    g_mobilePulseActive = false;
  }

  // 1. Sample ADC
  int eegValue = analogRead(EEG_PIN);

  // Push into EEG circular buffer for /eeg endpoint
  eegBufPush(eegValue);

  // 2. EMA baseline
  g_baseline = (1.0f - EMA_ALPHA) * g_baseline + EMA_ALPHA * (float)eegValue;

  // 3. Diff signal
  int diff = abs(eegValue - (int)g_baseline);

  // per-second EEG deviation and 25-Hz IMU sampling
  g_devSum += diff; ++g_devN;
  if (g_imuOk && now - g_lastImuMs >= IMU_PERIOD_MS) {
    g_lastImuMs += IMU_PERIOD_MS;
    if (now - g_lastImuMs > 4 * IMU_PERIOD_MS) g_lastImuMs = now;   // resync after a stall
    if (g_imu.read()) g_motion.push(g_imu.ax, g_imu.ay, g_imu.az, g_imu.gx, g_imu.gy, g_imu.gz);
  }
  if (now - g_secStartMs >= 1000UL) {
    g_secStartMs += 1000UL;
    g_fsMeasured = (int)g_devN;
    g_lastDev = g_devN ? (float)(g_devSum / g_devN) : NAN;
    g_devSum = 0.0; g_devN = 0;
    BaselineDetector::Source s = g_detector->pushSecond(g_lastDev, g_motion.acc_act, g_motion.rhythm, g_imuOk);
    Serial.printf("# [DET] fs=%d dev=%.2f eegR=%.2f acc=%.4f gyr=%.2f rhy=%.2f movR=%.2f event=%d conv=%d\n",
                  g_fsMeasured, g_lastDev, isfinite(g_detector->lrE) ? exp(g_detector->lrE) : 0.0,
                  g_motion.acc_act, g_motion.gyr_act, g_motion.rhythm,
                  isfinite(g_detector->lrM) ? exp(g_detector->lrM) : 0.0, (int)s, (int)g_detector->convulsive);
    if (s != BaselineDetector::NONE) { g_lastSource = (int)s; g_eventActive = true; g_eventMs = now; }
    if (g_detector->convulsive)       { g_lastSource = 3; g_convActive = true; g_convAlarmMs = now; }
  }

  // 4. Welford estimator — LIVE NORMAL state only.
  //    Uses g_state (not effectiveState) so simulation cannot corrupt the model.
  if (g_state == STATE_NORMAL) {
    welfordUpdate((float)diff);
  }

  // 5. Adaptive threshold recalculation
  bool warmedUp = (now - g_startMs) >= ADAPT_WARMUP_MS;
  if (warmedUp && (now - g_lastAdaptMs) >= ADAPT_INTERVAL_MS) {
    recalcThresholds();
    g_lastAdaptMs = now;
  }

  // 6. Seizure state machine (operates on g_state, fully independent of sim)
  SeizureState prevState = g_state;

#if DETECTOR_MODE == 1
  // convulsive alarm -> BLACKOUT then POST-ICTAL; general event -> BROWNOUT
  if (g_eventActive && now - g_eventMs >= EVENT_HOLD_MS) g_eventActive = false;
  if (g_convActive) {
    unsigned long since = now - g_convAlarmMs;
    if (since < ALARM_HOLD_MS)                         g_state = STATE_BLACKOUT;
    else if (since < ALARM_HOLD_MS + POSTICTAL_HOLD_MS) g_state = STATE_POSTICTAL;
    else { g_convActive = false; g_state = g_eventActive ? STATE_BROWNOUT : STATE_NORMAL; }
  } else {
    g_state = g_eventActive ? STATE_BROWNOUT : STATE_NORMAL;
  }
  if (false)
#endif
  switch (g_state) {
    case STATE_NORMAL:
      if (diff >= g_threshBlackout) {
        if (++g_confirmBlackout >= CONFIRM_BLACKOUT) {
          g_state = STATE_BLACKOUT;
          g_confirmBlackout = g_confirmBrownout = 0;
        }
      } else if (diff >= g_threshBrownout) {
        g_confirmBlackout = 0;
        if (++g_confirmBrownout >= CONFIRM_BROWNOUT) {
          g_state = STATE_BROWNOUT;
          g_confirmBrownout = 0;
        }
      } else {
        if (g_confirmBrownout > 0) g_confirmBrownout--;
        if (g_confirmBlackout > 0) g_confirmBlackout--;
      }
      break;

    case STATE_BROWNOUT:
      if (diff >= g_threshBlackout) {
        if (++g_confirmBlackout >= CONFIRM_BLACKOUT) {
          g_state = STATE_BLACKOUT;
          g_confirmBlackout = 0;
        }
      } else if (diff < g_threshBrownout) {
        if (++g_confirmBrownout >= CONFIRM_BROWNOUT) {
          g_state = STATE_NORMAL;
          g_confirmBrownout = 0;
        }
      } else {
        g_confirmBrownout = g_confirmBlackout = 0;
      }
      break;

    case STATE_BLACKOUT:
      if (diff < g_threshBrownout) {
        g_state          = STATE_POSTICTAL;
        g_postictalCount = POSTICTAL_HOLD;
      }
      break;

    case STATE_POSTICTAL:
      if (--g_postictalCount <= 0 && diff < g_threshBrownout) {
        g_state = STATE_NORMAL;
      }
      break;
  }

  // 7. State-change side-effects
  if (g_state != prevState) {
    g_ledLastMs = now;
    g_ledToggle = true;

    if (g_state == STATE_BROWNOUT) {
      Serial.printf("# [STATE] -> BROWNOUT  thr=%d\n", g_threshBrownout);
    } else if (g_state == STATE_BLACKOUT) {
      g_seizureStartMs = now;
      digitalWrite(PIN_MOBILE_TRIG, HIGH);
      g_mobilePulseEndMs  = now + MOBILE_PULSE_MS;
      g_mobilePulseActive = true;
      Serial.printf("# [STATE] -> BLACKOUT  thr=%d  source=%d\n", g_threshBlackout, g_lastSource);
    } else if (g_state == STATE_POSTICTAL) {
      Serial.println("# [STATE] -> POST-ICTAL");
    } else if (g_state == STATE_NORMAL) {
      Serial.println("# [STATE] -> NORMAL");
    }
  }

  // 8. Non-blocking RGB LED update
  //    updateLED() calls effectiveState() — simulation syncs LEDs here.
  updateLED(now);

  // 9. Onboard heartbeat LED (NORMAL only)
  //    Uses effectiveState() so heartbeat off during simulated non-NORMAL.
  if (effectiveState() == STATE_NORMAL &&
      (now - g_lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS)) {
    g_lastHeartbeatMs = now;
    g_heartbeatOn     = !g_heartbeatOn;
    digitalWrite(LED_HEARTBEAT, g_heartbeatOn);
  } else if (effectiveState() != STATE_NORMAL) {
    digitalWrite(LED_HEARTBEAT, LOW);
    g_heartbeatOn = false;
  }

  // Periodic battery debug log — every 60 s, avoids serial spam
  if (now - g_lastBattLogMs >= 60000UL) {
    g_lastBattLogMs = now;
    int raw = analogRead(BATTERY_PIN);
    int pct = constrain(map(raw, BATT_ADC_MIN, BATT_ADC_MAX, 0, 100), 0, 100);
    Serial.printf("# [BATT] ADC=%d  ->  %d%%\n", raw, pct);
  }

  // 10. Serial output — 5 fields.
  //     'state' field is LIVE g_state (not simulated) for Python analyzer.
  Serial.print(eegValue);       Serial.print(" ");
  Serial.print(g_baseline, 2);  Serial.print(" ");
  Serial.print(diff);           Serial.print(" ");
  Serial.print((int)g_state);   Serial.print(" ");
  Serial.println(g_threshBrownout);

  // 11. Sample pacing (~200 Hz)
  delay(SAMPLE_DELAY_MS);
}
