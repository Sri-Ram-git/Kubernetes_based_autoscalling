"""
Scaling Strategy Coordinator.
Project ID: 357 | Alliance University, Bengaluru

Strict requirement:
- Clear controller ownership: direct Deployment replica control.
- Avoids simultaneous competing writes to the same replica field.
- Checks and guards against competing native HPA instances on the target workload.
"""

import logging
from typing import Any, Dict, Optional, Tuple

from controller.guardrails import GuardrailEngine, GuardrailResult
from controller.kubernetes_executor import ExecutionResult, KubernetesExecutor

logger = logging.getLogger("autoscaler.strategy_coordinator")

try:
    from kubernetes import client
    from kubernetes.client.rest import ApiException
    AUTOSCALING_API_AVAILABLE = True
except ImportError:
    AUTOSCALING_API_AVAILABLE = False


class StrategyCoordinator:
    """Coordinates scaling strategy execution and validates exclusive ownership."""

    def __init__(
        self,
        executor: KubernetesExecutor,
        guardrail_engine: GuardrailEngine,
        enforce_exclusive_ownership: bool = True,
    ):
        self.executor = executor
        self.guardrail_engine = guardrail_engine
        self.enforce_exclusive_ownership = enforce_exclusive_ownership
        self._autoscaling_v2_api = None

        if AUTOSCALING_API_AVAILABLE and executor._connected and executor._apps_v1_api:
            try:
                self._autoscaling_v2_api = client.AutoscalingV2Api(executor._apps_v1_api.api_client)
            except Exception:
                self._autoscaling_v2_api = None

    def check_competing_hpa(self) -> Tuple[bool, Optional[str]]:
        """
        Inspects the namespace for any native HorizontalPodAutoscaler targeting this deployment.
        Returns (has_conflict, description).
        """
        if not AUTOSCALING_API_AVAILABLE or not self.executor._connected or not self._autoscaling_v2_api:
            return False, None

        try:
            hpas = self._autoscaling_v2_api.list_namespaced_horizontal_pod_autoscaler(
                namespace=self.executor.namespace,
                _request_timeout=1.5,
            )
            for hpa in hpas.items:
                target_ref = hpa.spec.scale_target_ref
                if (
                    target_ref.kind == "Deployment"
                    and target_ref.name == self.executor.deployment_name
                ):
                    return True, (
                        f"Conflict detected: Native HPA '{hpa.metadata.name}' is already targeting "
                        f"Deployment '{self.executor.deployment_name}'. Competing writes prohibited."
                    )
            return False, None
        except Exception as e:
            logger.debug("HPA check check skipped or failed: %s", e)
            return False, None

    def coordinate_and_execute(
        self,
        proposed_action: str,
        current_replicas: int,
        target_replicas: int,
        replica_delta: int,
    ) -> Tuple[GuardrailResult, ExecutionResult]:
        """
        Coordinates guardrail validation and delegates approved actions to Kubernetes executor.
        """
        # Step 1: Check competing ownership
        if self.enforce_exclusive_ownership:
            has_conflict, conflict_msg = self.check_competing_hpa()
            if has_conflict:
                logger.error("Ownership conflict: %s", conflict_msg)
                guardrail_res = GuardrailResult(
                    approved=False,
                    action="REJECTED",
                    original_target_replicas=target_replicas,
                    authorized_target_replicas=current_replicas,
                    replica_delta=0,
                    clamped=False,
                    rejection_reason=conflict_msg,
                    is_dry_run=self.guardrail_engine.dry_run,
                    authorization_note="Action rejected: Competing native HPA detected.",
                )
                exec_res = ExecutionResult(
                    success=False,
                    dry_run=self.guardrail_engine.dry_run,
                    initial_replicas=current_replicas,
                    target_replicas=current_replicas,
                    confirmed_replicas=current_replicas,
                    action_type="HOLD",
                    message="Execution aborted due to competing autoscaler ownership conflict.",
                    error=conflict_msg,
                )
                return guardrail_res, exec_res

        # Step 2: Validate against operational guardrails
        guardrail_result = self.guardrail_engine.validate_action(
            proposed_action=proposed_action,
            current_replicas=current_replicas,
            target_replicas=target_replicas,
            replica_delta=replica_delta,
        )

        if not guardrail_result.approved or guardrail_result.action in ("HOLD", "REJECTED"):
            # Guardrails withheld or rejected execution
            exec_result = ExecutionResult(
                success=True if guardrail_result.action == "HOLD" else False,
                dry_run=guardrail_result.is_dry_run,
                initial_replicas=current_replicas,
                target_replicas=guardrail_result.authorized_target_replicas,
                confirmed_replicas=current_replicas,
                action_type=guardrail_result.action,
                message=guardrail_result.authorization_note,
                error=guardrail_result.rejection_reason,
            )
            return guardrail_result, exec_result

        # Step 3: Route approved action to Kubernetes executor
        exec_result = self.executor.execute_scaling(
            action=proposed_action,
            target_replicas=guardrail_result.authorized_target_replicas,
            dry_run=guardrail_result.is_dry_run,
        )

        return guardrail_result, exec_result
