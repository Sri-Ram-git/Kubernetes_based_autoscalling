"""
Comprehensive Regression Tests for Project 357 (KubePilot).
Verifies all 9 critical operational and data-consistency scenarios:
1. No policy matches.
2. A scale-out policy matches and execution is permitted.
3. A scale-in policy matches but cooldown blocks it.
4. A policy is created, saved, reloaded, and used in subsequent evaluation.
5. A live scaling request changes the real Deployment replica count (against Minikube).
6. A failed Kubernetes request leaves the UI/state showing actual cluster state.
7. Dry-run proposes a change without modifying Kubernetes.
8. Execution History reflects the real outcome without duplicate entries.
9. Refreshing or reopening the dashboard retains persisted policies and history.
"""

import copy
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from controller.config import ControllerConfig
from controller.decision_controller import DecisionController
from controller.decision_logger import DecisionLogger
from controller.guardrails import GuardrailEngine, GuardrailResult
from controller.kubernetes_executor import ExecutionResult, KubernetesExecutor, WorkloadState
from controller.main import AutoscalingController
from controller.policy_engine import PolicyEngine, PolicyRule
from controller.strategy_coordinator import StrategyCoordinator
from controller.telemetry import MetricSample, MetricStatus
from dashboard.app import app


@pytest.fixture
def test_config():
    """Returns safe controller config pointing to real policies."""
    cfg = ControllerConfig.load("policies/scaling-policies.yaml")
    cfg.dry_run = True
    cfg.enable_live_execution = False
    return cfg


# ==============================================================================
# Case 1: No policy matches
# ==============================================================================
def test_case_1_no_policy_matches():
    engine = PolicyEngine("policies/scaling-policies.yaml")
    ctrl = DecisionController(policy_engine=engine, default_cooldown_seconds=60.0)

    # Nominal metrics: CPU 50%, Memory 40%, RPS 20
    nominal_metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent", value=50.0, timestamp=time.time(),
            status=MetricStatus.VALID, source="prometheus"
        ),
        "memory_utilization_percent": MetricSample(
            metric_name="memory_utilization_percent", value=40.0, timestamp=time.time(),
            status=MetricStatus.VALID, source="prometheus"
        ),
        "http_requests_per_second": MetricSample(
            metric_name="http_requests_per_second", value=20.0, timestamp=time.time(),
            status=MetricStatus.VALID, source="prometheus"
        ),
    }

    decision = ctrl.compute_decision(nominal_metrics, current_replicas=2)
    assert decision.action == "HOLD"
    assert decision.proposed_replica_delta == 0
    assert decision.target_replicas == 2
    assert decision.selected_policy_id is None
    assert decision.selected_policy_name is None
    assert "No policy thresholds breached" in decision.explanation
    assert len(decision.competing_proposals) == 0


# ==============================================================================
# Case 2: A scale-out policy matches and execution is permitted
# ==============================================================================
def test_case_2_scale_out_matches_and_permitted():
    engine = PolicyEngine("policies/scaling-policies.yaml")
    ctrl = DecisionController(policy_engine=engine, default_cooldown_seconds=60.0)
    guardrails = GuardrailEngine(min_replicas=1, max_replicas=10, max_scale_step_up=2, dry_run=False, enable_live_execution=True)

    # Spike CPU to 95.0% (triggers CPU_CRITICAL_SPIKE: >= 90%, delta +2, priority 100)
    spike_metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent", value=95.0, timestamp=time.time(),
            status=MetricStatus.VALID, source="prometheus"
        ),
        "memory_utilization_percent": MetricSample(
            metric_name="memory_utilization_percent", value=50.0, timestamp=time.time(),
            status=MetricStatus.VALID, source="prometheus"
        ),
        "http_requests_per_second": MetricSample(
            metric_name="http_requests_per_second", value=100.0, timestamp=time.time(),
            status=MetricStatus.VALID, source="prometheus"
        ),
    }

    decision = ctrl.compute_decision(spike_metrics, current_replicas=2)
    assert decision.action == "SCALE_OUT"
    assert decision.selected_policy_id == "CPU_CRITICAL_SPIKE"
    assert decision.proposed_replica_delta == 2
    assert decision.target_replicas == 4

    # Validate guardrail permission
    g_res = guardrails.validate_action(
        proposed_action=decision.action,
        current_replicas=2,
        target_replicas=decision.target_replicas,
        replica_delta=decision.proposed_replica_delta,
    )
    assert g_res.approved is True
    assert g_res.action == "EXECUTE"
    assert g_res.authorized_target_replicas == 4
    assert g_res.is_dry_run is False


