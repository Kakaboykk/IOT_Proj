#include <Arduino.h>
#include <Wire.h>
#include <MPU6050.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// --- Network Setup ---
const char* ssid = "Wokwi-GUEST";
const char* password = "";

// Wokwi simulation mode:
// Wokwi runs in a sandbox. Use host.wokwi.internal to reach Flask on your PC.
const String serverName = "http://host.wokwi.internal:5000/update";

// Initialize IMU Sensors
MPU6050 imuAbove(0x68);
MPU6050 imuBelow(0x69);

// Pin Definitions
const int PIN_VIBRATION  = 2;
const int PIN_LED_GREEN  = 26;
const int PIN_LED_YELLOW = 25;
const int PIN_STATUS     = 13;
const int PIN_FLEX       = 34;

// Thresholds for Rep Counting
const float TARGET_ANGLE  = 90.0;
const float TOLERANCE     = 5.0;
const float RESET_ANGLE   = 20.0;
const unsigned long MOTOR_DURATION_MS = 600;

// Logic Variables
int repCount = 0;
bool repActive = false;
bool targetHit = false;
bool motorActive = false;
unsigned long motorStartTime = 0;

unsigned long lastPrint = 0;
const unsigned long PRINT_INTERVAL = 200; // 5 updates per second

// Simulator usability:
// true  -> drive knee angle directly from potentiometer (recommended for Wokwi)
// false -> compute knee angle from IMU pitch difference
const bool SIM_USE_POT_FOR_KNEE = true;
const float SIM_KNEE_MIN_DEG = 0.0f;
const float SIM_KNEE_MAX_DEG = 130.0f;

// Function to calculate pitch from MPU6050
float getPitchAngle(MPU6050 &imu) {
  int16_t ax, ay, az, gx, gy, gz;
  imu.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);

  float aX = ax / 16384.0f;
  float aY = ay / 16384.0f;
  float aZ = az / 16384.0f;

  float pitch = atan2(aY, sqrt(aX * aX + aZ * aZ)) * 180.0f / PI;
  return pitch;
}

void triggerHaptic() {
  digitalWrite(PIN_VIBRATION, HIGH);
  motorActive = true;
  motorStartTime = millis();
}

void printProgressBar(float angle, float maxAngle = 180.0) {
  int bars = (int)((angle / maxAngle) * 25.0f);
  bars = constrain(bars, 0, 25);
  int target = (int)((TARGET_ANGLE / maxAngle) * 25.0f);

  Serial.print("|");
  for (int i = 0; i < 25; i++) {
    if (i == target) Serial.print("|");
    else if (i < bars) Serial.print("=");
    else Serial.print(".");
  }
  Serial.print("| ");
  Serial.print(angle, 1);
  Serial.print(" deg");
}

void setup() {
  Serial.begin(115200);
  delay(500);

  Wire.begin(21, 22);

  pinMode(PIN_VIBRATION, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_STATUS, OUTPUT);

  imuAbove.initialize();
  imuBelow.initialize();

  // Connect to Wokwi Virtual WiFi
  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  while(WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");
  Serial.print("WiFi IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("Posting to: ");
  Serial.println(serverName);
  Serial.println("JOINT TRACK LIVE: LOCALHOST MODE");
}

void loop() {
  unsigned long now = millis();

  // 1. Read Raw Sensors
  float pitchAbove = getPitchAngle(imuAbove);
  float pitchBelow = getPitchAngle(imuBelow);
  int flexRaw = analogRead(PIN_FLEX);

  // 2. Format data (Synced with Flask/Dashboard logic)
  float flexAdc = flexRaw * (1023.0f / 4095.0f);
  float kneeAngle = abs(pitchBelow - pitchAbove);

  if (SIM_USE_POT_FOR_KNEE) {
    // In simulator mode, use one control to directly set joint angle.
    float potNorm = flexRaw / 4095.0f;
    kneeAngle = SIM_KNEE_MIN_DEG + potNorm * (SIM_KNEE_MAX_DEG - SIM_KNEE_MIN_DEG);

    // Keep backend logic aligned (it computes knee = abs(imu2 - imu1)).
    pitchAbove = 0.0f;
    pitchBelow = kneeAngle;
  }

  // 3. Hardware Feedback Logic
  bool inTargetZone = (kneeAngle >= TARGET_ANGLE - TOLERANCE && kneeAngle <= TARGET_ANGLE + TOLERANCE);
  bool underAngle = (kneeAngle < TARGET_ANGLE - TOLERANCE);
  bool overAngle = (kneeAngle > TARGET_ANGLE + TOLERANCE);

  digitalWrite(PIN_LED_GREEN, inTargetZone ? HIGH : LOW);
  digitalWrite(PIN_LED_YELLOW, overAngle ? HIGH : LOW);
  // Red indicator in diagram is wired on PIN_VIBRATION (pin 2).
  // Keep it ON in under-angle zone unless a haptic pulse is currently active.
  if (!motorActive) {
    digitalWrite(PIN_VIBRATION, underAngle ? HIGH : LOW);
  }

  // Rep Counting Logic
  if (kneeAngle > RESET_ANGLE) {
    repActive = true;
  }

  if (inTargetZone && repActive && !targetHit) {
    targetHit = true;
    repCount++;
    triggerHaptic();
  }

  if (kneeAngle < RESET_ANGLE && repActive) {
    repActive = false;
    targetHit = false;
  }

  // Handle Haptic Motor Timer
  if (motorActive && (now - motorStartTime >= MOTOR_DURATION_MS)) {
    motorActive = false;
  }

  // Blink Status LED
  digitalWrite(PIN_STATUS, ((now / 500) % 2 == 0) ? HIGH : LOW);

  // --- Network Transmission to Local Flask ---
  if (now - lastPrint >= PRINT_INTERVAL) {
    lastPrint = now;

    // Serial Monitor Output
    Serial.print("Knee:");
    Serial.print(kneeAngle);
    Serial.print(" Flex:");
    Serial.print(flexAdc);
    Serial.print(" ");
    printProgressBar(kneeAngle);
    Serial.print(" Reps:");
    Serial.print(repCount);

    if(WiFi.status() == WL_CONNECTED) {
      HTTPClient http;
      http.begin(serverName); // Local HTTP request
      http.addHeader("Content-Type", "application/json");

      // Prepare JSON payload
      StaticJsonDocument<200> doc;
      doc["imu1"] = pitchAbove;
      doc["imu2"] = pitchBelow;
      doc["flex"] = flexAdc;

      String requestBody;
      serializeJson(doc, requestBody);

      // Execute POST
      int httpResponseCode = http.POST(requestBody);
      
      if(httpResponseCode == 200) {
        Serial.println(" [POST: OK]");
      } else {
        Serial.print(" [POST ERROR: ");
        Serial.print(httpResponseCode);
        Serial.print("] ");
        Serial.println(http.getString());
      }
      http.end();
    } else {
      Serial.println(" [WiFi Disconnected]");
    }
  }

  delay(30);
}