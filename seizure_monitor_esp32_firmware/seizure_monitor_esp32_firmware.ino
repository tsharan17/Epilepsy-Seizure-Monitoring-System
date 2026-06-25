/*
  seizure_monitor.ino  — v4  (EEG Streaming + Simulation Mode + Full App Sync)
  ═══════════════════════════════════════════════════════════════════════════════
  Extends v3 (WiFi AP + RGB LED + Emergency Ecosystem) with:

    1. /eeg      — live EEG waveform streaming (128-sample circular buffer)
    2. /simulate — Flutter app injects NORMAL/BROWNOUT/BLACKOUT/POST-ICTAL
    3. /status   — adds "simulation" flag; seizure duration preserved from v3
    4. RGB LED   — syncs with simulation via effectiveState() (no dup logic)
    5. Debug log — # [TAG] prefixed lines; skipped by Python parser

  ALL v3 logic preserved:
    EMA baseline · Welford EWMA estimator · adaptive thresholds (mu+K*sigma)
    Four-state machine · non-blocking RGB blink · non-blocking mobile pulse
    Battery ADC · 5-field serial stream at 115200 baud

  GPIO (unchanged from v3):
    GPIO34 — EEG ADC (ADC1_CH6, input-only)
    GPIO35 — Battery voltage divider (ADC1_CH7, input-only)
    GPIO2  — Onboard heartbeat LED
    GPIO18 — Mobile/BT trigger (500 ms HIGH on BLACKOUT)
    GPIO25 — RGB Green
    GPIO26 — RGB Red
    GPIO27 — RGB Blue

  WiFi AP: SSID Vera_EEG_Cap / PW 12345678 -> 192.168.4.1

  Requirements: Arduino IDE 2.x, esp32 by Espressif >= 2.0, no extra libs.
  ═══════════════════════════════════════════════════════════════════════════════
*/

// ── Includes ──────────────────────────────────────────────────────────────────
#include <WiFi.h>
#include <WebServer.h>

// ═════════════════════════════════════════════════════════════════════════════
//  SECTION 1 — COMPILE-TIME CONSTANTS  (all #defines, unchanged from v3)
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

// EEG circular buffer size [NEW v4] — 128 samples = 640 ms @ 200 Hz
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

// EEG circular buffer [NEW v4]
static int  g_eegBuf[EEG_BUF_SIZE];
static int  g_eegBufHead = 0;
static bool g_eegBufFull = false;

// Simulation mode [NEW v4]
static bool         g_simulationMode = false;
static SeizureState g_simulatedState = STATE_NORMAL;

// Live seizure state machine (unchanged from v3)
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
unsigned long g_lastBattLogMs    = 0;   // [NEW v4] periodic battery log
bool          g_heartbeatOn      = false;

// Non-blocking mobile trigger pulse (unchanged from v3)
bool          g_mobilePulseActive = false;
unsigned long g_mobilePulseEndMs  = 0;

// Non-blocking LED blink state (unchanged from v3)
unsigned long g_ledLastMs  = 0;
bool          g_ledToggle  = false;

// Welford EWMA estimator variables (unchanged from v3)
double wf_n  = 0.0;
double wf_m  = 0.0;
double wf_M2 = 0.0;

// ═════════════════════════════════════════════════════════════════════════════
//  SECTION 4 — HELPER FUNCTIONS
//  All globals and the SeizureState enum are now fully declared above.
// ═════════════════════════════════════════════════════════════════════════════

// ── Simulation: single source of truth for display/LED/API ────────────────
// [NEW v4] — only function that decides live vs simulated state.
// The state machine, Welford estimator, and serial output ALWAYS use g_state.
SeizureState effectiveState() {
  return g_simulationMode ? g_simulatedState : g_state;
}

// ── EEG circular buffer push [NEW v4] ─────────────────────────────────────
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

// ── Welford EWMA estimator (unchanged from v3) ────────────────────────────
void welfordUpdate(float x) {
  wf_n   = WF_FORGET * wf_n + 1.0;
  double d = x - wf_m;
  wf_m  += d / wf_n;
  wf_M2  = WF_FORGET * wf_M2 + d * (x - wf_m);
}

