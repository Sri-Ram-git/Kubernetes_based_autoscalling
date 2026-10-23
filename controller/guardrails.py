"""
Operational Guardrails and Execution Safety Engine.
Project ID: 357 | Alliance University, Bengaluru

Strict requirement:
- Separates decision proposal from operational execution authorization.
- Enforces replica bounds [min_replicas, max_replicas].
- Enforces step-size bounds (max_scale_step_up, max_scale_step_down).
- Detects redundant/duplicate actions.
- Governs dry-run vs live cluster mutation permissions.
"""

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("autoscaler.guardrails")


@dataclass
class GuardrailResult:
    approved: bool
    action: str  # "EXECUTE", "HOLD", "REJECTED"
    original_target_replicas: int
    authorized_target_replicas: int
    replica_delta: int
    clamped: bool
    rejection_reason: Optional[str]
    is_dry_run: bool
    authorization_note: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GuardrailEngine:
    """Enforces operational limits and safety boundaries on proposed scaling decisions."""

    def __init__(
        self,
        min_replicas: int = 1,
        max_replicas: int = 10,
        max_scale_step_up: int = 2,
        max_scale_step_down: int = 1,
        dry_run: bool = True,
        enable_live_execution: bool = False,
    ):
        if min_replicas < 1:
            raise ValueError(f"min_replicas must be >= 1 (got {min_replicas})")
        if max_replicas < min_replicas:
            raise ValueError(f"max_replicas ({max_replicas}) cannot be less than min_replicas ({min_replicas})")

        self.min_replicas = min_replicas
        self.max_replicas = max_replicas
        self.max_scale_step_up = max_scale_step_up
        self.max_scale_step_down = max_scale_step_down
        self.dry_run = dry_run
        self.enable_live_execution = enable_live_execution

    def set_live_execution(self, enabled: bool) -> None:
        """Update live execution permissions safely at runtime."""
        self.enable_live_execution = enabled
        if enabled:
            self.dry_run = False
        else:
            self.dry_run = True
        logger.info("Guardrail execution state updated: dry_run=%s, enable_live_execution=%s", self.dry_run, self.enable_live_execution)

    def validate_action(
        self,
        proposed_action: str,
        current_replicas: int,
        target_replicas: int,
        replica_delta: int,
    ) -> GuardrailResult:
        """
        Validates proposed scaling action against operational constraints.
        Returns GuardrailResult with approved=True only if the action is fully authorized.
        """
        is_dry_run = self.dry_run or (not self.enable_live_execution)

        # 1. HOLD action requires no cluster changes
        if proposed_action == "HOLD" or replica_delta == 0:
            return GuardrailResult(
                approved=True,
                action="HOLD",
                original_target_replicas=current_replicas,
                authorized_target_replicas=current_replicas,
                replica_delta=0,
                clamped=False,
                rejection_reason=None,
                is_dry_run=is_dry_run,
                authorization_note="No scaling action proposed; maintaining current replica count.",
            )

        # 2. Duplicate / redundant action check
        if target_replicas == current_replicas:
            return GuardrailResult(
                approved=False,
                action="HOLD",
                original_target_replicas=target_replicas,
                authorized_target_replicas=current_replicas,
                replica_delta=0,
                clamped=False,
                rejection_reason="Proposed target replicas equals current replica count; action is redundant.",
                is_dry_run=is_dry_run,
                authorization_note="Redundant request filtered.",
            )

        clamped = False
        notes = []
        final_delta = replica_delta

        # 3. Step size limits
        if proposed_action == "SCALE_OUT" and final_delta > self.max_scale_step_up:
            logger.warning(
                "Scale-out delta (+%d) exceeds max_scale_step_up (+%d). Clamping.",
                final_delta,
                self.max_scale_step_up,
            )
            final_delta = self.max_scale_step_up
            clamped = True
            notes.append(f"Clamped scale-out step size to maximum allowed (+{self.max_scale_step_up}).")

        elif proposed_action == "SCALE_IN" and abs(final_delta) > self.max_scale_step_down:
            logger.warning(
                "Scale-in delta (%d) exceeds max_scale_step_down (-%d). Clamping.",
                final_delta,
                self.max_scale_step_down,
            )
            final_delta = -self.max_scale_step_down
            clamped = True
            notes.append(f"Clamped scale-in step size to maximum allowed (-{self.max_scale_step_down}).")

        authorized_target = current_replicas + final_delta

        # 4. Enforce Boundary: min_replicas
        if authorized_target < self.min_replicas:
            if current_replicas <= self.min_replicas:
                # Already at minimum; cannot scale in further
                return GuardrailResult(
                    approved=False,
                    action="REJECTED",
                    original_target_replicas=target_replicas,
                    authorized_target_replicas=current_replicas,
                    replica_delta=0,
                    clamped=False,
                    rejection_reason=(
                        f"Workload already at minimum replica boundary ({self.min_replicas}). "
                        f"Scale-in to {target_replicas} rejected."
                    ),
                    is_dry_run=is_dry_run,
                    authorization_note=f"Rejected: min_replicas limit reached ({self.min_replicas}).",
                )
            # Clamp to min_replicas
            authorized_target = self.min_replicas
            final_delta = authorized_target - current_replicas
            clamped = True
            notes.append(f"Clamped target to min_replicas boundary ({self.min_replicas}).")

        # 5. Enforce Boundary: max_replicas
        if authorized_target > self.max_replicas:
            if current_replicas >= self.max_replicas:
                # Already at maximum; cannot scale out further
                return GuardrailResult(
                    approved=False,
                    action="REJECTED",
                    original_target_replicas=target_replicas,
                    authorized_target_replicas=current_replicas,
                    replica_delta=0,
                    clamped=False,
                    rejection_reason=(
                        f"Workload already at maximum replica ceiling ({self.max_replicas}). "
                        f"Scale-out to {target_replicas} rejected."
                    ),
                    is_dry_run=is_dry_run,
                    authorization_note=f"Rejected: max_replicas ceiling reached ({self.max_replicas}).",
                )
            # Clamp to max_replicas
            authorized_target = self.max_replicas
            final_delta = authorized_target - current_replicas
            clamped = True
            notes.append(f"Clamped target to max_replicas ceiling ({self.max_replicas}).")

        # 6. Check if clamping produced no net delta
        if final_delta == 0:
            return GuardrailResult(
                approved=False,
                action="HOLD",
                original_target_replicas=target_replicas,
                authorized_target_replicas=current_replicas,
                replica_delta=0,
                clamped=True,
                rejection_reason="Guardrail bounds reduced replica delta to 0.",
                is_dry_run=is_dry_run,
                authorization_note="No delta remaining after guardrail boundary enforcement.",
            )

        auth_msg = (
            f"Authorized {proposed_action}: target {authorized_target} (delta: {final_delta:+d}). "
            f"Mode: {'DRY RUN (Preview Only)' if is_dry_run else 'LIVE CLUSTER MUTATION'}."
        )
        if notes:
            auth_msg += " " + " ".join(notes)

        return GuardrailResult(
            approved=True,
            action="EXECUTE",
            original_target_replicas=target_replicas,
            authorized_target_replicas=authorized_target,
            replica_delta=final_delta,
            clamped=clamped,
            rejection_reason=None,
            is_dry_run=is_dry_run,
            authorization_note=auth_msg,
        )
