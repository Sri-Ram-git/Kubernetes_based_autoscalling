"""
Integration tests for Dashboard REST API endpoints and error states.
"""

import pytest
from dashboard.app import app


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
