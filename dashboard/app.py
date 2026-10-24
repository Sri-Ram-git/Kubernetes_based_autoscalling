"""
Web Dashboard Server for Kubernetes Auto-Scaling Framework.
Project ID: 357 | Alliance University, Bengaluru

REST API-backed Dashboard providing live telemetry monitoring, PRAH decision inspection,
policy management, audit history, and operational safety controls.
"""

import copy
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import tempfile
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
from controller.policy_engine import (
    PolicyEngine,
    PolicyValidationError,
    SUPPORTED_METRICS,
    SUPPORTED_OPERATORS,
    SUPPORTED_ACTIONS,
)
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


def _load_policy_document() -> Dict[str, Any]:
    """Read the active YAML document without exposing credentials or secrets."""
    with open(controller.config.policies_path, "r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    if not isinstance(document, dict) or not isinstance(document.get("policies"), list):
        raise PolicyValidationError("Policy document must contain a 'policies' list")
    return document


def _persist_policy_document(document: Dict[str, Any]) -> None:
    """Validate first, then atomically persist and reload the active policy file."""
    candidate = PolicyEngine()
    candidate.validate_and_parse(copy.deepcopy(document))
    policy_path = Path(controller.config.policies_path)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=policy_path.parent,
                                     prefix=f".{policy_path.name}.", suffix=".tmp", delete=False) as handle:
        yaml.safe_dump(document, handle, sort_keys=False)
        temp_path = Path(handle.name)
    try:
        os.replace(temp_path, policy_path)
        controller.reload_policies()
        controller.run_single_cycle()
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _policy_input(data: Dict[str, Any], policy_id: str | None = None) -> Dict[str, Any]:
    """Normalize and strictly validate the policy payload while keeping the existing YAML schema."""
    if not isinstance(data, dict):
        raise PolicyValidationError("Policy payload must be a JSON object")
    if "enabled" in data and not isinstance(data["enabled"], bool):
        raise PolicyValidationError("Policy 'enabled' must be a boolean")
    required = ("name", "metric", "threshold", "action", "replica_delta", "priority")
    missing = [key for key in required if key not in data]
    op = data.get("operator") or data.get("operator_str")
    if not op:
        missing.append("operator")
    if missing:
        raise PolicyValidationError(f"Missing required policy fields: {', '.join(missing)}")

    p_id = str(policy_id or data.get("id") or "").strip()
    if not p_id:
        raise PolicyValidationError("Policy 'id' is required")
    if not re.match(r"^[A-Za-z0-9_-]+$", p_id):
        raise PolicyValidationError("Policy 'id' must contain only alphanumeric characters, underscores, and hyphens")

    name = str(data["name"]).strip()
    if not name:
        raise PolicyValidationError("Policy 'name' is required")

    metric = str(data["metric"]).strip()
    if metric not in SUPPORTED_METRICS:
        raise PolicyValidationError(f"Policy '{p_id}' references unsupported metric '{metric}'. Supported metrics: {sorted(list(SUPPORTED_METRICS))}")

    op_clean = str(op).strip()
    if op_clean not in SUPPORTED_OPERATORS:
        raise PolicyValidationError(f"Invalid operator '{op_clean}'. Supported operators: {sorted(list(SUPPORTED_OPERATORS.keys()))}")

    action = str(data["action"]).strip()
    if action not in SUPPORTED_ACTIONS:
        raise PolicyValidationError(f"Invalid action '{action}'. Supported actions: {sorted(list(SUPPORTED_ACTIONS))}")

    # Validate numeric threshold and ranges
    try:
        threshold_val = float(data["threshold"])
        if not math.isfinite(threshold_val) or threshold_val < 0.0:
            raise ValueError()
    except (ValueError, TypeError):
        raise PolicyValidationError("Threshold must be a non-negative finite numeric value")

    if "percent" in metric and (threshold_val < 0.0 or threshold_val > 100.0):
        raise PolicyValidationError("Percentage metric threshold must be between 0.0 and 100.0")

    try:
        priority_val = int(data["priority"])
        if priority_val <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise PolicyValidationError("Priority must be a positive integer (> 0)")

    try:
        delta_val = int(data["replica_delta"])
    except (ValueError, TypeError):
        raise PolicyValidationError("replica_delta must be an integer")

    if action == "SCALE_OUT" and delta_val <= 0:
        raise PolicyValidationError(f"Policy '{p_id}': SCALE_OUT must have positive replica_delta (got {delta_val})")
    if action == "SCALE_IN" and delta_val >= 0:
        raise PolicyValidationError(f"Policy '{p_id}': SCALE_IN must have negative replica_delta (got {delta_val})")
    if action == "HOLD" and delta_val != 0:
        raise PolicyValidationError(f"Policy '{p_id}': HOLD must have replica_delta == 0 (got {delta_val})")

    try:
        duration_val = float(data.get("duration_seconds", 0))
        if duration_val < 0 or not math.isfinite(duration_val):
            raise ValueError()
    except (ValueError, TypeError):
        raise PolicyValidationError("duration_seconds must be a non-negative number")

    try:
        cooldown_val = float(data.get("cooldown_seconds", 60))
        if cooldown_val < 0 or not math.isfinite(cooldown_val):
            raise ValueError()
    except (ValueError, TypeError):
        raise PolicyValidationError("cooldown_seconds must be a non-negative number")

    return {
        "id": p_id,
        "name": name,
        "description": str(data.get("description", "")).strip(),
        "enabled": data.get("enabled", True),
        "priority": priority_val,
        "metric": metric,
        "operator": op_clean,
        "threshold": threshold_val,
        "duration_seconds": duration_val,
        "action": action,
        "replica_delta": delta_val,
        "cooldown_seconds": cooldown_val,
    }


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


