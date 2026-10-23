"""
Unit tests for Operational Guardrails and Safety Boundaries.
"""

import pytest

from controller.guardrails import GuardrailEngine, GuardrailResult


def test_guardrail_initialization_validation():
    # Valid
    ge = GuardrailEngine(min_replicas=1, max_replicas=10)
    assert ge.min_replicas == 1
    assert ge.max_replicas == 10

    # min_replicas < 1 raises
    with pytest.raises(ValueError, match="min_replicas must be >= 1"):
        GuardrailEngine(min_replicas=0, max_replicas=5)

    # max_replicas < min_replicas raises
    with pytest.raises(ValueError, match="cannot be less than min_replicas"):
        GuardrailEngine(min_replicas=5, max_replicas=2)


def test_min_replicas_boundary_rejection():
    ge = GuardrailEngine(min_replicas=2, max_replicas=10)

    # Already at min (2), scale-in proposed
    result = ge.validate_action(
        proposed_action="SCALE_IN",
        current_replicas=2,
        target_replicas=1,
        replica_delta=-1,
    )
    assert result.approved is False
    assert result.action == "REJECTED"
    assert "already at minimum replica boundary" in result.rejection_reason
    assert result.authorized_target_replicas == 2


def test_min_replicas_clamping():
    ge = GuardrailEngine(min_replicas=2, max_replicas=10, max_scale_step_down=3)

    # Current is 3, scale-in proposes delta -2 -> target 1 (< 2)
    result = ge.validate_action(
        proposed_action="SCALE_IN",
        current_replicas=3,
        target_replicas=1,
        replica_delta=-2,
    )
    assert result.approved is True
    assert result.action == "EXECUTE"
    assert result.clamped is True
    assert result.authorized_target_replicas == 2
    assert result.replica_delta == -1


def test_max_replicas_boundary_rejection():
    ge = GuardrailEngine(min_replicas=1, max_replicas=5)

    # Already at max (5), scale-out proposed
    result = ge.validate_action(
        proposed_action="SCALE_OUT",
        current_replicas=5,
        target_replicas=6,
        replica_delta=1,
    )
    assert result.approved is False
    assert result.action == "REJECTED"
    assert "already at maximum replica ceiling" in result.rejection_reason
    assert result.authorized_target_replicas == 5


def test_max_replicas_clamping():
    ge = GuardrailEngine(min_replicas=1, max_replicas=5, max_scale_step_up=3)

    # Current is 4, scale-out proposes delta +2 -> target 6 (> 5)
    result = ge.validate_action(
        proposed_action="SCALE_OUT",
        current_replicas=4,
        target_replicas=6,
        replica_delta=2,
    )
    assert result.approved is True
    assert result.action == "EXECUTE"
    assert result.clamped is True
    assert result.authorized_target_replicas == 5
    assert result.replica_delta == 1


def test_scale_step_size_clamping():
    ge = GuardrailEngine(
        min_replicas=1,
        max_replicas=10,
        max_scale_step_up=2,
        max_scale_step_down=1,
    )

    # Scale-out by +4 should be clamped to +2
    res_up = ge.validate_action(
        proposed_action="SCALE_OUT",
        current_replicas=2,
        target_replicas=6,
        replica_delta=4,
    )
    assert res_up.approved is True
    assert res_up.clamped is True
    assert res_up.replica_delta == 2
    assert res_up.authorized_target_replicas == 4

    # Scale-in by -3 should be clamped to -1
    res_down = ge.validate_action(
        proposed_action="SCALE_IN",
        current_replicas=6,
        target_replicas=3,
        replica_delta=-3,
    )
    assert res_down.approved is True
    assert res_down.clamped is True
    assert res_down.replica_delta == -1
    assert res_down.authorized_target_replicas == 5


def test_duplicate_redundant_action_filtered():
    ge = GuardrailEngine(min_replicas=1, max_replicas=10)

    result = ge.validate_action(
        proposed_action="SCALE_OUT",
        current_replicas=3,
        target_replicas=3,
        replica_delta=1,  # Inconsistent with target == current
    )
    assert result.approved is False
    assert result.action == "HOLD"
    assert "action is redundant" in result.rejection_reason


def test_dry_run_vs_live_execution_flag():
    ge = GuardrailEngine(dry_run=True, enable_live_execution=False)
    res_dry = ge.validate_action(
        proposed_action="SCALE_OUT",
        current_replicas=2,
        target_replicas=3,
        replica_delta=1,
    )
    assert res_dry.is_dry_run is True
    assert "DRY RUN" in res_dry.authorization_note

    # Switch to live
    ge.set_live_execution(True)
    res_live = ge.validate_action(
        proposed_action="SCALE_OUT",
        current_replicas=2,
        target_replicas=3,
        replica_delta=1,
    )
    assert res_live.is_dry_run is False
    assert "LIVE CLUSTER MUTATION" in res_live.authorization_note
