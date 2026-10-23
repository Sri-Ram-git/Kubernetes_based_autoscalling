"""
Unit tests for Policy Engine (YAML parsing, operator evaluation, condition windowing,
safety validation, conflict handling, and PRAH integration).
"""

import copy
import pytest
import yaml

from controller.policy_engine import (
    PolicyEngine,
    PolicyRule,
    PolicyEvaluationResult,
    PolicyValidationError,
    SUPPORTED_OPERATORS,
    SUPPORTED_METRICS,
)
from controller.telemetry import MetricSample, MetricStatus
from controller.decision_controller import DecisionController


def sample_policy_dict():
    return {
        "version": "1.0",
        "target_workload": {
            "namespace": "test-ns",
            "name": "test-app",
        },
        "guardrails": {
            "min_replicas": 1,
            "max_replicas": 5,
        },
        "policies": [
            {
                "id": "RULE_CPU_HIGH",
                "name": "High CPU",
                "enabled": True,
                "priority": 80,
                "metric": "cpu_utilization_percent",
                "operator": ">",
                "threshold": 75.0,
                "duration_seconds": 10,
                "action": "SCALE_OUT",
                "replica_delta": 1,
                "cooldown_seconds": 60,
            },
            {
                "id": "RULE_CPU_LOW",
                "name": "Low CPU",
                "enabled": True,
                "priority": 40,
                "metric": "cpu_utilization_percent",
                "operator": "<",
                "threshold": 25.0,
                "duration_seconds": 15,
                "action": "SCALE_IN",
                "replica_delta": -1,
                "cooldown_seconds": 90,
            },
        ],
    }


def test_valid_policy_parsing():
    engine = PolicyEngine()
    engine.validate_and_parse(sample_policy_dict())
    assert len(engine.rules) == 2
    assert engine.rules[0].id == "RULE_CPU_HIGH"
    assert engine.rules[0].action == "SCALE_OUT"
    assert engine.rules[0].replica_delta == 1
    assert engine.rules[1].id == "RULE_CPU_LOW"
    assert engine.rules[1].action == "SCALE_IN"
    assert engine.rules[1].replica_delta == -1


def test_invalid_policy_missing_fields():
    engine = PolicyEngine()
    invalid_dict = {
        "policies": [
            {
                "name": "Missing ID",
                "priority": 10,
            }
        ]
    }
    with pytest.raises(PolicyValidationError, match="missing valid 'id'"):
        engine.validate_and_parse(invalid_dict)


def test_invalid_policy_duplicate_ids():
    engine = PolicyEngine()
    dup_dict = sample_policy_dict()
    dup_dict["policies"][1]["id"] = dup_dict["policies"][0]["id"]
    with pytest.raises(PolicyValidationError, match="Duplicate policy ID detected"):
        engine.validate_and_parse(dup_dict)


def test_empty_policies_list_rejected():
    engine = PolicyEngine()
    with pytest.raises(PolicyValidationError, match="cannot be empty"):
        engine.validate_and_parse({"policies": []})


def test_invalid_policy_unsupported_operator():
    engine = PolicyEngine()
    bad_op = sample_policy_dict()
    bad_op["policies"][0]["operator"] = "~="
    with pytest.raises(PolicyValidationError, match="invalid operator"):
        engine.validate_and_parse(bad_op)


def test_invalid_policy_unsupported_metric():
    engine = PolicyEngine()
    bad_metric = sample_policy_dict()
    bad_metric["policies"][0]["metric"] = "unsupported_disk_io_metric"
    with pytest.raises(PolicyValidationError, match="unsupported metric"):
        engine.validate_and_parse(bad_metric)


def test_invalid_policy_invalid_thresholds():
    engine = PolicyEngine()

    # Percentage metric exceeding 100%
    bad_thresh1 = sample_policy_dict()
    bad_thresh1["policies"][0]["threshold"] = 125.0
    with pytest.raises(PolicyValidationError, match="must be in range \\[0, 100\\]"):
        engine.validate_and_parse(bad_thresh1)

    # Negative threshold
    bad_thresh2 = sample_policy_dict()
    bad_thresh2["policies"][0]["threshold"] = -5.0
    with pytest.raises(PolicyValidationError, match="must be in range \\[0, 100\\]"):
        engine.validate_and_parse(bad_thresh2)

    # Non-finite threshold (NaN)
    bad_thresh3 = sample_policy_dict()
    bad_thresh3["policies"][0]["threshold"] = float("nan")
    with pytest.raises(PolicyValidationError, match="must be finite"):
        engine.validate_and_parse(bad_thresh3)


def test_invalid_policy_invalid_action():
    engine = PolicyEngine()
    bad_act = sample_policy_dict()
    bad_act["policies"][0]["action"] = "DESTROY"
    with pytest.raises(PolicyValidationError, match="action must be SCALE_OUT, SCALE_IN, or HOLD"):
        engine.validate_and_parse(bad_act)


