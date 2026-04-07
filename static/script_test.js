/* ════════════════════════════════════════════
   KneeRehab Monitor — Frontend JavaScript
   Live updates every 500ms via fetch(/data)
   ════════════════════════════════════════════ */

   "use strict";

   // ── CONFIG ──────────────────────────────────
   const POLL_MS   = 500;      // fetch interval
   const MAX_PTS   = 30;       // chart max data points
   const REP_GOAL  = 10;       // progress bar goal
   
   // ── STATE ───────────────────────────────────
   let polling     = null;     // setInterval handle
   let simRunning  = false;
   let prevReps    = 0;
   let pingStart   = 0;
   
   // ── DOM REFS ────────────────────────────────
   const elKneeVal   = document.getElementById("kneeAngleVal");
   const elRepCount  = document.getElementById("repCount");
   const elRepBar    = document.getElementById("repBar");
   const elFlexVal   = document.getElementById("flexVal");
   const elFlexFill  = document.getElementById("flexRingFill");
   const elImu1Val   = document.getElementById("imu1Val");
   const elImu2Val   = document.getElementById("imu2Val");
   const elImu1Bar   = document.getElementById("imu1Bar");
   const elImu2Bar   = document.getElementById("imu2Bar");
   const elLedGreen  = document.getElementById("ledGreen");
   const elLedRed    = document.getElementById("ledRed");
   const elLedYellow = document.getElementById("ledYellow");
   const elHaptic    = document.getElementById("hapticRow");
   const elZoneBadge = document.getElementById("zoneBadge");
   const elPulse     = document.getElementById("pulseStatus");
   const elStatusLbl = document.getElementById("statusLabel");
   const elRepLog    = document.getElementById("repLog");
   const elPing      = document.getElementById("footerPing");
   const btnStart    = document.getElementById("btnStart");
   const btnStop     = document.getElementById("btnStop");
   
   
   /* ══════════════════════════════════════════
      SEMI-CIRCULAR GAUGE (Canvas)
   ══════════════════════════════════════════ */
   const gaugeCanvas = document.getElementById("gaugeCanvas");
   const gCtx        = gaugeCanvas.getContext("2d");
   
   function drawGauge(angle) {
     const W = gaugeCanvas.width;
     const H = gaugeCanvas.height;
     const cx = W / 2, cy = H - 10;
     const r  = 80;
   
     gCtx.clearRect(0, 0, W, H);
   
     // Track arc (grey background)
     gCtx.beginPath();
     gCtx.arc(cx, cy, r, Math.PI, 0, false);
     gCtx.lineWidth = 14;
     gCtx.strokeStyle = "#1e2438";
     gCtx.lineCap = "round";
     gCtx.stroke();
   
     // Target zone highlight (80–100°, i.e. ±10° of 90°)
     const toRad = deg => (Math.PI * (1 - deg / 180));
     gCtx.beginPath();
     gCtx.arc(cx, cy, r, toRad(100), toRad(80), false);
     gCtx.lineWidth = 14;
     gCtx.strokeStyle = "rgba(0,255,136,0.25)";
     gCtx.stroke();
   
     // Value arc
     const clamp    = Math.min(Math.max(angle, 0), 175);
     const endAngle = Math.PI - (clamp / 175) * Math.PI;
   
     const inZone = Math.abs(angle - 90) <= 10;
     const color  = angle > 100 ? "#ff3c5a"
                  : inZone       ? "#00ff88"
                  :                "#00e5ff";
   
     gCtx.beginPath();
     gCtx.arc(cx, cy, r, Math.PI, endAngle, false);
     gCtx.lineWidth = 14;
     gCtx.strokeStyle = color;
     gCtx.lineCap = "round";
     gCtx.stroke();
   
     // Needle tip
     const nx = cx + (r) * Math.cos(Math.PI - (clamp / 175) * Math.PI) * -1;
     const ny = cy + (r) * Math.sin(Math.PI - (clamp / 175) * Math.PI) * -1;
     gCtx.beginPath();
     gCtx.arc(nx, ny, 6, 0, Math.PI * 2);
     gCtx.fillStyle = color;
     gCtx.shadowColor = color;
     gCtx.shadowBlur = 12;
     gCtx.fill();
     gCtx.shadowBlur = 0;
   
     // Degree ticks & labels
     gCtx.font = "9px 'Share Tech Mono'";
     gCtx.fillStyle = "#5a6480";
     gCtx.textAlign = "center";
     [0, 30, 60, 90, 120, 150, 175].forEach(d => {
       const a = Math.PI * (1 - d / 175);
       const tx = cx + (r + 18) * Math.cos(a) * -1;
       const ty = cy + (r + 18) * Math.sin(a) * -1;
       gCtx.fillText(d + "°", tx, ty + 3);
     });
   }
   
   
   /* ══════════════════════════════════════════
      CHART.JS — Knee Angle (line)
   ══════════════════════════════════════════ */
   const kneeChart = new Chart(document.getElementById("chartKnee"), {
     type: "line",
     data: {
       labels: [],
       datasets: [{
         label: "Knee Angle (°)",
         data: [],
         borderColor:     "#00e5ff",
         backgroundColor: "rgba(0,229,255,0.08)",
         borderWidth: 2,
         pointRadius: 0,
         tension: 0.4,
         fill: true,
       }, {
         label: "Target 90°",
         data: [],
         borderColor:     "rgba(0,255,136,0.4)",
         borderWidth: 1.5,
         borderDash: [6, 4],
         pointRadius: 0,
         fill: false,
       }]
     },
     options: chartOptions("Angle (°)", 0, 180)
   });
   
   
   /* ══════════════════════════════════════════
      CHART.JS — IMU Comparison (line)
   ══════════════════════════════════════════ */
   const imuChart = new Chart(document.getElementById("chartIMU"), {
     type: "line",
     data: {
       labels: [],
       datasets: [{
         label: "IMU 1 (Above knee)",
         data: [],
         borderColor: "#00e5ff",
         borderWidth: 2,
         pointRadius: 0,
         tension: 0.4,
       }, {
         label: "IMU 2 (Below knee)",
         data: [],
         borderColor: "#7b5ea7",
         borderWidth: 2,
         pointRadius: 0,
         tension: 0.4,
       }]
     },
     options: chartOptions("Angle (°)", 0, 200)
   });
   
   
   /* Shared chart options factory */
   function chartOptions(yLabel, yMin, yMax) {
     return {
       responsive: true,
       animation: { duration: 300 },
       interaction: { intersect: false, mode: "index" },
       scales: {
         x: {
           ticks:  { color: "#5a6480", font: { family: "'Share Tech Mono'", size: 9 }, maxTicksLimit: 6 },
           grid:   { color: "#1e2438" },
         },
         y: {
           min: yMin, max: yMax,
           ticks:  { color: "#5a6480", font: { family: "'Share Tech Mono'", size: 10 } },
           grid:   { color: "#1e2438" },
           title:  { display: true, text: yLabel, color: "#5a6480", font: { size: 10, family: "'Share Tech Mono'" } },
         }
       },
       plugins: {
         legend: { labels: { color: "#c9d1e8", font: { family: "'Share Tech Mono'", size: 10 }, boxWidth: 14 } },
       }
     };
   }
   
   
   /* ══════════════════════════════════════════
      UPDATE CHARTS with history array
   ══════════════════════════════════════════ */
   function updateCharts(history) {
     const labels = history.map(h => h.time);
     const knees  = history.map(h => h.knee_angle);
     const imu1s  = history.map(h => h.imu1);
     const imu2s  = history.map(h => h.imu2);
     const target = history.map(() => 90);
   
     // Knee angle chart
     kneeChart.data.labels = labels;
     kneeChart.data.datasets[0].data = knees;
     kneeChart.data.datasets[1].data = target;
     kneeChart.update("none");
   
     // IMU comparison chart
     imuChart.data.labels = labels;
     imuChart.data.datasets[0].data = imu1s;
     imuChart.data.datasets[1].data = imu2s;
     imuChart.update("none");
   }
   
   
   /* ══════════════════════════════════════════
      UPDATE DOM from data snapshot
   ══════════════════════════════════════════ */
   function updateUI(d) {
     // ── Knee angle gauge ──
     const angle = d.knee_angle;
     drawGauge(angle);
     elKneeVal.textContent = angle.toFixed(1) + "°";
   
     // Zone badge
     if (d.target_zone) {
       elZoneBadge.textContent = "✓ IN TARGET ZONE";
       elZoneBadge.classList.add("in-zone");
     } else {
       elZoneBadge.textContent = "OUT OF ZONE";
       elZoneBadge.classList.remove("in-zone");
     }
   
     // ── Reps ──
     if (d.reps !== prevReps) {
       elRepCount.classList.add("pop");
       setTimeout(() => elRepCount.classList.remove("pop"), 300);
       prevReps = d.reps;
     }
     elRepCount.textContent = d.reps;
     elRepBar.style.width = Math.min((d.reps / REP_GOAL) * 100, 100) + "%";
   
     // ── Flex sensor ring ──
     const flexPct = Math.min(d.flex_sensor / 1023, 1);
     const circ    = 2 * Math.PI * 50;          // r=50 → ~314
     elFlexFill.style.strokeDashoffset = circ - flexPct * circ;
     elFlexFill.style.stroke           = flexPct > 0.7 ? "var(--accent2)" : "var(--accent)";
     elFlexVal.textContent = d.flex_sensor;
   
     // ── IMU values ──
     elImu1Val.textContent = d.imu1_angle.toFixed(1) + "°";
     elImu2Val.textContent = d.imu2_angle.toFixed(1) + "°";
     elImu1Bar.style.width = Math.min(d.imu1_angle / 180 * 100, 100) + "%";
     elImu2Bar.style.width = Math.min(d.imu2_angle / 180 * 100, 100) + "%";
   
     // ── LEDs ──
     elLedGreen.classList.toggle("on",  d.led_green);
     elLedRed.classList.toggle("on",    d.led_red);
     elLedYellow.classList.toggle("on", d.led_yellow);
   
     // ── Haptic feedback ──
     if (d.haptic) {
       elHaptic.classList.add("active");
     } else {
       elHaptic.classList.remove("active");
     }
   
     // ── Rep log ──
     if (d.rep_history && d.rep_history.length > 0) {
       elRepLog.innerHTML = d.rep_history.map(r =>
         `<li>
            <span class="log-rep-num">REP #${r.rep}</span>
            <span class="log-rep-time">${r.time}</span>
          </li>`
       ).reverse().join("");
     }
   
     // ── Charts ──
     if (d.history && d.history.length > 0) {
       updateCharts(d.history);
     }
   }
   
   
   /* ══════════════════════════════════════════
      FETCH /data  (polling loop)
   ══════════════════════════════════════════ */
   async function fetchData() {
     pingStart = performance.now();
     try {
       const res  = await fetch("/data");
       const data = await res.json();
       const ping = Math.round(performance.now() - pingStart);
       elPing.textContent = `API PING: ${ping} ms`;
       updateUI(data);
     } catch (err) {
       elPing.textContent = "API ERROR";
       console.error("Fetch error:", err);
     }
   }
   
   
   /* ══════════════════════════════════════════
      CONTROL BUTTONS
   ══════════════════════════════════════════ */
   window.startSim = async function () {
     await fetch("/start");
     simRunning = true;
     elPulse.classList.add("active");
     elStatusLbl.textContent = "RUNNING";
     btnStart.disabled = true;
     btnStop.disabled  = false;
     if (!polling) {
       polling = setInterval(fetchData, POLL_MS);
       fetchData();   // immediate first fetch
     }
   }
   
   window.stopSim = async function () {
     await fetch("/stop");
     simRunning = false;
     elPulse.classList.remove("active");
     elStatusLbl.textContent = "PAUSED";
     btnStart.disabled = false;
     btnStop.disabled  = true;
   }
   
    window.resetSim = async function ()  {
     await fetch("/reset");
     prevReps = 0;
     elRepLog.innerHTML = `<li class="log-empty">No reps yet — start the simulation</li>`;
     drawGauge(0);
     elKneeVal.textContent = "0.0°";
     elRepCount.textContent = "0";
     elRepBar.style.width = "0%";
     elFlexVal.textContent = "0";
     elFlexFill.style.strokeDashoffset = "314";
     elImu1Val.textContent = "0.0°";
     elImu2Val.textContent = "0.0°";
     kneeChart.data.labels = [];
     kneeChart.data.datasets.forEach(ds => ds.data = []);
     kneeChart.update();
     imuChart.data.labels = [];
     imuChart.data.datasets.forEach(ds => ds.data = []);
     imuChart.update();
   }
   
   
   /* ══════════════════════════════════════════
      CLOCK
   ══════════════════════════════════════════ */
   function updateClock() {
     const now = new Date();
     document.getElementById("headerTime").textContent =
       now.toTimeString().slice(0, 8);
   }
   setInterval(updateClock, 1000);
   updateClock();
   
   // Initial gauge draw
   drawGauge(0);