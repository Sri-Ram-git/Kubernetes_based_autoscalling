"""
Unit tests for PRAH Decision Controller (Priority arbitration, tie-breaking, safe fallback).
"""

import pytest

from controller.decision_controller import DecisionController
from controller.policy_engine import PolicyEngine
from controller.telemetry import MetricSample, MetricStatus


def build_test_engine():
    data = {
        "version": "1.0",
        "policies": [
            {
                "id": "HIGH_PRIORITY_OUT",
                "name": "High Priority Scale-Out",
                "enabled": True,
                "priority": 90,
                "metric": "cpu_utilization_percent",
                "operator": ">=",
                "threshold": 80.0,
                "duration_seconds": 0,
                "action": "SCALE_OUT",
                "replica_delta": 2,
                "cooldown_seconds": 60,
            },
            {
                "id": "LOW_PRIORITY_OUT",
                "name": "Low Priority Scale-Out",
                "enabled": True,
                "priority": 50,
                "metric": "cpu_utilization_percent",
                "operator": ">",
                "threshold": 70.0,
                "duration_seconds": 0,
                "action": "SCALE_OUT",
                "replica_delta": 1,
                "cooldown_seconds": 60,
            },
            {
                "id": "EQUAL_PRIORITY_IN",
                "name": "Equal Priority Scale-In",
                "enabled": True,
                "priority": 90,
                "metric": "memory_utilization_percent",
                "operator": "<",
                "threshold": 30.0,
                "duration_seconds": 0,
                "action": "SCALE_IN",
                "replica_delta": -1,
                "cooldown_seconds": 60,
            },
        ],
    }
    engine = PolicyEngine()
    engine.validate_and_parse(data)
    return engine


def test_priority_arbitration_selects_higher_priority():
    engine = build_test_engine()
    ctrl = DecisionController(policy_engine=engine)

    # CPU is 85% -> both HIGH_PRIORITY_OUT (priority 90) and LOW_PRIORITY_OUT (priority 50) match
    # Memory is 50% -> EQUAL_PRIORITY_IN does not match
    metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=85.0,
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="test",
            query="q",
        ),
        "memory_utilization_percent": MetricSample(
            metric_name="memory_utilization_percent",
            value=50.0,
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="test",
            query="q",
        ),
    }

    decision = ctrl.compute_decision(metrics, current_replicas=2, now=100.0)

    assert decision.action == "SCALE_OUT"
    assert decision.selected_policy_id == "HIGH_PRIORITY_OUT"
    assert decision.priority == 90
    assert decision.proposed_replica_delta == 2
    assert decision.target_replicas == 4
    assert len(decision.competing_proposals) == 2


def test_equal_priority_conflict_tie_breaking_scale_out_wins():
    engine = build_test_engine()
    ctrl = DecisionController(policy_engine=engine)

    # Both priority 90 rules match:
    # HIGH_PRIORITY_OUT (CPU >= 80) -> SCALE_OUT (+2)
    # EQUAL_PRIORITY_IN (MEM < 30) -> SCALE_IN (-1)
    metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=85.0,
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="test",
            query="q",
        ),
        "memory_utilization_percent": MetricSample(
            metric_name="memory_utilization_percent",
            value=20.0,
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="test",
            query="q",
        ),
    }

    decision = ctrl.compute_decision(metrics, current_replicas=3, now=100.0)

    # Scale-out takes precedence for service availability
    assert decision.action == "SCALE_OUT"
    assert decision.priority == 90
    assert decision.selected_policy_id == "HIGH_PRIORITY_OUT"
    assert "Tie-breaking" in decision.explanation
    assert "SCALE_OUT chosen for service availability" in decision.explanation


def test_missing_metrics_triggers_safe_fallback_hold():
    engine = build_test_engine()
    ctrl = DecisionController(policy_engine=engine)

    # CPU metric is missing
    metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=None,
            timestamp=100.0,
            status=MetricStatus.MISSING,
            source="test",
            query="q",
            error_message="Prometheus connection down",
        ),
    }

    decision = ctrl.compute_decision(metrics, current_replicas=3, now=100.0)

    assert decision.action == "HOLD"
    assert decision.selected_policy_id == "FALLBACK_TELEMETRY_INVALID"
    assert "Telemetry safety check failed" in decision.explanation
    assert decision.target_replicas == 3


def test_stale_metrics_triggers_safe_fallback_hold():
    engine = build_test_engine()
    ctrl = DecisionController(policy_engine=engine)

    # Metric is stale
    metrics = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=95.0,
            timestamp=100.0,
            status=MetricStatus.STALE,
            source="test",
            query="q",
            error_message="Telemetry stale by 90s",
        ),
    }

    decision = ctrl.compute_decision(metrics, current_replicas=3, now=100.0)

    assert decision.action == "HOLD"
    assert "Fallback Triggered" in decision.explanation