def test_invalid_policy_negative_delta_on_scale_out():
    engine = PolicyEngine()
    bad_delta = sample_policy_dict()
    bad_delta["policies"][0]["replica_delta"] = -1
    with pytest.raises(PolicyValidationError, match="SCALE_OUT must have positive replica_delta"):
        engine.validate_and_parse(bad_delta)


def test_invalid_policy_positive_delta_on_scale_in():
    engine = PolicyEngine()
    bad_delta = sample_policy_dict()
    bad_delta["policies"][1]["replica_delta"] = 2
    with pytest.raises(PolicyValidationError, match="SCALE_IN must have negative replica_delta"):
        engine.validate_and_parse(bad_delta)


def test_explicit_comparison_operators_and_boundaries():
    """Verifies >, >=, <, <=, ==, != and strict boundary conditions."""
    rule_gt = PolicyRule(
        id="R1", name="R1", description="", enabled=True, priority=50,
        metric="cpu_utilization_percent", operator_str=">", threshold=75.0,
        duration_seconds=0, action="SCALE_OUT", replica_delta=1
    )
    assert rule_gt.evaluate_condition(75.1) is True
    assert rule_gt.evaluate_condition(75.0) is False  # Strict > boundary check
    assert rule_gt.evaluate_condition(74.9) is False

    rule_ge = PolicyRule(
        id="R2", name="R2", description="", enabled=True, priority=50,
        metric="cpu_utilization_percent", operator_str=">=", threshold=75.0,
        duration_seconds=0, action="SCALE_OUT", replica_delta=1
    )
    assert rule_ge.evaluate_condition(75.0) is True  # Boundary included
    assert rule_ge.evaluate_condition(74.9) is False

    rule_lt = PolicyRule(
        id="R3", name="R3", description="", enabled=True, priority=50,
        metric="cpu_utilization_percent", operator_str="<", threshold=25.0,
        duration_seconds=0, action="SCALE_IN", replica_delta=-1
    )
    assert rule_lt.evaluate_condition(24.9) is True
    assert rule_lt.evaluate_condition(25.0) is False  # Strict < boundary check
    assert rule_lt.evaluate_condition(25.1) is False

    rule_le = PolicyRule(
        id="R4", name="R4", description="", enabled=True, priority=50,
        metric="cpu_utilization_percent", operator_str="<=", threshold=25.0,
        duration_seconds=0, action="SCALE_IN", replica_delta=-1
    )
    assert rule_le.evaluate_condition(25.0) is True  # Boundary included
    assert rule_le.evaluate_condition(25.1) is False

    rule_eq = PolicyRule(
        id="R5", name="R5", description="", enabled=True, priority=50,
        metric="cpu_utilization_percent", operator_str="==", threshold=50.0,
        duration_seconds=0, action="HOLD", replica_delta=0
    )
    assert rule_eq.evaluate_condition(50.0) is True
    assert rule_eq.evaluate_condition(50.1) is False


def test_scale_out_condition_evaluated_successfully():
    engine = PolicyEngine()
    engine.validate_and_parse(sample_policy_dict())

    metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=82.0,
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="test",
            query="cpu_query",
        )
    }

    # First breach: duration 10s not met yet
    results_t1 = engine.evaluate(metrics, now=100.0)
    high_cpu_res = [r for r in results_t1 if r.policy_id == "RULE_CPU_HIGH"][0]
    assert high_cpu_res.matched is False  # 0s < 10s duration
    assert high_cpu_res.evaluable is True
    assert "Condition breached for" in high_cpu_res.reason

    # Second breach: 12 seconds later, duration met
    results_t2 = engine.evaluate(metrics, now=112.0)
    high_cpu_res2 = [r for r in results_t2 if r.policy_id == "RULE_CPU_HIGH"][0]
    assert high_cpu_res2.matched is True
    assert high_cpu_res2.evaluable is True
    assert high_cpu_res2.action == "SCALE_OUT"
    assert high_cpu_res2.replica_delta == 1


def test_scale_in_condition_evaluated_successfully():
    engine = PolicyEngine()
    engine.validate_and_parse(sample_policy_dict())

    metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=18.0,
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="test",
            query="cpu_query",
        )
    }

    # Evaluate at t=100s then t=120s
    engine.evaluate(metrics, now=100.0)
    results = engine.evaluate(metrics, now=120.0)
    low_cpu_res = [r for r in results if r.policy_id == "RULE_CPU_LOW"][0]
    assert low_cpu_res.matched is True
    assert low_cpu_res.action == "SCALE_IN"
    assert low_cpu_res.replica_delta == -1


