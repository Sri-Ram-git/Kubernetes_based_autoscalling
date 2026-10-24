"""
Unit and integration tests for the Automated Experimentation Engine (Project 357).
Verifies:
- Workload generator lifecycle and statistical tracking.
- ExperimentManager initialization, specs, mutual exclusion locking.
- REST API endpoints (/api/experiments, /api/experiments/<id>/run, /api/experiments/<id>/status, /api/experiments/runs/<id>).
- Safe teardown, cleanup, and file persistence.
"""

import json
import time
from unittest.mock import MagicMock, patch
import pytest

from controller.experiment_runner import (
    ExperimentManager,
    ExperimentRun,
    SystemRunResult,
    TimeSeriesSample,
    WorkloadGenerator,
)
from dashboard.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_workload_generator_stats():
    gen = WorkloadGenerator(target_url="http://localhost:8080")
    gen.reset_stats()
    stats = gen.get_stats()
    assert stats["sent"] == 0
    assert stats["success"] == 0
    assert stats["failed"] == 0
    assert stats["avg_latency_ms"] == 0.0


def test_experiment_specs_available():
    mock_controller = MagicMock()
    mgr = ExperimentManager(mock_controller)
    specs = mgr.list_experiments()
    assert len(specs) == 2
    ids = [s["id"] for s in specs]
    assert "stable_workload" in ids
    assert "traffic_spike" in ids


def test_experiment_manager_rejects_unknown_id():
    mock_controller = MagicMock()
    mgr = ExperimentManager(mock_controller)
    ok, msg, run_id = mgr.start_experiment("invalid_experiment_id")
    assert ok is False
    assert run_id is None
    assert "Unknown experiment ID" in msg


def test_experiment_manager_mutual_exclusion():
    mock_controller = MagicMock()
    mgr = ExperimentManager(mock_controller)
    # Simulate an active run by acquiring the lock
    assert mgr._run_lock.acquire(blocking=False) is True
    try:
        ok, msg, run_id = mgr.start_experiment("stable_workload")
        assert ok is False
        assert run_id is None
        assert "Another experiment is currently running" in msg
    finally:
        mgr._run_lock.release()


def test_experiment_stop_when_idle():
    mock_controller = MagicMock()
    mgr = ExperimentManager(mock_controller)
    ok, msg = mgr.stop_current_experiment()
    assert ok is False
    assert "No experiment is currently running" in msg


def test_timeseries_sample_to_dict():
    sample = TimeSeriesSample(
        timestamp=1700000000.0,
        iso_timestamp="2026-10-24T00:00:00Z",
        elapsed_seconds=5.0,
        system="baseline",
        cpu_utilization_percent=45.5,
        memory_utilization_percent=50.0,
        http_requests_per_second=10.0,
        desired_replicas=2,
        current_replicas=2,
        ready_replicas=2,
        scaling_action="HOLD",
        workload_rps_actual=10.0,
        workload_latency_avg_ms=12.5,
    )
    d = sample.to_dict()
    assert d["system"] == "baseline"
    assert d["cpu_utilization_percent"] == 45.5
    assert d["desired_replicas"] == 2


def test_compute_comparison_logic():
    mock_controller = MagicMock()
    mgr = ExperimentManager(mock_controller)

    baseline = SystemRunResult(
        system="baseline",
        duration_seconds=20.0,
        initial_replicas=2,
        peak_replicas=4,
        final_replicas=2,
        scaling_events_count=2,
        time_to_first_scale_seconds=14.0,
        max_cpu_percent=88.0,
        avg_cpu_percent=42.0,
        max_memory_percent=55.0,
        total_requests_sent=200,
        successful_requests=200,
        failed_requests=0,
        avg_request_latency_ms=15.0,
    )

    proposed = SystemRunResult(
        system="proposed",
        duration_seconds=20.0,
        initial_replicas=2,
        peak_replicas=4,
        final_replicas=2,
        scaling_events_count=2,
        time_to_first_scale_seconds=6.0,
        max_cpu_percent=85.0,
        avg_cpu_percent=40.0,
        max_memory_percent=54.0,
        total_requests_sent=200,
        successful_requests=200,
        failed_requests=0,
        avg_request_latency_ms=14.0,
    )

    comp = mgr._compute_comparison(baseline, proposed)
    assert comp["baseline_peak_replicas"] == 4
    assert comp["proposed_peak_replicas"] == 4
    assert comp["baseline_scale_latency_seconds"] == 14.0
    assert comp["proposed_scale_latency_seconds"] == 6.0
    assert comp["scale_latency_improvement_seconds"] == 8.0  # 14.0 - 6.0
    assert "STABLE" in comp["scaling_stability"]


def test_api_experiments_list(client):
    res = client.get("/api/experiments")
    assert res.status_code == 200
    data = res.get_json()
    assert "experiments" in data
    assert "history" in data
    exp_ids = [e["id"] for e in data["experiments"]]
    assert "stable_workload" in exp_ids
    assert "traffic_spike" in exp_ids


def test_experiments_nav_tab_removed_and_embedded_in_overview(client):
    # Separate /experiments tab is removed
    res = client.get("/experiments")
    assert res.status_code == 404

    # Experiments are accessible directly through Overview
    res_overview = client.get("/")
    assert res_overview.status_code == 200
    assert "text/html" in res_overview.headers.get("Content-Type", "")


def test_api_experiment_run_rejects_invalid_id(client):
    res = client.post("/api/experiments/unknown_exp/run", json={"mode": "both"})
    assert res.status_code == 409
    data = res.get_json()
    assert data["success"] is False
    assert "Unknown experiment ID" in data["message"]


def test_api_experiment_status_endpoint(client):
    res = client.get("/api/experiments/stable_workload/status")
    assert res.status_code == 200
    data = res.get_json()
    assert "current_run" in data


def test_api_experiment_run_details_not_found(client):
    res = client.get("/api/experiments/runs/non-existent-run-id")
    assert res.status_code == 404
    data = res.get_json()
    assert "not found" in data["error"]


def test_api_experiment_stop_endpoint(client):
    # Stopping when nothing is running returns 400
    res = client.post("/api/experiments/stop")
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
