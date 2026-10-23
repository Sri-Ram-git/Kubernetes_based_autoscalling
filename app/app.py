"""
Sample Cloud Web Application for Auto-Scaling Framework Demonstrations.
Project ID: 357 | Alliance University, Bengaluru

Features:
- Responsive HTML UI for interactive demonstration
- Prometheus telemetry instrumentation (/metrics)
- Kubernetes health probes (/healthz, /readyz)
- Configurable synthetic CPU load generation (/load)
- Repeatable HTTP traffic surge generator (/generate-traffic)
"""

import math
import os
import time

try:
    import psutil
except ImportError:
    psutil = None

from flask import Flask, jsonify, request, Response, render_template_string
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

app = Flask(__name__)

# Prometheus Metrics Definitions
REQUEST_COUNT = Counter(
    "sample_app_requests_total",
    "Total HTTP requests received by the sample web application",
    ["method", "endpoint", "status"],
)

REQUEST_DURATION = Histogram(
    "sample_app_request_duration_seconds",
    "HTTP request latency in seconds",
    ["endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0],
)

CPU_BURDEN_GAUGE = Gauge(
    "sample_app_active_load_workers",
    "Number of active synthetic CPU load tasks running",
)

CPU_UTILIZATION_GAUGE = Gauge(
    "sample_app_cpu_utilization_percent",
    "Current CPU utilization percentage of the sample web application",
)

MEMORY_UTILIZATION_GAUGE = Gauge(
    "sample_app_memory_utilization_percent",
    "Current memory utilization percentage of the sample web application",
)

POD_NAME = os.getenv("HOSTNAME", "local-pod")
NODE_NAME = os.getenv("NODE_NAME", "local-node")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sample Web App — KubePilot</title>
    <style>
        :root {
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #334155;
            --border: #334155;
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --success: #10b981;
            --success-bg: rgba(16, 185, 129, 0.15);
            --warning: #f59e0b;
        }
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            margin: 0;
            padding: 2.5rem 1rem;
            display: flex;
            justify-content: center;
        }
        .container {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            max-width: 680px;
            width: 100%;
            padding: 2rem;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 1.25rem;
            margin-bottom: 1.5rem;
        }
        .header h1 {
            font-size: 1.35rem;
            margin: 0;
            color: #38bdf8;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .badge {
            background: var(--success-bg);
            color: var(--success);
            padding: 0.25rem 0.65rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        .stat-card {
            background: #0f172a;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
        }
        .stat-title {
            font-size: 0.72rem;
            color: var(--text-muted);
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.05em;
        }
        .stat-value {
            font-size: 1.15rem;
            font-weight: 700;
            margin-top: 0.35rem;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            word-break: break-all;
        }
        .actions {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
            margin-top: 1.25rem;
        }
        button {
            background: var(--primary);
            color: #fff;
            border: none;
            border-radius: 8px;
            padding: 0.85rem 1.25rem;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease-in-out;
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 0.5rem;
        }
        button:hover { background: var(--primary-hover); transform: translateY(-1px); }
        button:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        button.secondary { background: #334155; }
        button.secondary:hover { background: #475569; }
        #console-output {
            margin-top: 1.25rem;
            padding: 1rem;
            border-radius: 8px;
            background: #020617;
            border: 1px solid #1e293b;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;
            font-size: 0.82rem;
            min-height: 48px;
            display: none;
            white-space: pre-wrap;
            line-height: 1.4;
        }
        .links {
            margin-top: 1.75rem;
            padding-top: 1rem;
            border-top: 1px solid var(--border);
            display: flex;
            gap: 1.25rem;
            font-size: 0.85rem;
        }
        .links a { color: #38bdf8; text-decoration: none; }
        .links a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>Cloud Workload Microservice</h1>
                <p style="color: var(--text-muted); font-size: 0.85rem; margin: 0.25rem 0 0 0;">
                    KubePilot &bull; Kubernetes Auto-Scaling Target
                </p>
            </div>
            <span class="badge">Running</span>
        </div>

        <div class="grid">
            <div class="stat-card">
                <div class="stat-title">Pod Identity</div>
                <div class="stat-value">{{ pod }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">Kubernetes Node</div>
                <div class="stat-value">{{ node }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-title">Prometheus Telemetry</div>
                <div class="stat-value"><a href="/metrics" style="color: #38bdf8; text-decoration: none;">/metrics</a></div>
            </div>
            <div class="stat-card">
                <div class="stat-title">Health Probes</div>
                <div class="stat-value" style="color: var(--success); font-size: 0.95rem;">Liveness &amp; Readiness OK</div>
            </div>
        </div>

        <div class="actions">
            <button id="btn-traffic" onclick="generateTraffic(50)">
                ⚡ Generate 50 HTTP Requests (Traffic Surge)
            </button>
            <button id="btn-load" class="secondary" onclick="simulateLoad(10)">
                🔥 Simulate CPU Load (10 Seconds Math Loop)
            </button>
        </div>

        <div id="console-output"></div>

        <div class="links">
            <a href="/healthz" target="_blank">/healthz</a>
            <a href="/readyz" target="_blank">/readyz</a>
            <a href="/metrics" target="_blank">/metrics</a>
            <a href="/?format=json" target="_blank">JSON Payload</a>
        </div>
    </div>

    <script>
        const out = document.getElementById("console-output");
        
        async function generateTraffic(count) {
            const btn = document.getElementById("btn-traffic");
            btn.disabled = true;
            btn.textContent = "Sending burst traffic...";
            out.style.display = "block";
            out.style.color = "#38bdf8";
            out.textContent = `[INFO] Generating ${count} HTTP requests against workload telemetry...`;

            try {
                const res = await fetch(`/generate-traffic?count=${count}`);
                const data = await res.json();
                out.style.color = "#34d399";
                out.textContent = `[SUCCESS] ${data.requests_generated} requests recorded in Prometheus counters! Latency: ${data.duration_ms}ms.`;
            } catch (err) {
                out.style.color = "#f87171";
                out.textContent = `[ERROR] Failed to generate traffic: ${err.message}`;
            } finally {
                btn.disabled = false;
                btn.textContent = "⚡ Generate 50 HTTP Requests (Traffic Surge)";
            }
        }

        async function simulateLoad(duration) {
            const btn = document.getElementById("btn-load");
            btn.disabled = true;
            btn.textContent = `Computing math load (${duration}s)...`;
            out.style.display = "block";
            out.style.color = "#f59e0b";
            out.textContent = `[INFO] Synthesizing high CPU load for ${duration}s on pod {{ pod }}...`;

            try {
                const res = await fetch(`/load?duration=${duration}`);
                const data = await res.json();
                out.style.color = "#34d399";
                out.textContent = `[SUCCESS] ${data.iterations_computed.toLocaleString()} iterations completed in ${data.duration_seconds}s on pod ${data.pod}.`;
            } catch (err) {
                out.style.color = "#f87171";
                out.textContent = `[ERROR] Load simulation failed: ${err.message}`;
            } finally {
                btn.disabled = false;
                btn.textContent = "🔥 Simulate CPU Load (10 Seconds Math Loop)";
            }
        }
    </script>
</body>
</html>
"""


@app.before_request
def start_timer():
    request._start_time = time.time()


@app.after_request
def record_metrics(response):
    if hasattr(request, "_start_time") and request.path != "/metrics":
        latency = time.time() - request._start_time
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.path,
            status=response.status_code,
        ).inc()
        REQUEST_DURATION.labels(endpoint=request.path).observe(latency)
    return response


@app.route("/")
def index():
    # Return JSON if requested explicitly or if curl/API client
    format_param = request.args.get("format", "")
    accept_header = request.headers.get("Accept", "")

    if format_param == "json" or ("application/json" in accept_header and "text/html" not in accept_header):
        return jsonify({
            "status": "healthy",
            "service": "sample-web-app",
            "pod": POD_NAME,
            "node": NODE_NAME,
            "framework": "KubePilot - Alliance University",
            "timestamp": time.time(),
        })

    return render_template_string(HTML_TEMPLATE, pod=POD_NAME, node=NODE_NAME)


@app.route("/healthz")
def healthz():
    """Liveness probe endpoint."""
    return jsonify({"status": "ok", "pod": POD_NAME}), 200


@app.route("/readyz")
def readyz():
    """Readiness probe endpoint."""
    return jsonify({"status": "ready", "pod": POD_NAME}), 200


@app.route("/generate-traffic")
def generate_traffic():
    """
    Repeatable endpoint to generate synthetic HTTP request traffic for autoscaling verification.
    """
    count = int(request.args.get("count", 50))
    count = max(1, min(count, 500))  # Bound between 1 and 500

    start = time.time()
    for _ in range(count):
        REQUEST_COUNT.labels(
            method="GET",
            endpoint="/",
            status=200,
        ).inc()
        REQUEST_DURATION.labels(endpoint="/").observe(0.005)

    duration_ms = round((time.time() - start) * 1000, 2)
    return jsonify({
        "success": True,
        "requests_generated": count,
        "target_endpoint": "/",
        "pod": POD_NAME,
        "duration_ms": duration_ms,
    })


@app.route("/metrics")
def metrics():
    """Prometheus telemetry scrape endpoint."""
    if psutil:
        try:
            CPU_UTILIZATION_GAUGE.set(psutil.cpu_percent(interval=None))
            MEMORY_UTILIZATION_GAUGE.set(psutil.virtual_memory().percent)
        except Exception:
            pass
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route("/load")
def burn_cpu():
    """
    Simulates CPU-intensive computations for a given duration.
    Usage: /load?duration=10 (seconds)
    """
    duration = float(request.args.get("duration", 5.0))
    duration = min(duration, 60.0)  # Bound to 60s max for safety

    CPU_BURDEN_GAUGE.inc()
    start = time.time()
    iterations = 0

    # CPU-bound math loop
    while time.time() - start < duration:
        _ = [math.sqrt(i) * math.sin(i) for i in range(5000)]
        iterations += 5000

    CPU_BURDEN_GAUGE.dec()
    elapsed = time.time() - start

    return jsonify({
        "message": f"Simulated CPU load completed on pod {POD_NAME}",
        "duration_seconds": round(elapsed, 2),
        "iterations_computed": iterations,
        "pod": POD_NAME,
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
