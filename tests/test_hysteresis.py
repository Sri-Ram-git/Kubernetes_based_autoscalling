"""
Unit tests for PRAH Hysteresis, Anti-Flapping, and Cooldown logic.
"""

from controller.decision_controller import DecisionController
from controller.policy_engine import PolicyEngine
from controller.telemetry import MetricSample, MetricStatus


def build_engine():
    data = {
        "version": "1.0",
        "policies": [
            {
                "id": "POLICY_SCALE_OUT",
                "name": "Scale-Out Policy",
                "enabled": True,
                "priority": 80,
                "metric": "cpu_utilization_percent",
                "operator": ">",
                "threshold": 75.0,
                "duration_seconds": 0,
                "action": "SCALE_OUT",
                "replica_delta": 1,
                "cooldown_seconds": 60.0,
            },
            {
                "id": "POLICY_SCALE_IN",
                "name": "Scale-In Policy",
                "enabled": True,
                "priority": 80,
                "metric": "cpu_utilization_percent",
                "operator": "<",
                "threshold": 25.0,
                "duration_seconds": 0,
                "action": "SCALE_IN",
                "replica_delta": -1,
                "cooldown_seconds": 60.0,
            },
        ],
    }
    engine = PolicyEngine()
    engine.validate_and_parse(data)
    return engine


def test_cooldown_blocks_subsequent_scaling():
    engine = build_engine()
    ctrl = DecisionController(policy_engine=engine, default_cooldown_seconds=60.0)

    # 1. First cycle at t=100s triggers SCALE_OUT
    metrics_high = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=85.0,
            timestamp=100.0,
            status=MetricStatus.VALID,
            source="test",
            query="q",
        )
    }
    d1 = ctrl.compute_decision(metrics_high, current_replicas=2, now=100.0)
    assert d1.action == "SCALE_OUT"

    # Simulate executor executing this scaling action
    ctrl.record_action_executed(action="SCALE_OUT", policy_id="POLICY_SCALE_OUT", cooldown_seconds=60.0, now=100.0)

    # 2. Second cycle at t=120s (20s into 60s cooldown)
    d2 = ctrl.compute_decision(metrics_high, current_replicas=3, now=120.0)
    assert d2.action == "HOLD"
    assert d2.cooldown_active is True
    assert round(d2.cooldown_remaining_seconds, 1) == 40.0
    assert "cooldown is active (40.0s remaining" in d2.explanation


def test_cooldown_expires_and_permits_scaling():
    engine = build_engine()
    ctrl = DecisionController(policy_engine=engine, default_cooldown_seconds=60.0)

    # Record action at t=100s
    ctrl.record_action_executed(action="SCALE_OUT", policy_id="POLICY_SCALE_OUT", cooldown_seconds=60.0, now=100.0)

    # Cycle at t=165s (65s elapsed, cooldown expired)
    metrics_high = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=85.0,
            timestamp=165.0,
            status=MetricStatus.VALID,
            source="test",
            query="q",
        )
    }
    d = ctrl.compute_decision(metrics_high, current_replicas=3, now=165.0)
    assert d.action == "SCALE_OUT"
    assert d.cooldown_active is False
    assert d.cooldown_remaining_seconds == 0.0


def test_hysteresis_prevents_rapid_direction_flip():
    engine = build_engine()
    # Configure 30s minimum direction flip delay
    ctrl = DecisionController(
        policy_engine=engine,
        default_cooldown_seconds=10.0,
        min_direction_flip_delay_seconds=30.0,
    )

    # At t=100s, scale-out occurred
    ctrl.record_action_executed(action="SCALE_OUT", policy_id="POLICY_SCALE_OUT", cooldown_seconds=10.0, now=100.0)

    # At t=115s (cooldown of 10s expired, but flip delay of 30s still active):
    # Sudden drop in CPU triggers SCALE_IN
    metrics_low = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=15.0,
            timestamp=115.0,
            status=MetricStatus.VALID,
            source="test",
            query="q",
        )
    }

    d = ctrl.compute_decision(metrics_low, current_replicas=3, now=115.0)
    # Hysteresis anti-flapping should convert action to HOLD
    assert d.action == "HOLD"
    assert "PRAH Hysteresis Protection: Opposing action 'SCALE_IN' requested" in d.explanation
    assert "Anti-flapping delay active" in d.explanation


def test_reset_cooldown_allows_immediate_scaling():
    engine = build_engine()
    ctrl = DecisionController(policy_engine=engine, default_cooldown_seconds=60.0)

    ctrl.record_action_executed(action="SCALE_OUT", policy_id="POLICY_SCALE_OUT", cooldown_seconds=60.0, now=100.0)
    ctrl.reset_cooldown()

    metrics_high = {
        "cpu_utilization_percent": MetricSample(
            metric_name="cpu_utilization_percent",
            value=85.0,
            timestamp=105.0,
            status=MetricStatus.VALID,
            source="test",
            query="q",
        )
    }
    d = ctrl.compute_decision(metrics_high, current_replicas=3, now=105.0)
    assert d.action == "SCALE_OUT"
