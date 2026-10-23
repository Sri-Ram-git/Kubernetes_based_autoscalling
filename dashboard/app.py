"""
Web Dashboard Server for Kubernetes Auto-Scaling Framework.
Project ID: 357 | Alliance University, Bengaluru

REST API-backed Dashboard providing live telemetry monitoring, PRAH decision inspection,
policy management, audit history, and operational safety controls.
"""

import json
import logging
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict

# Ensure project root is in sys.path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from flask import Flask, jsonify, render_template, request
import yaml

from controller.config import ControllerConfig
from controller.main import AutoscalingController
from controller.telemetry import MetricStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("autoscaler.dashboard")

BASE_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
    static_url_path="/static",
)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "autoscaling-dev-secret-key-357")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Global controller instance
controller_config = ControllerConfig.load()
controller = AutoscalingController(config=controller_config)


@app.route("/")
@app.route("/overview")
def overview_page():
    """Overview page for verified cluster and controller state."""
    return render_template("overview.html", current_page="overview", page_title="Cluster overview")


@app.route("/workloads")
def workloads_page():
    return render_template("workloads.html", current_page="workloads", page_title="Workloads")


@app.route("/telemetry")
def telemetry_page():
    return render_template("telemetry.html", current_page="telemetry", page_title="Telemetry")


@app.route("/policies")
def policies_page():
    return render_template("policies.html", current_page="policies", page_title="Scaling policies")


@app.route("/decisions")
def decisions_page():
    return render_template("decisions.html", current_page="decisions", page_title="Decision engine")


@app.route("/history")
def history_page():
    return render_template("history.html", current_page="history", page_title="Execution history")


@app.route("/system-health")
def system_health_page():
    return render_template("system_health.html", current_page="system-health", page_title="System health")


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return render_template("404.html", current_page="", page_title="Page not found"), 404


# ==============================================================================
# REST API Endpoints
# ==============================================================================

@app.route("/api/status", methods=["GET"])
def get_status():
    """Returns overall framework and cluster connectivity status."""
    k8s_connected, k8s_msg = controller.executor.is_connected()
    prom_connected, prom_msg = controller.prometheus_provider.check_connection()
    prom_targets = controller.prometheus_provider.get_targets_status() if prom_connected else {
        "reachable": False, "total_targets": 0, "healthy_targets": 0, "targets": []
    }
    workload = controller.executor.get_workload_state()

    return jsonify({
        "controller_running": True,
        "mode": "DRY_RUN (Safe Preview)" if controller.config.dry_run else "LIVE EXECUTION (Cluster Mutation)",
        "dry_run": controller.config.dry_run,
        "enable_live_execution": controller.config.enable_live_execution,
        "simulation_mode": controller.config.simulation_mode,
        "target": {
            "namespace": controller.config.target_namespace,
            "deployment": controller.config.target_deployment,
            "connected": workload.connected,
            "data_source": "KUBERNETES_API" if workload.connected else "SIMULATED_FALLBACK",
            "desired_replicas": workload.desired_replicas,
            "current_replicas": workload.current_replicas,
            "ready_replicas": workload.ready_replicas,
            "unavailable_replicas": workload.unavailable_replicas,
            "pods": workload.pods,
            "status_message": workload.status_message,
        },
        "connectivity": {
            "kubernetes": {
                "connected": k8s_connected,
                "message": k8s_msg,
            },
            "prometheus": {
                "connected": prom_connected,
                "message": prom_msg,
                "url": controller.config.prometheus_url,
                "total_targets": prom_targets.get("total_targets", 0),
                "healthy_targets": prom_targets.get("healthy_targets", 0),
                "targets": prom_targets.get("targets", []),
            },
        },
        "guardrails": {
            "min_replicas": controller.config.min_replicas,
            "max_replicas": controller.config.max_replicas,
            "max_scale_step_up": controller.config.max_scale_step_up,
            "max_scale_step_down": controller.config.max_scale_step_down,
            "cooldown_seconds": controller.config.cooldown_seconds,
        },
    })


@app.route("/api/workloads", methods=["GET"])
def get_workloads():
    """Returns verified observed workload state directly from Kubernetes cluster API."""
    workload = controller.executor.get_workload_state()
    return jsonify(workload.to_dict())