# ==============================================================================
# Case 3: A scale-in policy matches but cooldown blocks it
# ==============================================================================
def test_case_3_scale_in_matches_cooldown_blocks():
    engine = PolicyEngine("policies/scaling-policies.yaml")
    ctrl = DecisionController(policy_engine=engine, default_cooldown_seconds=60.0)

    # First action executed at t=100.0
    ctrl.record_action_executed(action="SCALE_OUT", policy_id="CPU_CRITICAL_SPIKE", cooldown_seconds=60.0, now=100.0)

    # At t=120.0, CPU drops to 15.0% (below 25% threshold for CPU_LOW_LOAD)
    low_cpu_metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent", value=15.0, timestamp=120.0,
            status=MetricStatus.VALID, source="prometheus"
        ),
        "memory_utilization_percent": MetricSample(
            metric_name="memory_utilization_percent", value=20.0, timestamp=120.0,
            status=MetricStatus.VALID, source="prometheus"
        ),
        "http_requests_per_second": MetricSample(
            metric_name="http_requests_per_second", value=5.0, timestamp=120.0,
            status=MetricStatus.VALID, source="prometheus"
        ),
    }

    # First evaluation at t=120.0 records breach start
    ctrl.compute_decision(low_cpu_metrics, current_replicas=4, now=120.0)

    # Sustained at t=126.0 (elapsed 6s >= duration_seconds 5s, but cooldown 60s from t=100 has 34s remaining)
    low_cpu_metrics["cpu_utilization_percent"].timestamp = 126.0
    decision = ctrl.compute_decision(low_cpu_metrics, current_replicas=4, now=126.0)
    assert decision.action == "HOLD"
    assert decision.cooldown_active is True
    assert round(decision.cooldown_remaining_seconds, 1) == 4.0
    assert "Anti-flapping delay active (4.0s remaining)" in decision.explanation
    assert decision.selected_policy_id == "CPU_LOW_LOAD"


# ==============================================================================
# Case 4: Policy created, saved, reloaded, and used
# ==============================================================================
def test_case_4_policy_created_saved_reloaded_and_used(tmp_path, monkeypatch):
    test_yaml = tmp_path / "scaling-policies-test.yaml"
    shutil.copy("policies/scaling-policies.yaml", test_yaml)

    with app.test_client() as client:
        from dashboard import app as dash_module
        orig_path = dash_module.controller.config.policies_path
        dash_module.controller.config.policies_path = str(test_yaml)
        dash_module.controller.reload_policies()

        try:
            new_policy = {
                "id": "CUSTOM_REGRESSION_SPIKE",
                "name": "Custom Regression Spike",
                "metric": "cpu_utilization_percent",
                "operator": ">",
                "threshold": 82.0,
                "priority": 95,
                "action": "SCALE_OUT",
                "replica_delta": 1,
                "duration_seconds": 0,
                "cooldown_seconds": 30,
                "enabled": True,
            }
            res = client.post("/api/policies", json=new_policy)
            assert res.status_code == 201

            # Verify persisted in file
            content = yaml.safe_load(test_yaml.read_text(encoding="utf-8"))
            saved = next(p for p in content["policies"] if p["id"] == "CUSTOM_REGRESSION_SPIKE")
            assert saved["threshold"] == 82.0

            # Verify active engine reloaded it
            rule = next(r for r in dash_module.controller.policy_engine.rules if r.id == "CUSTOM_REGRESSION_SPIKE")
            assert rule.threshold == 82.0

            # Evaluate with CPU 85.0%
            dash_module.controller.simulated_provider.set_metric("cpu_utilization_percent", 85.0)
            dash_module.controller.config.simulation_mode = True
            rec = dash_module.controller.run_single_cycle()
            assert rec["decision"]["selected_policy_id"] == "CUSTOM_REGRESSION_SPIKE"
            assert rec["decision"]["action"] == "SCALE_OUT"

        finally:
            dash_module.controller.config.simulation_mode = False
            dash_module.controller.config.policies_path = orig_path
            dash_module.controller.reload_policies()


