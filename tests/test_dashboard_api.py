"""
Integration tests for Dashboard REST API endpoints and error states.
"""

import pytest
import yaml
from pathlib import Path
from dashboard.app import app
from controller.guardrails import GuardrailResult
from controller.kubernetes_executor import ExecutionResult, WorkloadState
from controller.policy_engine import PolicyEngine
import dashboard.app as dashboard_module


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_index_route(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"Cluster overview" in res.data


@pytest.mark.parametrize("path,title", [
    ("/overview", b"Cluster overview"),
    ("/workloads", b"Workloads"),
    ("/telemetry", b"Telemetry"),
    ("/policies", b"Scaling policies"),
    ("/decisions", b"Decision engine"),
    ("/history", b"Execution history"),
    ("/system-health", b"System health"),
])
def test_application_pages_are_real_routes(client, path, title):
    res = client.get(path)
    assert res.status_code == 200
    assert title in res.data
    assert b'href="#' not in res.data


def test_unknown_route_is_not_found(client):
    res = client.get("/does-not-exist")
    assert res.status_code == 404
    assert b"Page not found" in res.data


def test_healthz_endpoint(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "autoscaling-dashboard"


def test_readyz_endpoint(client):
    res = client.get("/readyz")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ready"
    assert data["policies_count"] > 0


def test_api_status_endpoint(client):
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["controller_running"] is True
    assert "connectivity" in data
    assert "kubernetes" in data["connectivity"]
    assert "prometheus" in data["connectivity"]
    assert "target" in data


def test_api_metrics_endpoint(client):
    res = client.get("/api/metrics")
    assert res.status_code == 200
    data = res.get_json()
    assert "metrics" in data
    assert "source" in data


def test_api_decisions_endpoint(client):
    res = client.get("/api/decisions")
    assert res.status_code == 200
    data = res.get_json()
    assert "decision" in data
    assert "guardrail" in data


def test_api_policies_endpoint(client):
    res = client.get("/api/policies")
    assert res.status_code == 200
    data = res.get_json()
    assert "policies" in data
    assert len(data["policies"]) >= 6


def test_api_history_endpoint(client):
    res = client.get("/api/history?limit=10")
    assert res.status_code == 200
    data = res.get_json()
    assert "records" in data
    assert "total" in data


def test_api_evaluate_endpoint(client):
    res = client.post("/api/evaluate")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "cycle_result" in data


def test_api_controls_live_execution(client):
    # Enable live
    res = client.post("/api/controls/live-execution", json={"enable": True})
    assert res.status_code in (200, 409)
    if res.status_code == 409:
        assert res.get_json()["success"] is False
        assert "connectivity" in res.get_json()
    else:
        assert res.get_json()["enable_live_execution"] is True

    # Disable live
    res2 = client.post("/api/controls/live-execution", json={"enable": False})
    assert res2.status_code == 200
    assert res2.get_json()["enable_live_execution"] is False


def test_api_simulate_and_clear_metrics(client):
    # Set simulated metric
    res = client.post(
        "/api/controls/simulate-metric",
        json={"metric_name": "cpu_utilization_percent", "value": 88.5},
    )
    assert res.status_code == 200
    assert res.get_json()["value"] == 88.5

    # Check metrics reflected
    m_res = client.get("/api/metrics")
    assert m_res.get_json()["source"] == "SIMULATED"

    # Clear simulation
    c_res = client.post("/api/controls/clear-simulation")
    assert c_res.status_code == 200
    assert c_res.get_json()["simulation_mode"] is False


def test_api_reset_cooldown(client):
    res = client.post("/api/controls/reset-cooldown")
    assert res.status_code == 200
    assert res.get_json()["success"] is True


def test_api_update_threshold_validation(client):
    # Missing fields
    res = client.post("/api/policies/update-threshold", json={})
    assert res.status_code == 400

    # Non-numeric threshold
    res2 = client.post(
        "/api/policies/update-threshold",
        json={"id": "CPU_HIGH_LOAD", "threshold": "invalid_num"},
    )
    assert res2.status_code == 400

    # Non-existent policy
    res3 = client.post(
        "/api/policies/update-threshold",
        json={"id": "NON_EXISTENT_POLICY", "threshold": 50.0},
    )
    assert res3.status_code == 404


def test_policy_create_validates_against_existing_engine(client):
    response = client.post("/api/policies", json={
        "id": "INVALID_POLICY",
        "name": "Invalid",
        "metric": "unsupported_metric",
        "operator": ">",
        "threshold": 10,
        "priority": 10,
        "action": "SCALE_OUT",
        "replica_delta": 1,
    })
    assert response.status_code == 400
    assert "unsupported metric" in response.get_json()["error"]


def test_policy_create_update_persists_and_reloads(client, monkeypatch):
    original_path = dashboard_module.controller.config.policies_path
    policy_path = Path("tests") / ".policy-persistence-regression.yaml"
    policy_path.write_text(Path(original_path).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(dashboard_module.controller.config, "policies_path", str(policy_path))
    dashboard_module.controller.reload_policies()
    try:
        payload = {
            "id": "PERSISTENCE_REGRESSION",
            "name": "Persistence regression",
            "metric": "cpu_utilization_percent",
            "operator": ">",
            "threshold": 66,
            "priority": 11,
            "action": "SCALE_OUT",
            "replica_delta": 1,
            "duration_seconds": 0,
            "cooldown_seconds": 15,
            "enabled": True,
        }
        created = client.post("/api/policies", json=payload)
        assert created.status_code == 201
        saved = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        assert next(p for p in saved["policies"] if p["id"] == payload["id"])["threshold"] == 66

        updated = dict(payload, threshold=72)
        changed = client.put(f"/api/policies/{payload['id']}", json=updated)
        assert changed.status_code == 200
        dashboard_module.controller.reload_policies()
        active = next(r for r in dashboard_module.controller.policy_engine.rules if r.id == payload["id"])
        assert active.threshold == 72
        restarted_engine = PolicyEngine(str(policy_path))
        persisted = next(r for r in restarted_engine.rules if r.id == payload["id"])
        assert persisted.threshold == 72
    finally:
        dashboard_module.controller.config.policies_path = original_path
        dashboard_module.controller.reload_policies()
        policy_path.unlink(missing_ok=True)


def test_policy_enabled_rejects_non_boolean(client):
    response = client.post("/api/policies", json={
        "id": "BAD_ENABLED",
        "name": "Bad enabled",
        "metric": "cpu_utilization_percent",
        "operator": ">",
        "threshold": 50,
        "priority": 10,
        "action": "SCALE_OUT",
        "replica_delta": 1,
        "enabled": "false",
    })
    assert response.status_code == 400
    assert "enabled" in response.get_json()["error"]


def test_policy_create_duplicate_id_returns_409(client):
    """Attempting to create a policy with an existing ID must return 409 Conflict with JSON error."""
    payload = {
        "id": "CPU_HIGH_LOAD",  # Already exists in default config
        "name": "Duplicate High Load",
        "metric": "cpu_utilization_percent",
        "operator": ">",
        "threshold": 80.0,
        "priority": 50,
        "action": "SCALE_OUT",
        "replica_delta": 1,
        "enabled": True,
    }
    response = client.post("/api/policies", json=payload)
    assert response.status_code == 409
    assert response.headers.get("Content-Type", "").startswith("application/json")
    data = response.get_json()
    assert "already exists" in data["error"]


def test_policy_create_invalid_fields_validation(client):
    """Verifies strict field validation on policy creation."""
    # 1. Invalid ID with spaces
    r1 = client.post("/api/policies", json={
        "id": "INVALID ID WITH SPACES",
        "name": "Invalid ID",
        "metric": "cpu_utilization_percent",
        "operator": ">",
        "threshold": 50,
        "priority": 10,
        "action": "SCALE_OUT",
        "replica_delta": 1,
    })
    assert r1.status_code == 400
    assert "id" in r1.get_json()["error"].lower()

    # 2. SCALE_OUT with negative delta
    r2 = client.post("/api/policies", json={
        "id": "SCALE_OUT_NEGATIVE",
        "name": "Bad delta",
        "metric": "cpu_utilization_percent",
        "operator": ">",
        "threshold": 50,
        "priority": 10,
        "action": "SCALE_OUT",
        "replica_delta": -1,
    })
    assert r2.status_code == 400
    assert "positive" in r2.get_json()["error"].lower()

    # 3. Percentage threshold > 100
    r3 = client.post("/api/policies", json={
        "id": "PERCENT_TOO_HIGH",
        "name": "High threshold",
        "metric": "cpu_utilization_percent",
        "operator": ">",
        "threshold": 150.0,
        "priority": 10,
        "action": "SCALE_OUT",
        "replica_delta": 1,
    })
    assert r3.status_code == 400
    assert "between 0.0 and 100.0" in r3.get_json()["error"]


def test_api_error_handlers_always_return_json(client):
    """Ensures /api/ endpoints always return JSON, never HTML, even on 404 or 405."""
    # 404 on API route
    res404 = client.get("/api/non-existent-endpoint")
    assert res404.status_code == 404
    assert res404.headers.get("Content-Type", "").startswith("application/json")
    assert "error" in res404.get_json()

    # 405 on API route (DELETE on /api/policies)
    res405 = client.delete("/api/policies")
    assert res405.status_code == 405
    assert res405.headers.get("Content-Type", "").startswith("application/json")
    assert "error" in res405.get_json()

    # Regular page routes still return HTML
    page404 = client.get("/non-existent-page")
    assert page404.status_code == 404
    assert "text/html" in page404.headers.get("Content-Type", "")


def test_manual_scale_rejects_bad_payload(client):
    response = client.post("/api/workloads/scale", json={"target_replicas": "3"})
    assert response.status_code == 400
    assert "integer" in response.get_json()["error"]


def test_manual_scale_returns_verified_workload_state(client, monkeypatch):
    states = [
        WorkloadState("autoscaling-demo", "sample-web-app", 2, 2, 2, 2, 0, True, "Connected", []),
        WorkloadState("autoscaling-demo", "sample-web-app", 5, 5, 5, 5, 0, True, "Connected", []),
    ]
    monkeypatch.setattr(dashboard_module.controller.executor, "is_connected", lambda: (True, "Kubernetes API reachable."))
    monkeypatch.setattr(dashboard_module.controller.executor, "get_workload_state", lambda: states.pop(0))
    monkeypatch.setattr(
        dashboard_module.controller.strategy_coordinator,
        "coordinate_and_execute",
        lambda **kwargs: (
            GuardrailResult(True, "EXECUTE", 5, 5, 3, False, None, False, "Authorized"),
            ExecutionResult(True, False, 2, 5, 5, "SCALE_OUT", "Verified by Kubernetes API."),
        ),
    )

    response = client.post("/api/workloads/scale", json={"target_replicas": 5})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["workload"]["desired_replicas"] == 5
    assert payload["execution"]["confirmed_replicas"] == 5


def test_manual_scale_exposes_kubernetes_unavailable(client, monkeypatch):
    monkeypatch.setattr(
        dashboard_module.controller.executor,
        "is_connected",
        lambda: (False, "forbidden: deployments/scale is not permitted"),
    )
    response = client.post("/api/workloads/scale", json={"target_replicas": 5})
    assert response.status_code == 409
    assert "forbidden" in response.get_json()["error"]


def test_api_capacity_endpoint(client):
    res = client.get("/api/capacity?delta=2")
    assert res.status_code == 200
    data = res.get_json()
    assert "outcome" in data
    assert "is_sufficient" in data
    assert "disclaimer" in data
    assert "evaluated_nodes" in data
