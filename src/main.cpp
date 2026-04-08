#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

/*
  Simple demo firmware for Wokwi + Flask dashboard
  ------------------------------------------------
  - Potentiometer controls knee angle directly (0 -> 130 degrees)
  - LED colors:
      red    = under target
      green  = in target zone
      yellow = over target
  - Sends JSON to Flask: imu1, imu2, flex
*/

// WiFi / backend
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASS = "";
const char* SERVER_URL = "http://host.wokwi.internal:5000/update";

// Pins (match diagram.json)
const int PIN_RED = 2;
const int PIN_GREEN = 26;
const int PIN_YELLOW = 25;
const int PIN_STATUS = 13;
const int PIN_POT = 34;

// Rehab thresholds
const float TARGET_ANGLE = 90.0f;
const float TOLERANCE = 5.0f;         // green zone is 85..95
const float RESET_ANGLE = 20.0f;      // must go below this before next rep
const float MAX_DEMO_ANGLE = 130.0f;  // potentiometer full-scale angle

// Loop timing
const unsigned long SEND_EVERY_MS = 200;

// Rep state
int repCount = 0;
bool repArmed = false;
bool repHit = false;

unsigned long lastSendMs = 0;

float mapPotToAngle(int raw) {
  float norm = constrain(raw / 4095.0f, 0.0f, 1.0f);
  return norm * MAX_DEMO_ANGLE;
}

void setZoneLeds(float kneeAngle) {
  const bool inGreen = abs(kneeAngle - TARGET_ANGLE) <= TOLERANCE;
  const bool isRed = kneeAngle < (TARGET_ANGLE - TOLERANCE);
  const bool isYellow = kneeAngle > (TARGET_ANGLE + TOLERANCE);

  digitalWrite(PIN_RED, isRed ? HIGH : LOW);
  digitalWrite(PIN_GREEN, inGreen ? HIGH : LOW);
  digitalWrite(PIN_YELLOW, isYellow ? HIGH : LOW);
}

void updateRepCount(float kneeAngle) {
  if (kneeAngle > RESET_ANGLE) {
    repArmed = true;
  }

  const bool inGreen = abs(kneeAngle - TARGET_ANGLE) <= TOLERANCE;
  if (repArmed && inGreen && !repHit) {
    repHit = true;
    repCount++;
  }

  if (repArmed && kneeAngle < RESET_ANGLE) {
    repArmed = false;
    repHit = false;
  }
}

void postToServer(float kneeAngle, int flexAdc) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected");
    return;
  }

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");

  // Keep backend math simple: knee = abs(imu2 - imu1)
  StaticJsonDocument<200> doc;
  doc["imu1"] = 0.0f;
  doc["imu2"] = kneeAngle;
  doc["flex"] = flexAdc;

  String payload;
  serializeJson(doc, payload);

  int code = http.POST(payload);
  Serial.print("angle=");
  Serial.print(kneeAngle, 1);
  Serial.print(" flex=");
  Serial.print(flexAdc);
  Serial.print(" reps=");
  Serial.print(repCount);
  Serial.print(" post=");
  Serial.println(code);

  http.end();
}

void setup() {
  Serial.begin(115200);

  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_GREEN, OUTPUT);
  pinMode(PIN_YELLOW, OUTPUT);
  pinMode(PIN_STATUS, OUTPUT);

  Serial.print("Connecting WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
  Serial.println(SERVER_URL);
}

void loop() {
  // Status LED blink (alive indicator)
  digitalWrite(PIN_STATUS, (millis() / 500) % 2);

  const int rawPot = analogRead(PIN_POT);
  const int flexAdc = (int)round(rawPot * (1023.0f / 4095.0f));
  const float kneeAngle = mapPotToAngle(rawPot);

  setZoneLeds(kneeAngle);
  updateRepCount(kneeAngle);

  if (millis() - lastSendMs >= SEND_EVERY_MS) {
    lastSendMs = millis();
    postToServer(kneeAngle, flexAdc);
  }

  delay(30);
}