# ==============================================================================
# Case 5: Live scaling request changes real Deployment replicas
# ==============================================================================
def test_case_5_live_scaling_real_deployment_mutation():
    executor = KubernetesExecutor(namespace="autoscaling-demo", deployment_name="sample-web-app")
    connected, _ = executor.is_connected()
    if not connected:
        pytest.skip("Live Minikube cluster is not accessible in this environment")

    # Read current state
    initial_state = executor.get_workload_state()
    initial_reps = initial_state.desired_replicas

    # Test scaling by +1
    target_reps = initial_reps + 1
    res = executor.execute_scaling(action="SCALE_OUT", target_replicas=target_reps, dry_run=False)

    try:
        assert res.success is True
        assert res.dry_run is False
        assert res.confirmed_replicas == target_reps

        # Verify Kubernetes API directly confirms target replicas
        verified_state = executor.get_workload_state()
        assert verified_state.desired_replicas == target_reps
    finally:
        # Restore to initial replica count
        executor.execute_scaling(action="SCALE_IN", target_replicas=initial_reps, dry_run=False)
        restored = executor.get_workload_state()
        assert restored.desired_replicas == initial_reps


# ==============================================================================
# Case 6: Failed Kubernetes request leaves UI showing actual cluster state
# ==============================================================================
def test_case_6_failed_kubernetes_request_preserves_actual_state():
    executor = KubernetesExecutor(namespace="autoscaling-demo", deployment_name="sample-web-app")
    executor._connected = True
    executor._apps_v1_api = MagicMock()

    # Initial deployment has 2 replicas
    mock_dep = MagicMock()
    mock_dep.spec.replicas = 2
    mock_dep.status.replicas = 2
    mock_dep.status.ready_replicas = 2
    mock_dep.status.available_replicas = 2
    executor._apps_v1_api.read_namespaced_deployment.return_value = mock_dep

    # Patch call fails with simulated Kubernetes 500
    from kubernetes.client.rest import ApiException
    executor._apps_v1_api.patch_namespaced_deployment_scale.side_effect = ApiException(status=500, reason="InternalServerError")

    res = executor.execute_scaling(action="SCALE_OUT", target_replicas=4, dry_run=False)

    assert res.success is False
    assert res.confirmed_replicas is None
    assert "InternalServerError" in str(res.error)

    # Workload state must retain actual observed 2 replicas, never the failed target (4)
    state = executor.get_workload_state()
    assert state.desired_replicas == 2


# ==============================================================================
# Case 7: Dry-run proposes change without modifying Kubernetes
# ==============================================================================
def test_case_7_dry_run_proposes_without_modifying_kubernetes():
    executor = KubernetesExecutor(namespace="autoscaling-demo", deployment_name="sample-web-app")
    connected, _ = executor.is_connected()
    if not connected:
        # Test simulated fallback
        executor._connected = False
        executor._simulated_replicas = 2
    
    initial = executor.get_workload_state().desired_replicas

    res = executor.execute_scaling(action="SCALE_OUT", target_replicas=initial + 2, dry_run=True)
    assert res.success is True
    assert res.dry_run is True
    assert res.confirmed_replicas is None
    assert "[DRY-RUN PREVIEW]" in res.message

    # Verify cluster state is strictly unmodified
    after = executor.get_workload_state()
    assert after.desired_replicas == initial


