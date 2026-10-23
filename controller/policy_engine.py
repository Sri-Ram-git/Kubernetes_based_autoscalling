"""
Rule-based Policy Engine for Kubernetes Scaling Operations.
Project ID: 357 | Alliance University, Bengaluru

Strict requirement:
- Deterministic, explainable, configurable, and rule-based.
- NO MACHINE LEARNING, NO FORECASTING, NO PREDICTIVE MODELS, NO AI.
"""

from dataclasses import asdict, dataclass, field
import logging
import math
import operator
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import yaml

from controller.telemetry import MetricSample

logger = logging.getLogger("autoscaler.policy_engine")

SUPPORTED_OPERATORS: Dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": lambda a, b: math.isclose(a, b, abs_tol=1e-5),
    "!=": lambda a, b: not math.isclose(a, b, abs_tol=1e-5),
}

SUPPORTED_ACTIONS: Set[str] = {"SCALE_OUT", "SCALE_IN", "HOLD"}

SUPPORTED_METRICS: Set[str] = {
    "cpu_utilization_percent",
    "memory_utilization_percent",
    "http_requests_per_second",
}


@dataclass
class PolicyRule:
    """Represents a validated, declarative auto-scaling policy rule."""
    id: str
    name: str
    description: str
    enabled: bool
    priority: int
    metric: str
    operator_str: str
    threshold: float
    duration_seconds: float
    action: str  # "SCALE_OUT", "SCALE_IN", "HOLD"
    replica_delta: int
    cooldown_seconds: float = 60.0

    def evaluate_condition(self, value: float) -> bool:
        """
        Evaluates an observed metric value against policy operator and threshold.
        Uses strictly explicit comparison logic (e.g. 75.0 > 75.0 is False).
        """
        op_func = SUPPORTED_OPERATORS.get(self.operator_str)
        if not op_func:
            raise ValueError(f"Unsupported operator: {self.operator_str}")
        return op_func(value, self.threshold)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["operator"] = self.operator_str
        return d


@dataclass
class PolicyEvaluationResult:
    """Structured result of evaluating a policy rule against telemetry."""
    policy_id: str
    policy_name: str
    matched: bool
    evaluable: bool
    priority: int
    action: str
    replica_delta: int
    metric_name: str
    observed_value: Optional[float]
    threshold: float
    operator_str: str
    duration_met: bool
    reason: str
    cooldown_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["operator"] = self.operator_str
        return d


class PolicyValidationError(Exception):
    """Raised when policy configuration fails schema, semantic, or boundary validation."""
    pass