@app.route("/api/workloads/scale", methods=["POST"])
@app.route("/api/workload/scale", methods=["POST"])
@app.route("/api/scale", methods=["POST"])
def request_workload_scale():
    """Submit an explicitly confirmed workload scale request through guardrails."""
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object"}), 400
        target = data.get("target_replicas")
        if target is None:
            target = data.get("replicas")
        if target is None:
            target = data.get("target")
        if isinstance(target, bool) or not isinstance(target, int):
            return jsonify({"error": "target_replicas must be an integer"}), 400
        if target < 1:
            return jsonify({"error": "target_replicas must be >= 1"}), 400

        connected, message = controller.executor.is_connected()
        if not connected:
            logger.warning("Manual scaling rejected: Kubernetes unavailable: %s", message)
            return jsonify({"error": f"Kubernetes is unavailable: {message}"}), 409

        workload = controller.executor.get_workload_state()
        if workload.desired_replicas is None:
            logger.warning("Manual scaling rejected: workload verification failed: %s", workload.status_message)
            return jsonify({"error": f"Target workload could not be verified: {workload.status_message}"}), 409

        delta = target - workload.desired_replicas
        action = "SCALE_OUT" if delta > 0 else "SCALE_IN" if delta < 0 else "HOLD"
        guardrail, execution = controller.strategy_coordinator.coordinate_and_execute(
            proposed_action=action,
            current_replicas=workload.desired_replicas,
            target_replicas=target,
            replica_delta=delta,
        )

        # Query Kubernetes again to verify actual state from cluster API
        controller.latest_workload_state = controller.executor.get_workload_state()
        controller.latest_guardrail = guardrail
        controller.latest_execution = execution
        success = execution.success and guardrail.action in ("EXECUTE", "HOLD")
        applied = bool(success and not execution.dry_run and execution.confirmed_replicas == target)
        verified = bool(applied and controller.latest_workload_state.desired_replicas == target)

        controller.decision_logger.log_cycle(
            decision={
                "action": action,
                "current_replicas": workload.desired_replicas,
                "proposed_replica_delta": delta,
                "target_replicas": target,
                "selected_policy_id": "MANUAL_OPERATOR_REQUEST",
                "selected_policy_name": "Manual operator request",
                "priority": 0,
                "explanation": "Manual operator request submitted through guarded workload control.",
                "cooldown_active": False,
                "cooldown_remaining_seconds": 0.0,
                "competing_proposals": [],
                "telemetry_summary": {},
            },
            guardrail_result=guardrail.to_dict(),
            execution_result=execution.to_dict(),
            metrics={},
            error=execution.error or guardrail.rejection_reason,
            target_namespace=controller.config.target_namespace,
            target_deployment=controller.config.target_deployment,
        )
        logger.info("Manual scaling result: target=%s guardrail=%s success=%s applied=%s message=%s",
                    target, guardrail.action, success, applied, execution.message)
        return jsonify({
            "success": success,
            "applied": applied,
            "verified": verified,
            "guardrail": guardrail.to_dict(),
            "execution": execution.to_dict(),
            "workload": controller.latest_workload_state.to_dict(),
        }), 200 if success else 409
    except Exception as exc:
        logger.exception("Manual scaling request failed")
        return jsonify({"error": f"Manual scaling request failed: {exc}"}), 500


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
    now = time.time()
    prom_connected, prom_msg = controller.prometheus_provider.check_connection()
    prom_targets = controller.prometheus_provider.get_targets_status() if prom_connected else {
        "reachable": False, "total_targets": 0, "healthy_targets": 0, "targets": []
    }

    # Fetch live telemetry when connected to Prometheus and not in simulation mode
    if not controller.config.simulation_mode:
        if prom_connected:
            metrics = controller.fetch_current_telemetry()
            controller.latest_telemetry = metrics
        else:
            metrics = controller.latest_telemetry or controller.fetch_current_telemetry()
    else:
        metrics = controller.latest_telemetry
        if not metrics:
            metrics = controller.fetch_current_telemetry()
            controller.latest_telemetry = metrics

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


