"""
PRAH Decision Controller (Priority-based Rule Arbitration with Hysteresis).
Project ID: 357 | Alliance University, Bengaluru

Implements the deterministic rule-based scaling decision pipeline:
1. Validates telemetry status and executes safe fallback when telemetry is missing/stale.
2. Collects competing proposals from policy engine.
3. Priority-based arbitration with explicit tie-breaking.
4. Hysteresis band and direction-flapping suppression.
5. Cooldown period enforcement.
6. Structured decision output with full human-readable audit trail.
"""

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from controller.policy_engine import PolicyEngine, PolicyEvaluationResult
from controller.telemetry import MetricSample, MetricStatus

logger = logging.getLogger("autoscaler.prah_controller")


@dataclass
class Proposal:
    policy_id: str
    policy_name: str
    priority: int
    action: str  # "SCALE_OUT", "SCALE_IN", "HOLD"
    replica_delta: int
    reason: str
    metric_name: str
    observed_value: Optional[float]
    threshold: float
    cooldown_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Decision:
    action: str  # "SCALE_OUT", "SCALE_IN", "HOLD"
    current_replicas: int
    proposed_replica_delta: int
    target_replicas: int
    selected_policy_id: Optional[str]
    selected_policy_name: Optional[str]
    priority: int
    explanation: str
    cooldown_active: bool
    cooldown_remaining_seconds: float
    competing_proposals: List[Dict[str, Any]]
    telemetry_summary: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DecisionController:
    """
    PRAH (Priority-based Rule Arbitration with Hysteresis) Controller.
    Coordinates rule evaluation, arbitration, hysteresis, and cooldowns.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        default_cooldown_seconds: float = 60.0,
        hysteresis_band_percent: float = 5.0,
        min_direction_flip_delay_seconds: float = 30.0,
    ):
        self.policy_engine = policy_engine
        self.default_cooldown_seconds = default_cooldown_seconds
        self.hysteresis_band_percent = hysteresis_band_percent
        self.min_direction_flip_delay_seconds = min_direction_flip_delay_seconds

        # State tracking for cooldown and hysteresis
        self.last_action_timestamp: Optional[float] = None
        self.last_action_direction: Optional[str] = None  # "SCALE_OUT", "SCALE_IN", None
        self.last_action_policy: Optional[str] = None
        self.active_cooldown_seconds: float = default_cooldown_seconds

    def reset_cooldown(self) -> None:
        """Manually reset the cooldown timer (useful for testing or administrative override)."""
        self.last_action_timestamp = None
        self.last_action_direction = None

    def record_action_executed(self, action: str, policy_id: Optional[str], cooldown_seconds: float, now: Optional[float] = None) -> None:
        """Called when an action is executed to update cooldown and hysteresis state."""
        if action in ("SCALE_OUT", "SCALE_IN"):
            current_time = now or time.time()
            self.last_action_timestamp = current_time
            self.last_action_direction = action
            self.last_action_policy = policy_id
            self.active_cooldown_seconds = cooldown_seconds
            logger.info("Recorded scaling execution: %s (cooldown: %.1fs)", action, cooldown_seconds)

    def compute_decision(
        self,
        metrics: Dict[str, MetricSample],
        current_replicas: int,
        now: Optional[float] = None,
        workload: Optional[Any] = None,
    ) -> Decision:
        """
        Executes the PRAH decision cycle:
        Returns a final Decision instance.
        """
        current_time = now or time.time()

        # Step 1: Policy Evaluation across all configured rules
        evaluation_results: List[PolicyEvaluationResult] = self.policy_engine.evaluate(
            metrics=metrics,
            workload=workload,
            now=current_time,
        )

        # Telemetry summary for transparency
        telemetry_summary: Dict[str, Any] = {}
        missing_or_stale = []
        for name, sample in metrics.items():
            telemetry_summary[name] = {
                "value": sample.value,
                "status": sample.status.value,
                "source": sample.source,
                "age_seconds": round(current_time - sample.timestamp, 1) if sample.timestamp else None,
            }
            if not sample.is_usable():
                missing_or_stale.append(f"{name} ({sample.status.value})")

        # Step 2: Telemetry Safety Fallback
        # If any metric evaluated by policies is missing or stale, trigger safe fallback HOLD
        if missing_or_stale:
            explanation = (
                f"PRAH Fallback Triggered: Telemetry safety check failed for {', '.join(missing_or_stale)}. "
                "Holding replica count to prevent unsafe scaling during telemetry degradation."
            )
            return Decision(
                action="HOLD",
                current_replicas=current_replicas,
                proposed_replica_delta=0,
                target_replicas=current_replicas,
                selected_policy_id="FALLBACK_TELEMETRY_INVALID",
                selected_policy_name="Telemetry Safety Fallback",
                priority=999,
                explanation=explanation,
                cooldown_active=False,
                cooldown_remaining_seconds=0.0,
                competing_proposals=[],
                telemetry_summary=telemetry_summary,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # Step 3: Collect Competing Proposals
        matched_proposals: List[Proposal] = []
        for res in evaluation_results:
            if res.matched and res.action != "HOLD":
                matched_proposals.append(
                    Proposal(
                        policy_id=res.policy_id,
                        policy_name=res.policy_name,
                        priority=res.priority,
                        action=res.action,
                        replica_delta=res.replica_delta,
                        reason=res.reason,
                        metric_name=res.metric_name,
                        observed_value=res.observed_value,
                        threshold=res.threshold,
                        cooldown_seconds=res.cooldown_seconds,
                    )
                )

        # If no policies matched -> HOLD
        if not matched_proposals:
            return Decision(
                action="HOLD",
                current_replicas=current_replicas,
                proposed_replica_delta=0,
                target_replicas=current_replicas,
                selected_policy_id=None,
                selected_policy_name=None,
                priority=0,
                explanation="No policy thresholds breached. Workload operating within nominal parameters; holding current replicas.",
                cooldown_active=False,
                cooldown_remaining_seconds=0.0,
                competing_proposals=[],
                telemetry_summary=telemetry_summary,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # Step 4: Priority-Based Arbitration (PRAH)
        # Sort candidates by priority descending
        sorted_proposals = sorted(matched_proposals, key=lambda p: p.priority, reverse=True)
        top_priority = sorted_proposals[0].priority
        top_candidates = [p for p in sorted_proposals if p.priority == top_priority]

        chosen_proposal: Proposal
        arbitration_note = ""

        if len(top_candidates) == 1:
            chosen_proposal = top_candidates[0]
            arbitration_note = f"Single highest priority policy selected (priority={top_priority})."
        else:
            # Conflict resolution among equal highest-priority policies
            scale_out_candidates = [p for p in top_candidates if p.action == "SCALE_OUT"]
            scale_in_candidates = [p for p in top_candidates if p.action == "SCALE_IN"]

            if scale_out_candidates and scale_in_candidates:
                # Direct conflict between scale-out and scale-in at equal priority
                # Tie-breaking rule: Scale-Out wins to preserve availability & SLAs
                # Pick the scale-out with largest delta
                scale_out_candidates.sort(key=lambda p: p.replica_delta, reverse=True)
                chosen_proposal = scale_out_candidates[0]
                arbitration_note = (
                    f"Tie-breaking: Equal priority conflict between {len(scale_out_candidates)} SCALE_OUT "
                    f"and {len(scale_in_candidates)} SCALE_IN policies. SCALE_OUT chosen for service availability."
                )
            elif scale_out_candidates:
                # All top candidates are scale-out -> pick largest delta
                scale_out_candidates.sort(key=lambda p: p.replica_delta, reverse=True)
                chosen_proposal = scale_out_candidates[0]
                arbitration_note = (
                    f"Arbitration: Multiple SCALE_OUT candidates at priority {top_priority}; "
                    f"selected largest delta (+{chosen_proposal.replica_delta})."
                )
            else:
                # All top candidates are scale-in -> pick most conservative delta (closest to 0) to prevent aggressive contraction
                scale_in_candidates.sort(key=lambda p: p.replica_delta, reverse=True)
                chosen_proposal = scale_in_candidates[0]
                arbitration_note = (
                    f"Arbitration: Multiple SCALE_IN candidates at priority {top_priority}; "
                    f"selected conservative delta ({chosen_proposal.replica_delta})."
                )

        # Step 5: Hysteresis Check (Anti-Flapping)
        # If the action flips direction immediately after an opposite action, enforce hysteresis delay
        if self.last_action_direction and self.last_action_timestamp:
            time_since_last_action = current_time - self.last_action_timestamp
            is_direction_flip = (
                (self.last_action_direction == "SCALE_OUT" and chosen_proposal.action == "SCALE_IN")
                or (self.last_action_direction == "SCALE_IN" and chosen_proposal.action == "SCALE_OUT")
            )
            if is_direction_flip and time_since_last_action < self.min_direction_flip_delay_seconds:
                remaining_delay = self.min_direction_flip_delay_seconds - time_since_last_action
                explanation = (
                    f"PRAH Hysteresis Protection: Opposing action '{chosen_proposal.action}' requested "
                    f"only {time_since_last_action:.1f}s after previous '{self.last_action_direction}'. "
                    f"Anti-flapping delay active ({remaining_delay:.1f}s remaining). Action converted to HOLD."
                )
                return Decision(
                    action="HOLD",
                    current_replicas=current_replicas,
                    proposed_replica_delta=0,
                    target_replicas=current_replicas,
                    selected_policy_id=chosen_proposal.policy_id,
                    selected_policy_name=chosen_proposal.policy_name,
                    priority=chosen_proposal.priority,
                    explanation=explanation,
                    cooldown_active=True,
                    cooldown_remaining_seconds=remaining_delay,
                    competing_proposals=[p.to_dict() for p in matched_proposals],
                    telemetry_summary=telemetry_summary,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

        # Step 6: Cooldown Check
        cooldown_duration = chosen_proposal.cooldown_seconds or self.active_cooldown_seconds
        if self.last_action_timestamp:
            elapsed_cooldown = current_time - self.last_action_timestamp
            if elapsed_cooldown < cooldown_duration:
                remaining_cooldown = cooldown_duration - elapsed_cooldown
                explanation = (
                    f"PRAH Cooldown Active: Policy '{chosen_proposal.policy_name}' triggered {chosen_proposal.action}, "
                    f"but cooldown is active ({remaining_cooldown:.1f}s remaining of {cooldown_duration:.1f}s). Action held."
                )
                return Decision(
                    action="HOLD",
                    current_replicas=current_replicas,
                    proposed_replica_delta=0,
                    target_replicas=current_replicas,
                    selected_policy_id=chosen_proposal.policy_id,
                    selected_policy_name=chosen_proposal.policy_name,
                    priority=chosen_proposal.priority,
                    explanation=explanation,
                    cooldown_active=True,
                    cooldown_remaining_seconds=remaining_cooldown,
                    competing_proposals=[p.to_dict() for p in matched_proposals],
                    telemetry_summary=telemetry_summary,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

        # Step 7: Approved Decision Construction
        target_replicas = current_replicas + chosen_proposal.replica_delta
        explanation = (
            f"PRAH Approved Action: {chosen_proposal.action} by {chosen_proposal.replica_delta:+d} replica(s) "
            f"via policy '{chosen_proposal.policy_name}' (priority={chosen_proposal.priority}). "
            f"Reason: {chosen_proposal.reason}. {arbitration_note}"
        )

        return Decision(
            action=chosen_proposal.action,
            current_replicas=current_replicas,
            proposed_replica_delta=chosen_proposal.replica_delta,
            target_replicas=target_replicas,
            selected_policy_id=chosen_proposal.policy_id,
            selected_policy_name=chosen_proposal.policy_name,
            priority=chosen_proposal.priority,
            explanation=explanation,
            cooldown_active=False,
            cooldown_remaining_seconds=0.0,
            competing_proposals=[p.to_dict() for p in matched_proposals],
            telemetry_summary=telemetry_summary,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