float welfordMean() { return (float)wf_m; }
float welfordStd()  { return (wf_n < 2.0) ? 0.0f : (float)sqrt(wf_M2 / wf_n); }

// ── Adaptive threshold recalculation (unchanged from v3) ─────────────────
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

// ── Battery percentage (unchanged from v3) ────────────────────────────────
int readBatteryPercent() {
  int raw = analogRead(BATTERY_PIN);
  return constrain(map(raw, BATT_ADC_MIN, BATT_ADC_MAX, 0, 100), 0, 100);
}

// ── RGB LED primitives (unchanged from v3) ────────────────────────────────
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
// [v4 change] reads effectiveState() — simulation drives LEDs automatically.
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
// [v4] Added "simulation" field.  All other fields unchanged from v3.
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

  char json[256];
  snprintf(json, sizeof(json),
    "{"
      "\"state\":\"%s\","
      "\"battery\":\"%d\","
      "\"connected\":\"true\","
      "\"seizureDuration\":\"%lu\","
      "\"simulation\":\"%s\","
      "\"threshBrownout\":\"%d\","
      "\"threshBlackout\":\"%d\""
    "}",
    stateLabel(effectiveState()),
    batt, durS,
    g_simulationMode ? "true" : "false",
    g_threshBrownout,
    g_threshBlackout
  );

  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

// ── GET /eeg  [NEW v4] ─────────────────────────────────────────────────────
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

// ── GET /simulate  [NEW v4] ────────────────────────────────────────────────
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

  // HTTP routes
  server.on("/status",   HTTP_GET, handleStatus);
  server.on("/eeg",      HTTP_GET, handleEEG);        // [NEW v4]
  server.on("/simulate", HTTP_GET, handleSimulation); // [NEW v4]
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

  // Mild Welford seed (unchanged from v3)
  for (int i = 0; i < 20; i++) welfordUpdate(10.0f);

  g_startMs     = millis();
  g_lastAdaptMs = millis();

  Serial.printf("# [BOOT] Calibration done.  Baseline=%.1f\n", g_baseline);
  Serial.println("# [BOOT] Streaming: eegValue baseline diff state adaptThreshold");
}

// ═════════════════════════════════════════════════════════════════════════════
//  MAIN LOOP  (~200 Hz)
//  Step order and all existing logic unchanged from v3.
//  [v4] additions are marked inline.
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

  // [v4] Push into EEG circular buffer for /eeg endpoint
  eegBufPush(eegValue);

  // 2. EMA baseline
  g_baseline = (1.0f - EMA_ALPHA) * g_baseline + EMA_ALPHA * (float)eegValue;

  // 3. Diff signal
  int diff = abs(eegValue - (int)g_baseline);

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
      Serial.printf("# [STATE] -> BLACKOUT  thr=%d\n", g_threshBlackout);
    } else if (g_state == STATE_POSTICTAL) {
      Serial.println("# [STATE] -> POST-ICTAL");
    } else if (g_state == STATE_NORMAL) {
      Serial.println("# [STATE] -> NORMAL");
    }
  }

  // 8. Non-blocking RGB LED update
  //    [v4] updateLED() calls effectiveState() — simulation syncs LEDs here.
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

  // [v4] Periodic battery debug log — every 60 s, avoids serial spam
  if (now - g_lastBattLogMs >= 60000UL) {
    g_lastBattLogMs = now;
    int raw = analogRead(BATTERY_PIN);
    int pct = constrain(map(raw, BATT_ADC_MIN, BATT_ADC_MAX, 0, 100), 0, 100);
    Serial.printf("# [BATT] ADC=%d  ->  %d%%\n", raw, pct);
  }

  // 10. Serial output — 5 fields, unchanged from v3.
  //     'state' field is LIVE g_state (not simulated) for Python analyzer.
  Serial.print(eegValue);       Serial.print(" ");
  Serial.print(g_baseline, 2);  Serial.print(" ");
  Serial.print(diff);           Serial.print(" ");
  Serial.print((int)g_state);   Serial.print(" ");
  Serial.println(g_threshBrownout);

  // 11. Sample pacing (~200 Hz)
  delay(SAMPLE_DELAY_MS);
}