@app.route("/api/policies", methods=["POST"])
def create_policy():
    """Create and validate a policy using the existing YAML persistence mechanism."""
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a valid JSON object"}), 400
        policy = _policy_input(data)
        document = _load_policy_document()
        if any(item.get("id") == policy["id"] for item in document.get("policies", [])):
            return jsonify({"error": f"Policy '{policy['id']}' already exists"}), 409
        document["policies"].append(policy)
        _persist_policy_document(document)
        saved = next((rule.to_dict() for rule in controller.policy_engine.rules if rule.id == policy["id"]), policy)
        return jsonify({"success": True, "policy": saved}), 201
    except PolicyValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except (OSError, yaml.YAMLError) as exc:
        logger.exception("Policy create failed")
        return jsonify({"error": f"Failed to persist policy: {exc}"}), 500
    except Exception as exc:
        logger.exception("Unexpected error in create_policy")
        return jsonify({"error": f"Internal server error: {exc}"}), 500


@app.route("/api/policies/<policy_id>", methods=["PUT"])
def update_policy(policy_id: str):
    """Validate and replace one policy while preserving all other YAML configuration."""
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a valid JSON object"}), 400
        document = _load_policy_document()
        index = next((i for i, item in enumerate(document.get("policies", []))
                      if item.get("id") == policy_id), None)
        if index is None:
            return jsonify({"error": f"Policy '{policy_id}' not found"}), 404
        updated_policy = _policy_input(data, policy_id=policy_id)
        document["policies"][index] = updated_policy
        _persist_policy_document(document)
        saved = next((rule.to_dict() for rule in controller.policy_engine.rules if rule.id == policy_id), updated_policy)
        return jsonify({"success": True, "policy": saved}), 200
    except PolicyValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except (OSError, yaml.YAMLError) as exc:
        logger.exception("Policy update failed")
        return jsonify({"error": f"Failed to persist policy: {exc}"}), 500
    except Exception as exc:
        logger.exception("Unexpected error in update_policy")
        return jsonify({"error": f"Internal server error: {exc}"}), 500


@app.route("/api/policies/<policy_id>/enabled", methods=["PATCH"])
def set_policy_enabled(policy_id: str):
    """Enable or disable a policy and confirm the reloaded configuration."""
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a valid JSON object"}), 400
        if not isinstance(data.get("enabled"), bool):
            return jsonify({"error": "'enabled' must be a boolean"}), 400
        document = _load_policy_document()
        policy = next((item for item in document.get("policies", []) if item.get("id") == policy_id), None)
        if policy is None:
            return jsonify({"error": f"Policy '{policy_id}' not found"}), 404
        policy["enabled"] = data["enabled"]
        _persist_policy_document(document)
        saved = next((rule.to_dict() for rule in controller.policy_engine.rules if rule.id == policy_id), policy)
        return jsonify({"success": True, "policy": saved}), 200
    except PolicyValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except (OSError, yaml.YAMLError) as exc:
        logger.exception("Policy enablement update failed")
        return jsonify({"error": f"Failed to persist policy: {exc}"}), 500
    except Exception as exc:
        logger.exception("Unexpected error in set_policy_enabled")
        return jsonify({"error": f"Internal server error: {exc}"}), 500


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

    try:
        yaml_data = _load_policy_document()
        target_policy = next((p for p in yaml_data["policies"] if p.get("id") == policy_id), None)
        if target_policy is None:
            return jsonify({"error": f"Policy '{policy_id}' not found"}), 404
        metric = str(target_policy.get("metric", ""))
        if metric.endswith("_percent") and (new_threshold < 0.0 or new_threshold > 100.0):
            return jsonify({"error": f"Percentage threshold for '{metric}' must be between 0 and 100"}), 400
        if new_threshold < 0.0:
            return jsonify({"error": "Threshold cannot be negative"}), 400
        for p in yaml_data["policies"]:
            if p.get("id") == policy_id:
                p["threshold"] = new_threshold
                break

        _persist_policy_document(yaml_data)

        logger.info("Updated threshold for policy %s to %f", policy_id, new_threshold)
        return jsonify({
            "success": True,
            "message": f"Updated {policy_id} threshold to {new_threshold}",
        })
    except (OSError, yaml.YAMLError, PolicyValidationError) as e:
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


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(500)
def handle_api_errors(e):
    """Ensure all /api/ requests receive structured JSON errors instead of HTML pages."""
    if request.path.startswith("/api/"):
        status_code = getattr(e, "code", 500)
        description = getattr(e, "description", str(e))
        return jsonify({"error": description, "status": status_code}), status_code
    if getattr(e, "code", 500) == 404:
        return render_template("404.html", page_title="Not Found"), 404
    return e


if __name__ == "__main__":
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", 5055))
    logger.info("Starting Auto-Scaling Dashboard on http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False, threaded=True)
