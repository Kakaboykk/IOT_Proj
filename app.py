"""
Knee Rehabilitation Monitoring System
Flask Backend — Live ingest + API Endpoints
"""

from flask import Flask, jsonify, render_template, request
import threading
import time

app = Flask(__name__)

# ─────────────────────────────────────────────
#  LIVE STATE (no fallback / no simulation)
# ─────────────────────────────────────────────
state = {
    # running = "we have received a recent device update"
    "running": False,
    "accepting_updates": True,
    "last_update_ms": None,     # monotonic timestamp of last /update
    "update_count": 0,
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
    "history": [],           # Last N data points for graph
    "rep_history": [],       # Rep timestamps
}

HISTORY_MAX = 60   # Keep last 60 data points
TARGET_ANGLE = 90  # Rehabilitation target angle (degrees)
TARGET_TOLERANCE = 5  # Match firmware: ±5° counts as "in zone"

_state_lock = threading.Lock()


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _is_fresh(last_update_ms: int | None, max_age_ms: int = 2500) -> bool:
    if last_update_ms is None:
        return False
    return (_now_ms() - last_update_ms) <= max_age_ms


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
    with _state_lock:
        s = state
        fresh = _is_fresh(s["last_update_ms"])
        s["running"] = fresh

        # No fallback: if we have never received live data, fail loudly.
        if s["last_update_ms"] is None:
            return jsonify({
                "error": "NO_LIVE_DATA",
                "message": "No device data received yet. Start the Wokwi simulation and ensure it can reach /update.",
            }), 503

        age_ms = _now_ms() - s["last_update_ms"] if s["last_update_ms"] is not None else None
        return jsonify({
            "running":      s["running"],
            "last_update_age_ms": age_ms,
            "update_count": s["update_count"],
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


@app.route("/update", methods=["POST"])
def update():
    """
    Device ingest endpoint.
    Wokwi/ESP32 posts JSON: {"imu1": <deg>, "imu2": <deg>, "flex": <0-1023-ish>}
    """
    if not request.is_json:
        return jsonify({"error": "BAD_REQUEST", "message": "Expected application/json"}), 415

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "BAD_REQUEST", "message": "Invalid JSON body"}), 400

    missing = [k for k in ("imu1", "imu2", "flex") if k not in payload]
    if missing:
        return jsonify({"error": "BAD_REQUEST", "message": f"Missing keys: {', '.join(missing)}"}), 400

    try:
        imu1 = float(payload["imu1"])
        imu2 = float(payload["imu2"])
        flex = float(payload["flex"])
    except (TypeError, ValueError):
        return jsonify({"error": "BAD_REQUEST", "message": "imu1/imu2/flex must be numbers"}), 400

    with _state_lock:
        s = state
        if not s["accepting_updates"]:
            return jsonify({"status": "ignored", "reason": "paused"}), 409

        s["last_update_ms"] = _now_ms()
        s["update_count"] += 1
        s["imu1_angle"] = round(imu1, 2)
        s["imu2_angle"] = round(imu2, 2)
        s["flex_sensor"] = int(round(flex))

        # Knee angle and target detection
        raw_knee = abs(s["imu2_angle"] - s["imu1_angle"])
        s["knee_angle"] = round(min(raw_knee, 175.0), 2)
        s["target_zone"] = abs(s["knee_angle"] - TARGET_ANGLE) <= TARGET_TOLERANCE

        # Rep counting (server-side, derived from live knee angle)
        if s["knee_angle"] >= TARGET_ANGLE - 5 and not s["in_rep"]:
            s["in_rep"] = True
        elif s["knee_angle"] < 50 and s["in_rep"]:
            s["in_rep"] = False
            s["reps"] += 1
            s["rep_history"].append({"rep": s["reps"], "time": time.strftime("%H:%M:%S")})

        # Indicators: 3-zone classification for demo clarity
        lower = TARGET_ANGLE - TARGET_TOLERANCE
        upper = TARGET_ANGLE + TARGET_TOLERANCE
        s["led_green"] = lower <= s["knee_angle"] <= upper
        s["led_red"] = s["knee_angle"] < lower
        s["led_yellow"] = s["knee_angle"] > upper
        s["haptic"] = s["target_zone"]

        # History
        s["history"].append({
            "time": time.strftime("%H:%M:%S"),
            "knee_angle": s["knee_angle"],
            "imu1": s["imu1_angle"],
            "imu2": s["imu2_angle"],
            "flex": s["flex_sensor"],
        })
        if len(s["history"]) > HISTORY_MAX:
            s["history"].pop(0)

        # Lightweight visibility: shows up in Flask console
        if s["update_count"] <= 5 or (s["update_count"] % 25 == 0):
            print(
                f"/update #{s['update_count']} imu1={s['imu1_angle']} imu2={s['imu2_angle']} "
                f"knee={s['knee_angle']} flex={s['flex_sensor']}"
            )

    return jsonify({"status": "ok"})


@app.route("/", methods=["POST"])
def update_root_fallback():
    """
    Backward-compatible ingest route.
    Some firmware builds may still POST to "/" instead of "/update".
    """
    return update()


@app.route("/start")
def start():
    """Resume accepting live updates from the device."""
    with _state_lock:
        state["accepting_updates"] = True
    return jsonify({"status": "started"})


@app.route("/stop")
def stop():
    """Pause ingestion (dashboard will keep last received values)."""
    with _state_lock:
        state["accepting_updates"] = False
        state["running"] = False
    return jsonify({"status": "stopped"})


@app.route("/reset")
def reset():
    """Reset rep counter and clear history (does not generate new data)."""
    with _state_lock:
        state["reps"] = 0
        state["in_rep"] = False
        state["history"] = []
        state["rep_history"] = []
    return jsonify({"status": "reset"})


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  Knee Rehab Monitor — Flask Server")
    print("  Open: http://127.0.0.1:5000")
    print("=" * 50)
    # Bind to 0.0.0.0 so the Wokwi simulator can reach it via host.wokwi.internal
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)