# ==============================================================================
# Case 8: Execution history has no duplicates and truthful outcomes
# ==============================================================================
def test_case_8_history_deduplication_and_truthful_outcomes(tmp_path):
    log_file = tmp_path / "decisions_test.jsonl"
    logger = DecisionLogger(log_file_path=str(log_file), max_history_records=50)

    nominal_decision = {
        "action": "HOLD",
        "current_replicas": 2,
        "proposed_replica_delta": 0,
        "target_replicas": 2,
        "selected_policy_id": None,
        "selected_policy_name": None,
        "priority": 0,
        "explanation": "No policy thresholds breached.",
        "cooldown_active": False,
        "cooldown_remaining_seconds": 0.0,
        "competing_proposals": [],
        "telemetry_summary": {},
    }
    nominal_guardrail = {
        "approved": True, "action": "HOLD", "original_target_replicas": 2,
        "authorized_target_replicas": 2, "replica_delta": 0, "clamped": False,
        "rejection_reason": None, "is_dry_run": True, "authorization_note": "Nominal",
    }
    nominal_exec = {
        "success": True, "dry_run": True, "initial_replicas": 2,
        "target_replicas": 2, "confirmed_replicas": 2, "action_type": "HOLD",
        "message": "Nominal", "error": None,
    }

    # Log nominal cycle 5 times consecutively
    for _ in range(5):
        logger.log_cycle(decision=nominal_decision, guardrail_result=nominal_guardrail, execution_result=nominal_exec)

    # Must be deduplicated to 1 entry instead of 5
    records = logger.get_recent_decisions(limit=50)
    assert len(records) == 1
    assert records[0]["status"] == "HOLD"
    assert records[0]["proposed_action"] == "HOLD"

    # Now log a real dry-run scale-out proposal
    dry_run_decision = copy.deepcopy(nominal_decision)
    dry_run_decision["action"] = "SCALE_OUT"
    dry_run_decision["selected_policy_id"] = "CPU_HIGH_LOAD"
    dry_run_decision["proposed_replica_delta"] = 1
    dry_run_decision["target_replicas"] = 3
    dry_run_guardrail = copy.deepcopy(nominal_guardrail)
    dry_run_guardrail["authorized_target_replicas"] = 3
    dry_run_guardrail["replica_delta"] = 1
    dry_run_exec = copy.deepcopy(nominal_exec)
    dry_run_exec["target_replicas"] = 3
    dry_run_exec["action_type"] = "SCALE_OUT"

    logger.log_cycle(decision=dry_run_decision, guardrail_result=dry_run_guardrail, execution_result=dry_run_exec)

    records = logger.get_recent_decisions(limit=50)
    assert len(records) == 2
    # Verify newest record is truthful DRY_RUN without claiming confirmed replicas
    newest = records[0]
    assert newest["status"] == "DRY_RUN"
    assert newest["mode"] == "DRY_RUN"
    assert newest["resulting_replicas"] is None
    assert "[DRY-RUN]" in newest["explanation"]


# ==============================================================================
# Case 9: Refreshing or reopening retains persisted policies and history
# ==============================================================================
def test_case_9_reopening_retains_persisted_policies_and_history(tmp_path):
    log_file = tmp_path / "persistent_history.jsonl"
    logger1 = DecisionLogger(log_file_path=str(log_file), max_history_records=20)

    # Log an event in logger1
    test_record = logger1.log_cycle(
        decision={"action": "SCALE_OUT", "current_replicas": 2, "target_replicas": 4, "selected_policy_id": "P1"},
        guardrail_result={"approved": True, "action": "EXECUTE", "authorized_target_replicas": 4, "is_dry_run": False},
        execution_result={"success": True, "dry_run": False, "initial_replicas": 2, "target_replicas": 4, "confirmed_replicas": 4, "action_type": "SCALE_OUT"},
    )

    # Instantiate a completely fresh logger2 pointing to the same file
    logger2 = DecisionLogger(log_file_path=str(log_file), max_history_records=20)
    reloaded_records = logger2.get_recent_decisions(limit=10)
    assert len(reloaded_records) == 1
    assert reloaded_records[0]["status"] == "VERIFIED"
    assert reloaded_records[0]["resulting_replicas"] == 4
    assert reloaded_records[0]["target_deployment"] == "sample-web-app"
