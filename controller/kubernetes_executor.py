"""
Kubernetes API Executor and Workload State Verifier.
Project ID: 357 | Alliance University, Bengaluru

Strict requirement:
- Never report an action as successful before confirming the relevant API response and observed state.
- Supports safe dry-run (preview) mode.
- Direct Deployment scaling ownership (avoids competing with native HPA).
- Handles API errors, authorization failures, and timeouts gracefully.
"""

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("autoscaler.k8s_executor")

# Optional kubernetes client import with fallback mock support
try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    K8S_CLIENT_AVAILABLE = True
except ImportError:
    K8S_CLIENT_AVAILABLE = False
    client = None  # type: ignore
    config = None  # type: ignore
    ApiException = Exception  # type: ignore

from controller.capacity_validator import CapacityValidator


@dataclass
class WorkloadState:
    namespace: str
    name: str
    desired_replicas: int
    current_replicas: int
    ready_replicas: int
    available_replicas: int
    unavailable_replicas: int
    connected: bool
    status_message: str
    pods: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionResult:
    success: bool
    dry_run: bool
    initial_replicas: int
    target_replicas: int
    confirmed_replicas: Optional[int]
    action_type: str
    message: str
    error: Optional[str] = None
    execution_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KubernetesExecutor:
    """Manages Kubernetes API communication, deployment querying, scaling, and state verification."""

    def __init__(
        self,
        namespace: str = "autoscaling-demo",
        deployment_name: str = "sample-web-app",
        kubeconfig_path: Optional[str] = None,
        verification_timeout_seconds: float = 15.0,
    ):
        self.namespace = namespace
        self.deployment_name = deployment_name
        self.kubeconfig_path = kubeconfig_path
        self.verification_timeout_seconds = verification_timeout_seconds

        self._apps_v1_api = None
        self._core_v1_api = None
        self._connected = False
        self._connection_error: Optional[str] = None
        self._simulated_replicas = 2  # Used when running without live cluster

        self.capacity_validator = CapacityValidator(
            core_v1_api=self._core_v1_api,
            apps_v1_api=self._apps_v1_api,
            namespace=self.namespace,
            deployment_name=self.deployment_name,
        )

        self._initialize_client()

    def _sync_capacity_validator(self) -> None:
        """Keeps capacity validator references aligned with active cluster clients."""
        if hasattr(self, "capacity_validator") and self.capacity_validator:
            self.capacity_validator.core_v1_api = self._core_v1_api
            self.capacity_validator.apps_v1_api = self._apps_v1_api
            self.capacity_validator.namespace = self.namespace
            self.capacity_validator.deployment_name = self.deployment_name

    def _initialize_client(self) -> None:
        """Initializes Kubernetes client from in-cluster config or kubeconfig."""
        if not K8S_CLIENT_AVAILABLE:
            self._connected = False
            self._connection_error = "kubernetes Python package is not installed."
            logger.warning("Kubernetes package unavailable: %s", self._connection_error)
            return

        try:
            # Try in-cluster configuration first (when running as pod)
            try:
                if hasattr(config, "load_incluster_config"):
                    config.load_incluster_config()
                elif hasattr(config, "load_in_cluster_config"):
                    config.load_in_cluster_config()
                self._apps_v1_api = client.AppsV1Api()
                self._core_v1_api = client.CoreV1Api()
                self._connected = True
                self._connection_error = None
                self._sync_capacity_validator()
                logger.info("Initialized Kubernetes client using in-cluster configuration.")
                return
            except config.ConfigException:
                pass

            # Try local kubeconfig
            config.load_kube_config(config_file=self.kubeconfig_path)
            k8s_conf = client.Configuration.get_default_copy()
            # Set short connection timeout so offline local clusters fail fast and gracefully
            k8s_conf.retries = 0
            k8s_conf.connection_pool_maxsize = 4
            api_client = client.ApiClient(k8s_conf)
            self._apps_v1_api = client.AppsV1Api(api_client)
            self._core_v1_api = client.CoreV1Api(api_client)
            self._connected = True
            self._connection_error = None
            self._sync_capacity_validator()
            logger.info("Initialized Kubernetes client using local kubeconfig.")

        except Exception as e:
            self._apps_v1_api = None
            self._core_v1_api = None
            self._connected = False
            self._connection_error = f"Kubernetes initialization error: {str(e)}"
            self._sync_capacity_validator()
            logger.warning("Failed to initialize Kubernetes API client: %s", self._connection_error)

    def is_connected(self) -> Tuple[bool, str]:
        """Returns connection status and description with auto-recovery."""
        if not K8S_CLIENT_AVAILABLE:
            return False, "kubernetes Python package is not installed."

        if self._apps_v1_api is None:
            self._initialize_client()
            if self._apps_v1_api is None:
                return False, self._connection_error or "Kubernetes client not connected."

        try:
            # Perform a lightweight fast check with short timeout
            self._apps_v1_api.get_api_resources(_request_timeout=2.0)
            self._connected = True
            self._connection_error = None
            return True, "Kubernetes API reachable."
        except Exception as e:
            # Attempt to re-initialize once in case kubeconfig server port was updated (e.g. Minikube restart)
            try:
                self._initialize_client()
                if self._apps_v1_api:
                    self._apps_v1_api.get_api_resources(_request_timeout=2.0)
                    self._connected = True
                    self._connection_error = None
                    return True, "Kubernetes API reachable."
            except Exception:
                pass

            self._connected = False
            self._connection_error = f"Kubernetes cluster unreachable ({str(e)[:80]}...)"
            return False, self._connection_error

    def get_workload_state(self) -> WorkloadState:
        """Reads current deployment state and pod readiness from Kubernetes cluster."""
        if not self._connected or not self._apps_v1_api:
            # Fallback to simulated workload state for testing/demo
            return WorkloadState(
                namespace=self.namespace,
                name=self.deployment_name,
                desired_replicas=self._simulated_replicas,
                current_replicas=self._simulated_replicas,
                ready_replicas=self._simulated_replicas,
                available_replicas=self._simulated_replicas,
                unavailable_replicas=0,
                connected=False,
                status_message=f"Cluster offline. Displaying local simulated state: {self._connection_error or 'Simulated'}",
                pods=[],
            )

        try:
            dep = self._apps_v1_api.read_namespaced_deployment(
                name=self.deployment_name,
                namespace=self.namespace,
                _request_timeout=1.5,
            )
            spec_replicas = dep.spec.replicas or 1
            status_replicas = dep.status.replicas or spec_replicas
            ready_replicas = dep.status.ready_replicas or 0
            available_replicas = dep.status.available_replicas or 0
            unavailable_replicas = dep.status.unavailable_replicas or max(0, spec_replicas - ready_replicas)

            # Query individual pod readiness if core API is available
            pod_list = []
            if self._core_v1_api:
                try:
                    pods_resp = self._core_v1_api.list_namespaced_pod(
                        namespace=self.namespace,
                        label_selector=f"app={self.deployment_name}",
                        _request_timeout=1.5,
                    )
                    for p in pods_resp.items:
                        # Exclude terminating pods marked for deletion
                        if p.metadata.deletion_timestamp is not None:
                            continue

                        is_ready = False
                        if p.status.conditions:
                            for cond in p.status.conditions:
                                if cond.type == "Ready" and cond.status == "True":
                                    is_ready = True
                                    break
                        restart_count = 0
                        if p.status.container_statuses:
                            restart_count = sum(c.restart_count for c in p.status.container_statuses)

                        pod_list.append({
                            "name": p.metadata.name,
                            "phase": p.status.phase,
                            "ready": is_ready,
                            "restarts": restart_count,
                            "node": p.spec.node_name,
                        })
                except Exception as e:
                    logger.debug("Pod list query skipped or failed: %s", e)

            return WorkloadState(
                namespace=self.namespace,
                name=self.deployment_name,
                desired_replicas=spec_replicas,
                current_replicas=status_replicas,
                ready_replicas=ready_replicas,
                available_replicas=available_replicas,
                unavailable_replicas=unavailable_replicas,
                connected=True,
                status_message="Healthy - Connected to Kubernetes cluster",
                pods=pod_list,
            )
        except ApiException as e:
            if e.status == 404:
                msg = f"Deployment '{self.deployment_name}' not found in namespace '{self.namespace}'"
            else:
                msg = f"Kubernetes API error (HTTP {e.status}): {e.reason}"
            logger.error("Failed to read deployment %s: %s", self.deployment_name, msg)
            return WorkloadState(
                namespace=self.namespace,
                name=self.deployment_name,
                desired_replicas=self._simulated_replicas,
                current_replicas=self._simulated_replicas,
                ready_replicas=0,
                available_replicas=0,
                unavailable_replicas=self._simulated_replicas,
                connected=False,
                status_message=msg,
                pods=[],
            )
        except Exception as e:
            self._connected = False
            msg = f"Cluster connection offline: {str(e)[:80]}..."
            logger.debug(msg)
            return WorkloadState(
                namespace=self.namespace,
                name=self.deployment_name,
                desired_replicas=self._simulated_replicas,
                current_replicas=self._simulated_replicas,
                ready_replicas=0,
                available_replicas=0,
                unavailable_replicas=self._simulated_replicas,
                connected=False,
                status_message=msg,
                pods=[],
            )

    def execute_scaling(
        self,
        action: str,
        target_replicas: int,
        dry_run: bool = True,
    ) -> ExecutionResult:
        """
        Executes scaling action with full verification.
        In dry-run mode: verifies intent and returns preview without mutation.
        In live mode: updates scale subresource, polls Kubernetes API to verify, returns result.
        """
        start_time = time.time()
        initial_state = self.get_workload_state()
        initial_replicas = initial_state.desired_replicas

        if action == "HOLD" or target_replicas == initial_replicas:
            return ExecutionResult(
                success=True,
                dry_run=dry_run,
                initial_replicas=initial_replicas,
                target_replicas=target_replicas,
                confirmed_replicas=initial_replicas,
                action_type="HOLD",
                message="No-op scaling: target replicas match current count.",
                execution_duration_ms=(time.time() - start_time) * 1000,
            )

        # 1. Dry Run Preview Mode
        if dry_run:
            logger.info(
                "[DRY-RUN] Simulating scaling %s/%s from %d to %d (Action: %s)",
                self.namespace,
                self.deployment_name,
                initial_replicas,
                target_replicas,
                action,
            )
            # Dry-run must never mutate simulated state or modify the cluster
            return ExecutionResult(
                success=True,
                dry_run=True,
                initial_replicas=initial_replicas,
                target_replicas=target_replicas,
                confirmed_replicas=None,
                action_type=action,
                message=f"[DRY-RUN PREVIEW] Would scale {self.deployment_name} from {initial_replicas} to {target_replicas}. No cluster changes applied.",
                execution_duration_ms=(time.time() - start_time) * 1000,
            )

        # 2. Live Execution Mode
        if not self._connected or not self._apps_v1_api:
            return ExecutionResult(
                success=False,
                dry_run=False,
                initial_replicas=initial_replicas,
                target_replicas=target_replicas,
                confirmed_replicas=None,
                action_type=action,
                message="Cannot execute live scaling: Kubernetes cluster connection is unavailable.",
                error=self._connection_error or "Not connected",
                execution_duration_ms=(time.time() - start_time) * 1000,
            )

        try:
            scale_patch = {"spec": {"replicas": target_replicas}}
            logger.info(
                "Executing live patch on %s/%s: target_replicas=%d",
                self.namespace,
                self.deployment_name,
                target_replicas,
            )
            # Patch deployment scale subresource
            self._apps_v1_api.patch_namespaced_deployment_scale(
                name=self.deployment_name,
                namespace=self.namespace,
                body=scale_patch,
            )

            # Verification: Poll cluster to confirm spec.replicas and pod readiness
            deadline = time.time() + self.verification_timeout_seconds
            confirmed_replicas = None
            observed_ready = 0
            observed_available = 0
            failure_reason = None
            current_state = initial_state

            while time.time() < deadline:
                current_state = self.get_workload_state()
                observed_ready = current_state.ready_replicas
                observed_available = current_state.available_replicas

                # Verification requires:
                # 1. spec.replicas matches target
                # 2. ready_replicas matches target
                # (When scaling in or out, rollout is complete when ready_replicas reaches target)
                if current_state.desired_replicas == target_replicas:
                    if observed_ready == target_replicas:
                        confirmed_replicas = observed_ready
                        break

                # Inspect deployment status conditions for progress deadline failure
                if self._apps_v1_api:
                    try:
                        dep_obj = self._apps_v1_api.read_namespaced_deployment(
                            name=self.deployment_name,
                            namespace=self.namespace,
                            _request_timeout=1.5,
                        )
                        if dep_obj and getattr(dep_obj, "status", None) and getattr(dep_obj.status, "conditions", None):
                            for c in dep_obj.status.conditions:
                                if c.type == "Progressing" and c.status == "False" and c.reason == "ProgressDeadlineExceeded":
                                    failure_reason = f"ProgressDeadlineExceeded: {c.message}"
                                    break
                    except Exception:
                        pass

                # Inspect pods for fatal waiting states (CrashLoopBackOff, ImagePullBackOff, Unschedulable)
                if self._core_v1_api and not failure_reason:
                    try:
                        pod_items = self._core_v1_api.list_namespaced_pod(
                            namespace=self.namespace,
                            label_selector=f"app={self.deployment_name}",
                            _request_timeout=1.5,
                        ).items
                        for p in (pod_items or []):
                            if p.status and p.status.container_statuses:
                                for cs in p.status.container_statuses:
                                    if cs.state and cs.state.waiting:
                                        r = cs.state.waiting.reason
                                        if r in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError"):
                                            failure_reason = f"Pod '{p.metadata.name}' failed with {r}: {cs.state.waiting.message}"
                                            break
                            if p.status and p.status.conditions:
                                for c in p.status.conditions:
                                    if c.type == "PodScheduled" and c.status == "False" and c.reason == "Unschedulable":
                                        failure_reason = f"Pod '{p.metadata.name}' unschedulable: {c.message}"
                                        break
                            if failure_reason:
                                break
                    except Exception:
                        pass

                if failure_reason:
                    break

                time.sleep(1.0)

            duration_ms = (time.time() - start_time) * 1000

            if failure_reason:
                msg = f"Scaling execution failed during pod rollout: {failure_reason}"
                logger.error(msg)
                return ExecutionResult(
                    success=False,
                    dry_run=False,
                    initial_replicas=initial_replicas,
                    target_replicas=target_replicas,
                    confirmed_replicas=observed_ready,
                    action_type=action,
                    message=msg,
                    error=failure_reason,
                    execution_duration_ms=duration_ms,
                )

            if confirmed_replicas == target_replicas:
                msg = f"Successfully scaled {self.deployment_name} from {initial_replicas} to {target_replicas} and verified by Kubernetes API (Ready: {observed_ready}/{target_replicas})."
                logger.info(msg)
                return ExecutionResult(
                    success=True,
                    dry_run=False,
                    initial_replicas=initial_replicas,
                    target_replicas=target_replicas,
                    confirmed_replicas=confirmed_replicas,
                    action_type=action,
                    message=msg,
                    execution_duration_ms=duration_ms,
                )
            else:
                msg = f"Scaling patch sent, but pod readiness verification timed out. Desired: {current_state.desired_replicas}, Ready: {observed_ready}/{target_replicas}, Available: {observed_available}/{target_replicas}."
                logger.warning(msg)
                return ExecutionResult(
                    success=False,
                    dry_run=False,
                    initial_replicas=initial_replicas,
                    target_replicas=target_replicas,
                    confirmed_replicas=current_state.desired_replicas,
                    action_type=action,
                    message=msg,
                    error="VerificationTimeout",
                    execution_duration_ms=duration_ms,
                )

        except ApiException as e:
            duration_ms = (time.time() - start_time) * 1000
            err_msg = f"Kubernetes API error (HTTP {e.status}): {e.reason} - {e.body}"
            logger.error("Live scaling failed: %s", err_msg)
            return ExecutionResult(
                success=False,
                dry_run=False,
                initial_replicas=initial_replicas,
                target_replicas=target_replicas,
                confirmed_replicas=None,
                action_type=action,
                message="Live scaling failed due to Kubernetes API exception.",
                error=err_msg,
                execution_duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            err_msg = f"Unexpected execution error: {str(e)}"
            logger.error("Live scaling failed: %s", err_msg)
            return ExecutionResult(
                success=False,
                dry_run=False,
                initial_replicas=initial_replicas,
                target_replicas=target_replicas,
                confirmed_replicas=None,
                action_type=action,
                message="Live scaling encountered an unexpected internal error.",
                error=err_msg,
                execution_duration_ms=duration_ms,
            )
