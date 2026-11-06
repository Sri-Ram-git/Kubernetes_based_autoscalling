"""
Capacity Validator Module for Kubernetes Auto-Scaling Framework (Project 357).
Alliance University, Bengaluru.

Provides lightweight, explainable pre-scaling capacity validation using
actual Kubernetes API data:
- Node allocatable CPU and memory
- Existing committed pod resource requests (across all active pods on each node)
- Target pod resource requests from the Deployment pod template
- Node readiness, schedulability (cordon check), and placement constraints (taints/tolerations)

Evaluates eligible nodes individually to determine whether cluster capacity is sufficient
before authorizing scale-out operations.

Possible outcomes:
- CAPACITY_SUFFICIENT: Eligible node(s) have adequate unreserved CPU and memory to host the additional replica(s).
- INSUFFICIENT_CPU: No eligible node has enough unreserved allocatable CPU for the requested replica(s).
- INSUFFICIENT_MEMORY: No eligible node has enough unreserved allocatable memory for the requested replica(s).
- NO_ELIGIBLE_NODE: No nodes in the cluster are Ready, schedulable, and match placement constraints.
- CAPACITY_UNKNOWN: Kubernetes cluster API is offline or unqueriable; capacity cannot be determined.

Authoritative principle:
This pre-check uses committed resource requests vs allocatable capacity to prevent scheduling
deadlocks. It does NOT confuse current pod CPU/memory utilization with scheduling capacity.
The Kubernetes scheduler remains the final authoritative placement engine.
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("autoscaler.capacity_validator")

try:
    from kubernetes import client
    from kubernetes.client.rest import ApiException
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False


class CapacityOutcome(str, Enum):
    CAPACITY_SUFFICIENT = "CAPACITY_SUFFICIENT"
    INSUFFICIENT_CPU = "INSUFFICIENT_CPU"
    INSUFFICIENT_MEMORY = "INSUFFICIENT_MEMORY"
    NO_ELIGIBLE_NODE = "NO_ELIGIBLE_NODE"
    CAPACITY_UNKNOWN = "CAPACITY_UNKNOWN"


def parse_cpu_millicores(cpu_val: Any) -> int:
    """
    Parses a Kubernetes CPU resource quantity into integer millicores (m).
    Examples:
        '100m' -> 100
        '0.5'  -> 500
        '2'    -> 2000
        2      -> 2000
    """
    if cpu_val is None:
        return 0
    s = str(cpu_val).strip()
    if not s:
        return 0
    if s.endswith("m"):
        try:
            return int(float(s[:-1]))
        except ValueError:
            return 0
    try:
        return int(float(s) * 1000)
    except ValueError:
        logger.debug("Unparseable CPU value: %s", cpu_val)
        return 0


def parse_memory_bytes(mem_val: Any) -> int:
    """
    Parses a Kubernetes Memory resource quantity into integer bytes.
    Supports binary SI suffixes (Ki, Mi, Gi, Ti, Pi, Ei) and decimal suffixes (k, M, G, T, P, E).
    Examples:
        '128Mi' -> 134217728
        '1Gi'   -> 1073741824
        '7990476Ki' -> 8182247424
        '500M'  -> 500000000
    """
    if mem_val is None:
        return 0
    s = str(mem_val).strip()
    if not s:
        return 0

    binary_multipliers = {
        "Ki": 1024,
        "Mi": 1024 ** 2,
        "Gi": 1024 ** 3,
        "Ti": 1024 ** 4,
        "Pi": 1024 ** 5,
        "Ei": 1024 ** 6,
    }
    for suffix, mult in binary_multipliers.items():
        if s.endswith(suffix):
            try:
                return int(float(s[:-len(suffix)]) * mult)
            except ValueError:
                return 0

    decimal_multipliers = {
        "k": 1000,
        "K": 1000,
        "M": 1000 ** 2,
        "G": 1000 ** 3,
        "T": 1000 ** 4,
        "P": 1000 ** 5,
        "E": 1000 ** 6,
    }
    for suffix, mult in decimal_multipliers.items():
        if s.endswith(suffix):
            try:
                return int(float(s[:-len(suffix)]) * mult)
            except ValueError:
                return 0

    # Plain integer byte string
    try:
        return int(float(s))
    except ValueError:
        logger.debug("Unparseable memory value: %s", mem_val)
        return 0


@dataclass
class NodeCapacityReport:
    node_name: str
    is_ready: bool
    is_schedulable: bool
    matches_taints: bool
    allocatable_cpu_m: int
    allocatable_memory_bytes: int
    requested_cpu_m: int
    requested_memory_bytes: int
    available_cpu_m: int
    available_memory_bytes: int
    active_pods_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_name": self.node_name,
            "is_ready": self.is_ready,
            "is_schedulable": self.is_schedulable,
            "matches_taints": self.matches_taints,
            "allocatable_cpu_m": self.allocatable_cpu_m,
            "allocatable_memory_bytes": self.allocatable_memory_bytes,
            "allocatable_memory_human": f"{round(self.allocatable_memory_bytes / (1024**2), 1)} MiB",
            "requested_cpu_m": self.requested_cpu_m,
            "requested_memory_bytes": self.requested_memory_bytes,
            "requested_memory_human": f"{round(self.requested_memory_bytes / (1024**2), 1)} MiB",
            "available_cpu_m": self.available_cpu_m,
            "available_memory_bytes": self.available_memory_bytes,
            "available_memory_human": f"{round(self.available_memory_bytes / (1024**2), 1)} MiB",
            "active_pods_count": self.active_pods_count,
        }


@dataclass
class CapacityValidationResult:
    outcome: CapacityOutcome
    is_sufficient: bool
    requested_replicas_delta: int
    pod_cpu_m: int
    pod_memory_bytes: int
    total_additional_cpu_m: int
    total_additional_memory_bytes: int
    message: str
    evaluated_nodes: List[NodeCapacityReport] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    disclaimer: str = (
        "Pre-scaling capacity check based on Kubernetes node allocatable resource requests. "
        "The authoritative placement decision is made solely by the Kubernetes scheduler at pod creation time."
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "is_sufficient": self.is_sufficient,
            "requested_replicas_delta": self.requested_replicas_delta,
            "pod_cpu_m": self.pod_cpu_m,
            "pod_memory_bytes": self.pod_memory_bytes,
            "pod_memory_human": f"{round(self.pod_memory_bytes / (1024**2), 1)} MiB",
            "total_additional_cpu_m": self.total_additional_cpu_m,
            "total_additional_memory_bytes": self.total_additional_memory_bytes,
            "total_additional_memory_human": f"{round(self.total_additional_memory_bytes / (1024**2), 1)} MiB",
            "message": self.message,
            "evaluated_nodes": [n.to_dict() for n in self.evaluated_nodes],
            "timestamp": self.timestamp,
            "disclaimer": self.disclaimer,
        }


class CapacityValidator:
    """
    Evaluates cluster scheduling capacity before allowing scale-out actions.
    Uses CoreV1Api and AppsV1Api to verify node allocatable capacity and existing pod requests.
    """

    def __init__(
        self,
        core_v1_api: Optional[Any] = None,
        apps_v1_api: Optional[Any] = None,
        namespace: str = "autoscaling-demo",
        deployment_name: str = "sample-web-app",
    ):
        self.core_v1_api = core_v1_api
        self.apps_v1_api = apps_v1_api
        self.namespace = namespace
        self.deployment_name = deployment_name

    def get_target_pod_requests(self) -> Tuple[int, int]:
        """
        Retrieves per-pod CPU (millicores) and Memory (bytes) requests from the Deployment pod template.
        Falls back to safe defaults (100m CPU, 128Mi Memory) if unspecified or unreadable.
        """
        default_cpu_m = 100
        default_mem_bytes = 128 * 1024 * 1024  # 128 MiB

        if not self.apps_v1_api:
            return default_cpu_m, default_mem_bytes

        try:
            dep = self.apps_v1_api.read_namespaced_deployment(
                name=self.deployment_name,
                namespace=self.namespace,
                _request_timeout=2.0,
            )
            containers = dep.spec.template.spec.containers or []
            total_cpu = 0
            total_mem = 0
            for c in containers:
                reqs = c.resources.requests or {} if c.resources else {}
                total_cpu += parse_cpu_millicores(reqs.get("cpu"))
                total_mem += parse_memory_bytes(reqs.get("memory"))

            cpu_m = total_cpu if total_cpu > 0 else default_cpu_m
            mem_b = total_mem if total_mem > 0 else default_mem_bytes
            return cpu_m, mem_b
        except Exception as e:
            logger.debug("Could not read deployment pod template requests: %s. Using defaults.", e)
            return default_cpu_m, default_mem_bytes

    def get_pod_tolerations(self) -> List[Any]:
        """Retrieves tolerations defined in the target Deployment template."""
        if not self.apps_v1_api:
            return []
        try:
            dep = self.apps_v1_api.read_namespaced_deployment(
                name=self.deployment_name,
                namespace=self.namespace,
                _request_timeout=2.0,
            )
            return dep.spec.template.spec.tolerations or []
        except Exception:
            return []

    def check_node_taint_match(self, node: Any, tolerations: List[Any]) -> bool:
        """
        Validates if target pod tolerations satisfy node taints.
        Nodes with untolerated NoSchedule or NoExecute taints cannot schedule the workload.
        """
        taints = node.spec.taints or []
        if not taints:
            return True

        for taint in taints:
            if taint.effect not in ("NoSchedule", "NoExecute"):
                continue

            tolerated = False
            for tol in tolerations:
                # Operator 'Exists' matches key regardless of value
                if tol.operator == "Exists":
                    if not tol.key or tol.key == taint.key:
                        if not tol.effect or tol.effect == taint.effect:
                            tolerated = True
                            break
                # Default 'Equal' operator matches key and value
                elif tol.key == taint.key and tol.value == taint.value:
                    if not tol.effect or tol.effect == taint.effect:
                        tolerated = True
                        break

            if not tolerated:
                return False

        return True

    def evaluate_node_capacity(self, node: Any, tolerations: List[Any]) -> NodeCapacityReport:
        """
        Inspects an individual node: allocatable capacity minus sum of all active pod requests.
        """
        node_name = node.metadata.name

        # 1. Schedulability (cordon check)
        is_schedulable = not getattr(node.spec, "unschedulable", False)

        # 2. Readiness check
        is_ready = False
        if node.status.conditions:
            for cond in node.status.conditions:
                if cond.type == "Ready" and cond.status == "True":
                    is_ready = True
                    break

        # 3. Taint toleration check
        matches_taints = self.check_node_taint_match(node, tolerations)

        # 4. Allocatable resources
        allocatable = node.status.allocatable or {}
        alloc_cpu_m = parse_cpu_millicores(allocatable.get("cpu", "0"))
        alloc_mem_b = parse_memory_bytes(allocatable.get("memory", "0"))

        # 5. Query active committed pod requests on this node
        req_cpu_m = 0
        req_mem_b = 0
        active_pods_count = 0

        if self.core_v1_api:
            try:
                pods_resp = self.core_v1_api.list_pod_for_all_namespaces(
                    field_selector=f"spec.nodeName={node_name}",
                    _request_timeout=3.0,
                )
                for pod in pods_resp.items:
                    # Skip terminated pods (Succeeded or Failed)
                    if pod.status and pod.status.phase in ("Succeeded", "Failed"):
                        continue

                    active_pods_count += 1
                    containers = pod.spec.containers or []
                    for c in containers:
                        if c.resources and c.resources.requests:
                            req_cpu_m += parse_cpu_millicores(c.resources.requests.get("cpu"))
                            req_mem_b += parse_memory_bytes(c.resources.requests.get("memory"))

            except Exception as e:
                logger.warning("Failed to list pods on node %s for capacity calculation: %s", node_name, e)

        available_cpu_m = max(0, alloc_cpu_m - req_cpu_m)
        available_mem_b = max(0, alloc_mem_b - req_mem_b)

        return NodeCapacityReport(
            node_name=node_name,
            is_ready=is_ready,
            is_schedulable=is_schedulable,
            matches_taints=matches_taints,
            allocatable_cpu_m=alloc_cpu_m,
            allocatable_memory_bytes=alloc_mem_b,
            requested_cpu_m=req_cpu_m,
            requested_memory_bytes=req_mem_b,
            available_cpu_m=available_cpu_m,
            available_memory_bytes=available_mem_b,
            active_pods_count=active_pods_count,
        )

    def validate_scale_out(self, delta: int) -> CapacityValidationResult:
        """
        Validates whether the cluster has sufficient unreserved capacity to place `delta` additional pods.
        Evaluates eligible nodes individually and simulates placement across them.
        """
        pod_cpu_m, pod_mem_b = self.get_target_pod_requests()
        total_needed_cpu = delta * pod_cpu_m
        total_needed_mem = delta * pod_mem_b

        if delta <= 0:
            return CapacityValidationResult(
                outcome=CapacityOutcome.CAPACITY_SUFFICIENT,
                is_sufficient=True,
                requested_replicas_delta=delta,
                pod_cpu_m=pod_cpu_m,
                pod_memory_bytes=pod_mem_b,
                total_additional_cpu_m=0,
                total_additional_memory_bytes=0,
                message="Non-positive replica delta; no additional capacity required.",
            )

        if not self.core_v1_api:
            return CapacityValidationResult(
                outcome=CapacityOutcome.CAPACITY_UNKNOWN,
                is_sufficient=False,
                requested_replicas_delta=delta,
                pod_cpu_m=pod_cpu_m,
                pod_memory_bytes=pod_mem_b,
                total_additional_cpu_m=total_needed_cpu,
                total_additional_memory_bytes=total_needed_mem,
                message="CoreV1Api unavailable; cluster capacity could not be verified.",
            )

        try:
            nodes_resp = self.core_v1_api.list_node(_request_timeout=2.5)
            nodes = nodes_resp.items or []
        except Exception as e:
            logger.warning("Failed to query nodes for capacity validation: %s", e)
            return CapacityValidationResult(
                outcome=CapacityOutcome.CAPACITY_UNKNOWN,
                is_sufficient=False,
                requested_replicas_delta=delta,
                pod_cpu_m=pod_cpu_m,
                pod_memory_bytes=pod_mem_b,
                total_additional_cpu_m=total_needed_cpu,
                total_additional_memory_bytes=total_needed_mem,
                message=f"Kubernetes node list query failed: {str(e)[:80]}",
            )

        if not nodes:
            return CapacityValidationResult(
                outcome=CapacityOutcome.NO_ELIGIBLE_NODE,
                is_sufficient=False,
                requested_replicas_delta=delta,
                pod_cpu_m=pod_cpu_m,
                pod_memory_bytes=pod_mem_b,
                total_additional_cpu_m=total_needed_cpu,
                total_additional_memory_bytes=total_needed_mem,
                message="No nodes detected in the Kubernetes cluster.",
            )

        tolerations = self.get_pod_tolerations()
        node_reports: List[NodeCapacityReport] = []

        for node in nodes:
            report = self.evaluate_node_capacity(node, tolerations)
            node_reports.append(report)

        # Filter strictly eligible nodes
        eligible_nodes = [
            r for r in node_reports
            if r.is_ready and r.is_schedulable and r.matches_taints
        ]

        if not eligible_nodes:
            reasons = []
            for r in node_reports:
                flags = []
                if not r.is_ready:
                    flags.append("NotReady")
                if not r.is_schedulable:
                    flags.append("Cordoned/Unschedulable")
                if not r.matches_taints:
                    flags.append("UntoleratedTaints")
                reasons.append(f"{r.node_name}: {','.join(flags)}")

            return CapacityValidationResult(
                outcome=CapacityOutcome.NO_ELIGIBLE_NODE,
                is_sufficient=False,
                requested_replicas_delta=delta,
                pod_cpu_m=pod_cpu_m,
                pod_memory_bytes=pod_mem_b,
                total_additional_cpu_m=total_needed_cpu,
                total_additional_memory_bytes=total_needed_mem,
                message=f"No eligible nodes available for pod placement ({'; '.join(reasons)}).",
                evaluated_nodes=node_reports,
            )

        # Simulate greedy bin-packing of `delta` pods across eligible nodes
        # Each pod needs `pod_cpu_m` and `pod_mem_b` on the same node
        simulated_available_cpu = {r.node_name: r.available_cpu_m for r in eligible_nodes}
        simulated_available_mem = {r.node_name: r.available_memory_bytes for r in eligible_nodes}

        placed_pods = 0
        cpu_exhausted = False
        mem_exhausted = False

        for _ in range(delta):
            placed = False
            # Try to place on the eligible node with the most available CPU
            sorted_nodes = sorted(
                eligible_nodes,
                key=lambda r: simulated_available_cpu[r.node_name],
                reverse=True,
            )
            for node_rep in sorted_nodes:
                n_name = node_rep.node_name
                avail_cpu = simulated_available_cpu[n_name]
                avail_mem = simulated_available_mem[n_name]

                if avail_cpu >= pod_cpu_m and avail_mem >= pod_mem_b:
                    simulated_available_cpu[n_name] -= pod_cpu_m
                    simulated_available_mem[n_name] -= pod_mem_b
                    placed = True
                    placed_pods += 1
                    break
                elif avail_cpu < pod_cpu_m:
                    cpu_exhausted = True
                elif avail_mem < pod_mem_b:
                    mem_exhausted = True

            if not placed:
                break

        if placed_pods == delta:
            summary = ", ".join(
                f"{r.node_name} ({simulated_available_cpu[r.node_name]}m CPU, {round(simulated_available_mem[r.node_name]/(1024**2), 1)} MiB mem remaining)"
                for r in eligible_nodes
            )
            return CapacityValidationResult(
                outcome=CapacityOutcome.CAPACITY_SUFFICIENT,
                is_sufficient=True,
                requested_replicas_delta=delta,
                pod_cpu_m=pod_cpu_m,
                pod_memory_bytes=pod_mem_b,
                total_additional_cpu_m=total_needed_cpu,
                total_additional_memory_bytes=total_needed_mem,
                message=f"Sufficient capacity on {len(eligible_nodes)} node(s) for +{delta} pod(s). {summary}",
                evaluated_nodes=node_reports,
            )

        # If placement failed, classify exact cause
        if cpu_exhausted and not mem_exhausted:
            outcome = CapacityOutcome.INSUFFICIENT_CPU
            reason = f"Insufficient CPU capacity on eligible nodes for +{delta} pod(s) (requires {total_needed_cpu}m total, {pod_cpu_m}m per pod)."
        elif mem_exhausted and not cpu_exhausted:
            outcome = CapacityOutcome.INSUFFICIENT_MEMORY
            reason = f"Insufficient memory capacity on eligible nodes for +{delta} pod(s) (requires {round(total_needed_mem/(1024**2), 1)} MiB total, {round(pod_mem_b/(1024**2), 1)} MiB per pod)."
        else:
            outcome = CapacityOutcome.INSUFFICIENT_CPU
            reason = f"Insufficient combined CPU and memory capacity to place {delta} additional pod(s)."

        return CapacityValidationResult(
            outcome=outcome,
            is_sufficient=False,
            requested_replicas_delta=delta,
            pod_cpu_m=pod_cpu_m,
            pod_memory_bytes=pod_mem_b,
            total_additional_cpu_m=total_needed_cpu,
            total_additional_memory_bytes=total_needed_mem,
            message=reason,
            evaluated_nodes=node_reports,
        )