class PolicyEngine:
    """Loads, validates, and evaluates YAML-defined scaling policies."""

    def __init__(self, policy_file_path: Optional[str] = None):
        self.policy_file_path = policy_file_path
        self.rules: List[PolicyRule] = []
        self.target_workload: Dict[str, Any] = {}
        self.guardrails_config: Dict[str, Any] = {}
        self.fallback_config: Dict[str, Any] = {}
        self.conflict_resolution_config: Dict[str, Any] = {}

        # Tracking breach start times for duration persistence: {policy_id: start_timestamp}
        self._breach_timestamps: Dict[str, float] = {}

        # Cache of latest evaluation results for dashboard and audit
        self.latest_evaluations: List[PolicyEvaluationResult] = []

        if policy_file_path:
            self.load_from_yaml(policy_file_path)

    def load_from_yaml(self, file_path: str) -> None:
        """Loads and strictly validates policies from a YAML file."""
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Policy configuration file not found at: {file_path}")

        try:
            with open(p, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)
        except Exception as e:
            raise PolicyValidationError(f"Invalid YAML syntax in policy file: {e}") from e

        if not isinstance(raw_data, dict):
            raise PolicyValidationError("Policy configuration root must be a YAML dictionary")

        self.validate_and_parse(raw_data)
        self.policy_file_path = file_path
        logger.info("Successfully loaded %d policy rules from %s", len(self.rules), file_path)

    def validate_and_parse(self, data: Dict[str, Any]) -> None:
        """Validates configuration schema and parses PolicyRule objects."""
        if "policies" not in data or not isinstance(data["policies"], list):
            raise PolicyValidationError("Configuration missing required 'policies' list")

        if len(data["policies"]) == 0:
            raise PolicyValidationError("Policy configuration 'policies' list cannot be empty")

        self.target_workload = data.get("target_workload", {})
        self.guardrails_config = data.get("guardrails", {})
        self.fallback_config = data.get("fallback_behavior", {})
        self.conflict_resolution_config = data.get("conflict_resolution", {})

        parsed_rules: List[PolicyRule] = []
        seen_ids = set()

        for idx, item in enumerate(data["policies"]):
            if not isinstance(item, dict):
                raise PolicyValidationError(f"Policy at index {idx} must be a dictionary")

            p_id = item.get("id")
            if not p_id or not isinstance(p_id, str):
                raise PolicyValidationError(f"Policy at index {idx} missing valid 'id'")

            p_id_clean = p_id.strip()
            if not p_id_clean:
                raise PolicyValidationError(f"Policy at index {idx} has empty 'id'")

            if p_id_clean in seen_ids:
                raise PolicyValidationError(f"Duplicate policy ID detected: '{p_id_clean}'")
            seen_ids.add(p_id_clean)

            name = item.get("name", p_id_clean)
            desc = item.get("description", "")
            enabled = bool(item.get("enabled", True))

            priority = item.get("priority")
            if priority is None or not isinstance(priority, int) or isinstance(priority, bool):
                raise PolicyValidationError(f"Policy '{p_id_clean}' requires integer 'priority'")
            if priority <= 0:
                raise PolicyValidationError(f"Policy '{p_id_clean}' priority must be positive (got {priority})")

            metric = item.get("metric")
            if not metric or not isinstance(metric, str):
                raise PolicyValidationError(f"Policy '{p_id_clean}' requires 'metric' string")
            metric_clean = metric.strip()
            if metric_clean not in SUPPORTED_METRICS:
                raise PolicyValidationError(
                    f"Policy '{p_id_clean}' references unsupported metric '{metric_clean}'. "
                    f"Supported metrics: {sorted(list(SUPPORTED_METRICS))}"
                )

            op = item.get("operator")
            if op not in SUPPORTED_OPERATORS:
                raise PolicyValidationError(
                    f"Policy '{p_id_clean}' has invalid operator '{op}'. Supported: {sorted(list(SUPPORTED_OPERATORS.keys()))}"
                )

            threshold = item.get("threshold")
            if threshold is None or not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
                raise PolicyValidationError(f"Policy '{p_id_clean}' requires numeric 'threshold'")
            threshold_val = float(threshold)
            if not math.isfinite(threshold_val):
                raise PolicyValidationError(f"Policy '{p_id_clean}' threshold must be finite (got {threshold})")

            # Validate range bounds for known percentage metrics
            if metric_clean.endswith("_percent") and (threshold_val < 0.0 or threshold_val > 100.0):
                raise PolicyValidationError(
                    f"Policy '{p_id_clean}': percentage metric '{metric_clean}' threshold must be in range [0, 100] (got {threshold_val})"
                )
            if threshold_val < 0.0:
                raise PolicyValidationError(f"Policy '{p_id_clean}': threshold cannot be negative (got {threshold_val})")

            duration = item.get("duration_seconds", 0.0)
            if not isinstance(duration, (int, float)) or isinstance(duration, bool):
                raise PolicyValidationError(f"Policy '{p_id_clean}' duration_seconds must be numeric")
            duration_val = float(duration)
            if duration_val < 0.0 or not math.isfinite(duration_val):
                raise PolicyValidationError(f"Policy '{p_id_clean}' duration_seconds must be >= 0")

            action = item.get("action")
            if action not in SUPPORTED_ACTIONS:
                raise PolicyValidationError(
                    f"Policy '{p_id_clean}' action must be SCALE_OUT, SCALE_IN, or HOLD (got '{action}')"
                )

            replica_delta = item.get("replica_delta")
            if replica_delta is None or not isinstance(replica_delta, int) or isinstance(replica_delta, bool):
                raise PolicyValidationError(f"Policy '{p_id_clean}' requires integer 'replica_delta'")

            if action == "SCALE_OUT" and replica_delta <= 0:
                raise PolicyValidationError(f"Policy '{p_id_clean}': SCALE_OUT must have positive replica_delta (got {replica_delta})")
            if action == "SCALE_IN" and replica_delta >= 0:
                raise PolicyValidationError(f"Policy '{p_id_clean}': SCALE_IN must have negative replica_delta (got {replica_delta})")
            if action == "HOLD" and replica_delta != 0:
                raise PolicyValidationError(f"Policy '{p_id_clean}': HOLD must have replica_delta == 0 (got {replica_delta})")

            cooldown = item.get("cooldown_seconds", 60.0)
            if not isinstance(cooldown, (int, float)) or isinstance(cooldown, bool):
                raise PolicyValidationError(f"Policy '{p_id_clean}' cooldown_seconds must be numeric")
            cooldown_val = float(cooldown)
            if cooldown_val < 0.0 or not math.isfinite(cooldown_val):
                raise PolicyValidationError(f"Policy '{p_id_clean}' cooldown_seconds must be >= 0")

            parsed_rules.append(
                PolicyRule(
                    id=p_id_clean,
                    name=name,
                    description=desc,
                    enabled=enabled,
                    priority=priority,
                    metric=metric_clean,
                    operator_str=op,
                    threshold=threshold_val,
                    duration_seconds=duration_val,
                    action=action,
                    replica_delta=replica_delta,
                    cooldown_seconds=cooldown_val,
                )
            )

        self.rules = parsed_rules

    def evaluate(
        self,
        metrics: Dict[str, MetricSample],
        workload: Optional[Any] = None,
        now: Optional[float] = None,
    ) -> List[PolicyEvaluationResult]:
        """
        Evaluates all enabled rules against current validated telemetry and workload context.
        Returns a complete, deterministic list of PolicyEvaluationResult objects.

        Guarantees:
        - Evaluates rules independently.
        - Does NOT suppress lower-priority matching rules (PRAH decision controller owns arbitration).
        - Explicit comparison logic: values exactly on the boundary do not match strict inequalities (> or <).
        - Telemetry failure states (MISSING, STALE, INVALID, ERROR, UNAVAILABLE) are reported cleanly without fabricating zero.
        - Outputs identical structured results for identical inputs.
        """
        current_time = now or time.time()
        results: List[PolicyEvaluationResult] = []

        for rule in self.rules:
            if not rule.enabled:
                continue

            sample = metrics.get(rule.metric)

            # Failure / Unusable Telemetry Handling
            if sample is None or not sample.is_usable():
                # Reset persistence timer on degraded telemetry
                self._breach_timestamps.pop(rule.id, None)
                status_str = sample.status.value if sample else "MISSING"
                error_detail = sample.error_message if (sample and sample.error_message) else "no telemetry sample available"
                reason_msg = f"Cannot evaluate policy: metric '{rule.metric}' is {status_str} ({error_detail})"
                results.append(
                    PolicyEvaluationResult(
                        policy_id=rule.id,
                        policy_name=rule.name,
                        matched=False,
                        evaluable=False,
                        priority=rule.priority,
                        action="HOLD",
                        replica_delta=0,
                        metric_name=rule.metric,
                        observed_value=sample.value if (sample and sample.value is not None) else None,
                        threshold=rule.threshold,
                        operator_str=rule.operator_str,
                        duration_met=False,
                        reason=reason_msg,
                        cooldown_seconds=rule.cooldown_seconds,
                    )
                )
                continue

            # Evaluate mathematical rule condition
            val = float(sample.value)  # safe because is_usable guarantees finite numeric
            condition_met = rule.evaluate_condition(val)

            if not condition_met:
                # Reset persistence timer
                self._breach_timestamps.pop(rule.id, None)
                results.append(
                    PolicyEvaluationResult(
                        policy_id=rule.id,
                        policy_name=rule.name,
                        matched=False,
                        evaluable=True,
                        priority=rule.priority,
                        action="HOLD",
                        replica_delta=0,
                        metric_name=rule.metric,
                        observed_value=val,
                        threshold=rule.threshold,
                        operator_str=rule.operator_str,
                        duration_met=False,
                        reason=f"Observed {rule.metric} ({val:.2f}) does not satisfy condition '{rule.operator_str} {rule.threshold:.2f}'",
                        cooldown_seconds=rule.cooldown_seconds,
                    )
                )
                continue

            # Condition satisfied: check duration persistence
            if rule.id not in self._breach_timestamps:
                self._breach_timestamps[rule.id] = current_time

            elapsed = current_time - self._breach_timestamps[rule.id]
            duration_met = elapsed >= rule.duration_seconds

            if not duration_met:
                remaining = max(0.0, rule.duration_seconds - elapsed)
                results.append(
                    PolicyEvaluationResult(
                        policy_id=rule.id,
                        policy_name=rule.name,
                        matched=False,
                        evaluable=True,
                        priority=rule.priority,
                        action="HOLD",
                        replica_delta=0,
                        metric_name=rule.metric,
                        observed_value=val,
                        threshold=rule.threshold,
                        operator_str=rule.operator_str,
                        duration_met=False,
                        reason=f"Condition breached for {elapsed:.1f}s, requires sustained {rule.duration_seconds:.1f}s ({remaining:.1f}s remaining)",
                        cooldown_seconds=rule.cooldown_seconds,
                    )
                )
            else:
                results.append(
                    PolicyEvaluationResult(
                        policy_id=rule.id,
                        policy_name=rule.name,
                        matched=True,
                        evaluable=True,
                        priority=rule.priority,
                        action=rule.action,
                        replica_delta=rule.replica_delta,
                        metric_name=rule.metric,
                        observed_value=val,
                        threshold=rule.threshold,
                        operator_str=rule.operator_str,
                        duration_met=True,
                        reason=f"Condition '{rule.metric} ({val:.2f}) {rule.operator_str} {rule.threshold:.2f}' sustained for {elapsed:.1f}s >= {rule.duration_seconds:.1f}s",
                        cooldown_seconds=rule.cooldown_seconds,
                    )
                )

        self.latest_evaluations = results
        return results

    def get_rules_summary(self) -> List[Dict[str, Any]]:
        """Returns structured metadata of all active policies for API serialization."""
        return [r.to_dict() for r in self.rules]