@app.route("/healthz")
def healthz():
    """Liveness probe endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "autoscaling-dashboard",
        "controller_running": True,
    }), 200


@app.route("/readyz")
def readyz():
    """Readiness probe endpoint checking policy engine state."""
    policies_loaded = len(controller.policy_engine.rules) > 0
    if not policies_loaded:
        return jsonify({
            "status": "not_ready",
            "reason": "Policies not loaded",
        }), 503

    return jsonify({
        "status": "ready",
        "service": "autoscaling-dashboard",
        "policies_count": len(controller.policy_engine.rules),
    }), 200


@app.route("/api/metrics", methods=["GET"])
def get_metrics():
    """Returns currently collected and validated telemetry."""
    # Read latest or fetch
    metrics = controller.latest_telemetry
    if not metrics:
        metrics = controller.fetch_current_telemetry()
        controller.latest_telemetry = metrics

    now = time.time()
    prom_connected, prom_msg = controller.prometheus_provider.check_connection()
    prom_targets = controller.prometheus_provider.get_targets_status() if prom_connected else {
        "reachable": False, "total_targets": 0, "healthy_targets": 0, "targets": []
    }

    metrics_payload = {}
    for name, sample in metrics.items():
        metrics_payload[name] = sample.to_dict()

    return jsonify({
        "metrics": metrics_payload,
        "source": "SIMULATED" if controller.config.simulation_mode else "PROMETHEUS",
        "timestamp": now,
        "prometheus_connected": prom_connected,
        "prometheus_message": prom_msg,
        "prometheus_url": controller.config.prometheus_url,
        "targets_summary": prom_targets,
    })


@app.route("/api/telemetry/refresh", methods=["POST"])
def refresh_telemetry():
    """Forces an immediate fresh query against Prometheus."""
    metrics = controller.fetch_current_telemetry()
    controller.latest_telemetry = metrics
    return jsonify({
        "success": True,
        "message": "Telemetry refreshed successfully from Prometheus.",
        "timestamp": time.time(),
        "metrics": {name: s.to_dict() for name, s in metrics.items()},
    })


@app.route("/api/telemetry/targets", methods=["GET"])
def get_telemetry_targets():
    """Returns live scrape targets status directly from Prometheus /api/v1/targets."""
    targets_info = controller.prometheus_provider.get_targets_status()
    return jsonify(targets_info)


@app.route("/api/decisions", methods=["GET"])
def get_latest_decision():
    """Returns latest PRAH decision details, competing proposals, policy evaluations, and guardrail check."""
    decision = controller.latest_decision
    guardrail = controller.latest_guardrail
    execution = controller.latest_execution

    # If no decision has run yet, trigger an initial single evaluation cycle
    if decision is None:
        try:
            controller.run_single_cycle()
            decision = controller.latest_decision
            guardrail = controller.latest_guardrail
            execution = controller.latest_execution
        except Exception as e:
            logger.warning("Initial decision cycle failed: %s", e)

    return jsonify({
        "decision": decision.to_dict() if decision else None,
        "guardrail": guardrail.to_dict() if guardrail else None,
        "execution": execution.to_dict() if execution else None,
        "policy_evaluations": [e.to_dict() for e in controller.policy_engine.latest_evaluations],
    })


@app.route("/api/history", methods=["GET"])
def get_history():
    """Returns recent structured audit records from the in-memory log buffer."""
    limit = int(request.args.get("limit", 50))
    records = controller.decision_logger.get_recent_decisions(limit=limit)
    return jsonify({
        "total": len(records),
        "records": records,
    })


@app.route("/api/policies", methods=["GET"])
def get_policies():
    """Returns the list of active scaling policies, latest rule evaluations, and configuration metadata."""
    policies = [r.to_dict() for r in controller.policy_engine.rules]
    evaluations = [e.to_dict() for e in controller.policy_engine.latest_evaluations]

    return jsonify({
        "policy_file": controller.config.policies_path,
        "target_workload": controller.policy_engine.target_workload,
        "guardrails": controller.policy_engine.guardrails_config,
        "fallback_behavior": controller.policy_engine.fallback_config,
        "conflict_resolution": controller.policy_engine.conflict_resolution_config,
        "policies": policies,
        "evaluations": evaluations,
    })


@app.route("/api/policies/update-threshold", methods=["POST"])
def update_policy_threshold():
    """Safely updates a policy threshold in memory and in the active YAML config."""
    data = request.get_json() or {}
    policy_id = data.get("id")
    new_threshold = data.get("threshold")

    if not policy_id or new_threshold is None:
        return jsonify({"error": "Missing 'id' or 'threshold'"}), 400

    try:
        new_threshold = float(new_threshold)
    except (ValueError, TypeError):
        return jsonify({"error": "Threshold must be numeric"}), 400

    if not math.isfinite(new_threshold):
        return jsonify({"error": "Threshold must be a finite number"}), 400

    # Find and update rule
    rule_found = False
    for r in controller.policy_engine.rules:
        if r.id == policy_id:
            # Check percentage bounds
            if r.metric.endswith("_percent") and (new_threshold < 0.0 or new_threshold > 100.0):
                return jsonify({"error": f"Percentage threshold for '{r.metric}' must be between 0 and 100"}), 400
            if new_threshold < 0.0:
                return jsonify({"error": "Threshold cannot be negative"}), 400

            r.threshold = new_threshold
            rule_found = True
            break

    if not rule_found:
        return jsonify({"error": f"Policy '{policy_id}' not found"}), 404

    # Save to disk
    try:
        with open(controller.config.policies_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)

        for p in yaml_data.get("policies", []):
            if p.get("id") == policy_id:
                p["threshold"] = new_threshold
                break

        with open(controller.config.policies_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(yaml_data, f, sort_keys=False)

        logger.info("Updated threshold for policy %s to %f", policy_id, new_threshold)
        return jsonify({
            "success": True,
            "message": f"Updated {policy_id} threshold to {new_threshold}",
        })
    except Exception as e:
        logger.error("Failed to persist updated policy: %s", e)
        return jsonify({"error": f"Failed to persist policy: {str(e)}"}), 500
        return jsonify({
            "success": True,
            "message": f"Updated {policy_id} threshold to {new_threshold}",
        })
    except Exception as e:
        logger.error("Failed to persist updated policy: %s", e)
        return jsonify({"error": f"Failed to persist policy: {str(e)}"}), 500


@app.route("/api/evaluate", methods=["POST"])
def trigger_evaluation():
    """Triggers an immediate single policy evaluation cycle."""
    try:
        record = controller.run_single_cycle()
        return jsonify({
            "success": True,
            "cycle_result": record,
        })
    except Exception as e:
        logger.exception("Manual evaluation failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/controls/live-execution", methods=["POST"])
def toggle_live_execution():
    """Toggles live cluster execution vs dry run mode."""
    data = request.get_json() or {}
    enable = bool(data.get("enable", False))
    if enable:
        k8s_connected, k8s_msg = controller.executor.is_connected()
        prom_connected, prom_msg = controller.prometheus_provider.check_connection()
        if not k8s_connected or not prom_connected:
            return jsonify({
                "success": False,
                "error": "Live execution requires reachable Kubernetes and Prometheus integrations.",
                "connectivity": {
                    "kubernetes": {"connected": k8s_connected, "message": k8s_msg},
                    "prometheus": {"connected": prom_connected, "message": prom_msg},
                },
            }), 409
    controller.set_live_execution(enable)
    return jsonify({
        "success": True,
        "enable_live_execution": controller.config.enable_live_execution,
        "dry_run": controller.config.dry_run,
        "mode": "LIVE EXECUTION" if enable else "DRY RUN",
    })


@app.route("/api/controls/simulate-metric", methods=["POST"])
def set_simulated_metric():
    """
    Sets simulated metric values for demonstration purposes.
    Always explicitly marked as SIMULATED.
    """
    data = request.get_json() or {}
    metric_name = data.get("metric_name")
    value = data.get("value")
    status_str = data.get("status", "SIMULATED")

    if not metric_name:
        return jsonify({"error": "metric_name is required"}), 400

    status = MetricStatus.SIMULATED
    if status_str == "MISSING":
        status = MetricStatus.MISSING
        value = None
    elif status_str == "STALE":
        status = MetricStatus.STALE

    if value is not None:
        try:
            value = float(value)
        except ValueError:
            return jsonify({"error": "value must be numeric"}), 400

    controller.simulated_provider.set_metric(metric_name, value, status=status)
    controller.config.simulation_mode = True

    logger.info("Simulated metric set: %s = %s (status: %s)", metric_name, value, status.value)
    return jsonify({
        "success": True,
        "metric_name": metric_name,
        "value": value,
        "status": status.value,
        "simulation_mode": True,
    })


@app.route("/api/controls/clear-simulation", methods=["POST"])
def clear_simulation():
    """Resets simulation mode to return to live Prometheus telemetry."""
    controller.config.simulation_mode = False
    controller.latest_telemetry = {}
    logger.info("Simulation mode cleared; returned to live Prometheus telemetry.")
    return jsonify({
        "success": True,
        "message": "Returned to live Prometheus telemetry mode.",
        "simulation_mode": False,
    })


@app.route("/api/controls/reset-cooldown", methods=["POST"])
def reset_cooldown():
    """Resets the cooldown timer to permit immediate scaling demonstration."""
    controller.decision_controller.reset_cooldown()
    return jsonify({
        "success": True,
        "message": "Cooldown timer reset successfully.",
    })


if __name__ == "__main__":
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", 5055))
    logger.info("Starting Auto-Scaling Dashboard on http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False, threaded=True)