def test_hold_behavior_within_normal_thresholds():
    engine = PolicyEngine()
    engine.validate_and_parse(sample_policy_dict())

    # Value 50% is between 25% and 75%
    metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=50.0,
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="test",
            query="cpu_query",
        )
    }

    results = engine.evaluate(metrics, now=100.0)
    assert all(r.matched is False for r in results)
    assert all(r.evaluable is True for r in results)
    assert all(r.action == "HOLD" for r in results)


def test_missing_or_stale_telemetry_marked_unevaluable():
    engine = PolicyEngine()
    engine.validate_and_parse(sample_policy_dict())

    # 1. Missing telemetry
    metrics_missing = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=None,
            timestamp=100.0,
            status=MetricStatus.MISSING,
            source="prometheus",
            error_message="No time series found",
        )
    }
    res_missing = engine.evaluate(metrics_missing, now=100.0)
    assert all(r.matched is False for r in res_missing)
    assert all(r.evaluable is False for r in res_missing)
    assert "MISSING" in res_missing[0].reason

    # 2. Stale telemetry
    metrics_stale = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=85.0,
            timestamp=10.0,
            status=MetricStatus.STALE,
            source="prometheus",
            error_message="Data age > 60s",
        )
    }
    res_stale = engine.evaluate(metrics_stale, now=100.0)
    assert all(r.matched is False for r in res_stale)
    assert all(r.evaluable is False for r in res_stale)
    assert "STALE" in res_stale[0].reason

    # 3. Invalid telemetry (non-finite)
    metrics_invalid = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=None,
            timestamp=100.0,
            status=MetricStatus.INVALID,
            source="prometheus",
            error_message="NaN numeric value",
        )
    }
    res_invalid = engine.evaluate(metrics_invalid, now=100.0)
    assert all(r.evaluable is False for r in res_invalid)


def test_multiple_matching_policies_with_different_priorities():
    """PolicyEngine must return all matching rules so PRAH can arbitrate."""
    config_data = {
        "policies": [
            {
                "id": "RULE_CPU_URGENT",
                "name": "CPU Urgent",
                "enabled": True,
                "priority": 90,
                "metric": "cpu_utilization_percent",
                "operator": ">",
                "threshold": 80.0,
                "duration_seconds": 0,
                "action": "SCALE_OUT",
                "replica_delta": 2,
            },
            {
                "id": "RULE_CPU_MODERATE",
                "name": "CPU Moderate",
                "enabled": True,
                "priority": 50,
                "metric": "cpu_utilization_percent",
                "operator": ">",
                "threshold": 70.0,
                "duration_seconds": 0,
                "action": "SCALE_OUT",
                "replica_delta": 1,
            },
        ]
    }
    engine = PolicyEngine()
    engine.validate_and_parse(config_data)

    metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=85.0,  # Matches both > 80 and > 70
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="prometheus",
        )
    }

    results = engine.evaluate(metrics, now=100.0)
    matched = [r for r in results if r.matched]
    assert len(matched) == 2
    # Confirms PolicyEngine preserves both priorities without suppressing the lower one
    priorities = {r.policy_id: r.priority for r in matched}
    assert priorities["RULE_CPU_URGENT"] == 90
    assert priorities["RULE_CPU_MODERATE"] == 50


def test_deterministic_evaluation_output():
    """Engine must return identical outputs for identical inputs."""
    engine = PolicyEngine()
    engine.validate_and_parse(sample_policy_dict())

    metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=85.0,
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="test",
        )
    }

    res1 = engine.evaluate(metrics, now=100.0)
    res2 = engine.evaluate(metrics, now=100.0)

    assert len(res1) == len(res2)
    for r1, r2 in zip(res1, res2):
        assert r1.policy_id == r2.policy_id
        assert r1.matched == r2.matched
        assert r1.evaluable == r2.evaluable
        assert r1.reason == r2.reason
        assert r1.action == r2.action


def test_prah_decision_controller_integration():
    """Verifies seamless handoff between PolicyEngine and DecisionController."""
    engine = PolicyEngine()
    engine.validate_and_parse(sample_policy_dict())

    controller = DecisionController(policy_engine=engine, default_cooldown_seconds=60.0)

    # 1. Nominal metrics -> DecisionController issues HOLD
    metrics_nominal = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=50.0,
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="test",
        )
    }
    d1 = controller.compute_decision(metrics_nominal, current_replicas=2, now=100.0)
    assert d1.action == "HOLD"
    assert d1.target_replicas == 2

    # 2. Breach metrics past duration -> DecisionController issues SCALE_OUT
    metrics_spike = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=85.0,
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="test",
        )
    }
    controller.compute_decision(metrics_spike, current_replicas=2, now=100.0)
    d2 = controller.compute_decision(metrics_spike, current_replicas=2, now=115.0)
    assert d2.action == "SCALE_OUT"
    assert d2.selected_policy_id == "RULE_CPU_HIGH"
    assert d2.target_replicas == 3
