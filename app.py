"""
Knee Rehabilitation Monitoring System
Flask Backend — Simulation Logic + API Endpoints
"""

from flask import Flask, jsonify, render_template
import threading
import time
import math
import random

app = Flask(__name__)

# ─────────────────────────────────────────────
#  SIMULATION STATE
# ─────────────────────────────────────────────
state = {
    "running": False,
    "imu1_angle": 0.0,       # Above-knee IMU
    "imu2_angle": 0.0,       # Below-knee IMU
    "knee_angle": 0.0,       # Calculated knee flex angle
    "flex_sensor": 0,        # 0–1023 (ADC-style value)
    "reps": 0,
    "in_rep": False,
    "target_zone": False,    # True when knee_angle near 90°
    "led_green": False,
    "led_red": False,
    "led_yellow": False,
    "haptic": False,
    "phase": 0.0,            # Sine wave phase counter
    "history": [],           # Last N data points for graph
    "rep_history": [],       # Rep timestamps
}

HISTORY_MAX = 60   # Keep last 60 data points
TICK = 0.5         # Update every 500 ms
TARGET_ANGLE = 90  # Rehabilitation target angle (degrees)
TARGET_TOLERANCE = 10  # ±10° counts as "in zone"

_sim_thread = None
_stop_event = threading.Event()


# ─────────────────────────────────────────────
#  SIMULATION CORE
# ─────────────────────────────────────────────
def simulate_cycle():
    """
    Generate one frame of simulated sensor data.
    Uses a sine wave to mimic a realistic knee flex/extend movement.
    Noise is added to make it feel like real IMU data.
    """
    s = state

    # Advance phase (full cycle every ~6 seconds at TICK=0.5)
    s["phase"] += 0.17

    # --- IMU angles ---
    # Above-knee sensor: moves gently (thigh tilt)
    imu1_base = 30 + 15 * math.sin(s["phase"] * 0.6)
    s["imu1_angle"] = round(imu1_base + random.uniform(-1.5, 1.5), 2)

    # Below-knee sensor: swings more (shank rotation)
    imu2_base = 120 + 60 * math.sin(s["phase"])   # 60–180°
    s["imu2_angle"] = round(imu2_base + random.uniform(-2, 2), 2)

    # Knee angle = difference (how much the knee is bent)
    raw_knee = abs(s["imu2_angle"] - s["imu1_angle"])
    s["knee_angle"] = round(min(raw_knee, 175), 2)

    # --- Flex sensor ---
    # Map knee_angle (0–175) → ADC value (100–950)
    flex_base = int((s["knee_angle"] / 175) * 850) + 100
    s["flex_sensor"] = flex_base + random.randint(-20, 20)

    # --- Target zone detection ---
    s["target_zone"] = abs(s["knee_angle"] - TARGET_ANGLE) <= TARGET_TOLERANCE

    # --- Rep counting ---
    # A rep is completed when angle crosses 90° going up then comes back
    if s["knee_angle"] >= TARGET_ANGLE - 5 and not s["in_rep"]:
        s["in_rep"] = True
    elif s["knee_angle"] < 50 and s["in_rep"]:
        s["in_rep"] = False
        s["reps"] += 1
        s["rep_history"].append({"rep": s["reps"], "time": time.strftime("%H:%M:%S")})

    # --- LED indicators ---
    s["led_green"] = s["target_zone"]                           # In target zone
    s["led_red"] = s["knee_angle"] > TARGET_ANGLE + TARGET_TOLERANCE  # Over-flexed
    s["led_yellow"] = s["knee_angle"] < TARGET_ANGLE - TARGET_TOLERANCE  # Under-flexed

    # --- Haptic feedback ---
    # Buzz when entering target zone
    s["haptic"] = s["target_zone"]

    # --- History for graph ---
    s["history"].append({
        "time": time.strftime("%H:%M:%S"),
        "knee_angle": s["knee_angle"],
        "imu1": s["imu1_angle"],
        "imu2": s["imu2_angle"],
        "flex": s["flex_sensor"],
    })
    if len(s["history"]) > HISTORY_MAX:
        s["history"].pop(0)


def simulation_loop():
    """Background thread: runs simulate_cycle() every TICK seconds."""
    while not _stop_event.is_set():
        if state["running"]:
            simulate_cycle()
        time.sleep(TICK)


# Start the background thread once on startup
_sim_thread = threading.Thread(target=simulation_loop, daemon=True)
_sim_thread.start()


# ─────────────────────────────────────────────
#  FLASK ROUTES
# ─────────────────────────────────────────────
@app.route("/")
def dashboard():
    """Serve the main dashboard HTML page."""
    return render_template("index.html")


@app.route("/data")
def data():
    """
    API endpoint — returns current sensor snapshot as JSON.
    Called by the frontend every 500 ms via fetch().
    """
    s = state
    return jsonify({
        "running":      s["running"],
        "imu1_angle":   s["imu1_angle"],
        "imu2_angle":   s["imu2_angle"],
        "knee_angle":   s["knee_angle"],
        "flex_sensor":  s["flex_sensor"],
        "reps":         s["reps"],
        "in_rep":       s["in_rep"],
        "target_zone":  s["target_zone"],
        "led_green":    s["led_green"],
        "led_red":      s["led_red"],
        "led_yellow":   s["led_yellow"],
        "haptic":       s["haptic"],
        "history":      s["history"][-30:],   # last 30 points
        "rep_history":  s["rep_history"][-10:],
    })


@app.route("/start")
def start():
    """Start the simulation."""
    state["running"] = True
    return jsonify({"status": "started"})


@app.route("/stop")
def stop():
    """Pause the simulation (state is preserved)."""
    state["running"] = False
    return jsonify({"status": "stopped"})


@app.route("/reset")
def reset():
    """Reset rep counter and clear history."""
    state["reps"] = 0
    state["in_rep"] = False
    state["history"] = []
    state["rep_history"] = []
    state["phase"] = 0.0
    return jsonify({"status": "reset"})


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  Knee Rehab Monitor — Flask Server")
    print("  Open: http://127.0.0.1:5000")
    print("=" * 50)
    app.run(debug=True, use_reloader=False)