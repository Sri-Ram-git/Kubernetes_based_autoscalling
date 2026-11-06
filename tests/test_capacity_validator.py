"""
Unit tests for the Capacity Validator module (Project 357).
Verifies node allocatable calculations, unit conversions, bin-packing simulation,
and classification into the 5 authoritative outcomes:
- CAPACITY_SUFFICIENT
- INSUFFICIENT_CPU
- INSUFFICIENT_MEMORY
- NO_ELIGIBLE_NODE
- CAPACITY_UNKNOWN
"""

from unittest.mock import MagicMock
import pytest

from controller.capacity_validator import (
    CapacityOutcome,
    CapacityValidationResult,
    CapacityValidator,
    NodeCapacityReport,
    parse_cpu_millicores,
    parse_memory_bytes,
)


def test_parse_cpu_millicores():
    assert parse_cpu_millicores("100m") == 100
    assert parse_cpu_millicores("500m") == 500
    assert parse_cpu_millicores("1") == 1000
    assert parse_cpu_millicores("2.5") == 2500
    assert parse_cpu_millicores(4) == 4000
    assert parse_cpu_millicores(None) == 0
    assert parse_cpu_millicores("") == 0
    assert parse_cpu_millicores("invalid") == 0


def test_parse_memory_bytes():
    assert parse_memory_bytes("128Mi") == 128 * 1024 * 1024
    assert parse_memory_bytes("1Gi") == 1024 * 1024 * 1024
    assert parse_memory_bytes("64Ki") == 64 * 1024
    assert parse_memory_bytes("500M") == 500 * 1000 * 1000
    assert parse_memory_bytes("2G") == 2 * 1000 * 1000 * 1000
    assert parse_memory_bytes(1048576) == 1048576
    assert parse_memory_bytes(None) == 0
    assert parse_memory_bytes("") == 0
    assert parse_memory_bytes("invalid") == 0


def test_capacity_sufficient_single_node():
    mock_core = MagicMock()
    mock_apps = MagicMock()

    # 1 Ready, schedulable node with 4000m CPU, 4Gi Mem
    mock_node = MagicMock()
    mock_node.metadata.name = "worker-1"
    mock_node.spec.unschedulable = False
    mock_node.spec.taints = []
    ready_cond = MagicMock()
    ready_cond.type = "Ready"
    ready_cond.status = "True"
    mock_node.status.conditions = [ready_cond]
    mock_node.status.allocatable = {"cpu": "4", "memory": "4Gi"}

    mock_core.list_node.return_value.items = [mock_node]

    # No existing pods consuming resources
    mock_core.list_pod_for_all_namespaces.return_value.items = []

    # Deployment requests 100m CPU, 128Mi memory per pod
    mock_dep = MagicMock()
    mock_container = MagicMock()
    mock_container.resources.requests = {"cpu": "100m", "memory": "128Mi"}
    mock_dep.spec.template.spec.containers = [mock_container]
    mock_dep.spec.template.spec.tolerations = []
    mock_apps.read_namespaced_deployment.return_value = mock_dep

    validator = CapacityValidator(core_v1_api=mock_core, apps_v1_api=mock_apps)
    res = validator.validate_scale_out(delta=2)

    assert res.outcome == CapacityOutcome.CAPACITY_SUFFICIENT
    assert res.is_sufficient is True
    assert res.requested_replicas_delta == 2
    assert res.pod_cpu_m == 100
    assert res.pod_memory_bytes == 128 * 1024 * 1024
    assert len(res.evaluated_nodes) == 1
    assert "Sufficient capacity" in res.message


def test_insufficient_cpu():
    mock_core = MagicMock()
    mock_apps = MagicMock()

    # Node has only 150m CPU available
    mock_node = MagicMock()
    mock_node.metadata.name = "worker-tight-cpu"
    mock_node.spec.unschedulable = False
    mock_node.spec.taints = []
    ready_cond = MagicMock()
    ready_cond.type = "Ready"
    ready_cond.status = "True"
    mock_node.status.conditions = [ready_cond]
    mock_node.status.allocatable = {"cpu": "200m", "memory": "4Gi"}

    mock_core.list_node.return_value.items = [mock_node]
    mock_core.list_pod_for_all_namespaces.return_value.items = []

    # Each pod needs 100m CPU. Delta 2 needs 200m CPU, but node only has 200m allocatable total,
    # and first pod takes 100m, leaving 100m. Second pod takes 100m, leaving 0.
    # What if delta = 3 (needs 300m)?
    mock_dep = MagicMock()
    mock_container = MagicMock()
    mock_container.resources.requests = {"cpu": "100m", "memory": "128Mi"}
    mock_dep.spec.template.spec.containers = [mock_container]
    mock_dep.spec.template.spec.tolerations = []
    mock_apps.read_namespaced_deployment.return_value = mock_dep

    validator = CapacityValidator(core_v1_api=mock_core, apps_v1_api=mock_apps)
    res = validator.validate_scale_out(delta=3)

    assert res.outcome == CapacityOutcome.INSUFFICIENT_CPU
    assert res.is_sufficient is False
    assert "Insufficient CPU capacity" in res.message


def test_insufficient_memory():
    mock_core = MagicMock()
    mock_apps = MagicMock()

    # Node has plenty of CPU, but only 200Mi memory available
    mock_node = MagicMock()
    mock_node.metadata.name = "worker-tight-mem"
    mock_node.spec.unschedulable = False
    mock_node.spec.taints = []
    ready_cond = MagicMock()
    ready_cond.type = "Ready"
    ready_cond.status = "True"
    mock_node.status.conditions = [ready_cond]
    mock_node.status.allocatable = {"cpu": "4", "memory": "200Mi"}

    mock_core.list_node.return_value.items = [mock_node]
    mock_core.list_pod_for_all_namespaces.return_value.items = []

    # 2 pods need 128Mi each = 256Mi > 200Mi available
    mock_dep = MagicMock()
    mock_container = MagicMock()
    mock_container.resources.requests = {"cpu": "100m", "memory": "128Mi"}
    mock_dep.spec.template.spec.containers = [mock_container]
    mock_dep.spec.template.spec.tolerations = []
    mock_apps.read_namespaced_deployment.return_value = mock_dep

    validator = CapacityValidator(core_v1_api=mock_core, apps_v1_api=mock_apps)
    res = validator.validate_scale_out(delta=2)

    assert res.outcome == CapacityOutcome.INSUFFICIENT_MEMORY
    assert res.is_sufficient is False
    assert "Insufficient memory capacity" in res.message


def test_no_eligible_node_due_to_cordon():
    mock_core = MagicMock()
    mock_apps = MagicMock()

    mock_node = MagicMock()
    mock_node.metadata.name = "worker-cordoned"
    mock_node.spec.unschedulable = True  # Cordoned
    mock_node.spec.taints = []
    ready_cond = MagicMock()
    ready_cond.type = "Ready"
    ready_cond.status = "True"
    mock_node.status.conditions = [ready_cond]
    mock_node.status.allocatable = {"cpu": "4", "memory": "4Gi"}

    mock_core.list_node.return_value.items = [mock_node]
    mock_core.list_pod_for_all_namespaces.return_value.items = []

    validator = CapacityValidator(core_v1_api=mock_core, apps_v1_api=mock_apps)
    res = validator.validate_scale_out(delta=1)

    assert res.outcome == CapacityOutcome.NO_ELIGIBLE_NODE
    assert res.is_sufficient is False
    assert "No eligible nodes available" in res.message


def test_no_eligible_node_due_to_taint():
    mock_core = MagicMock()
    mock_apps = MagicMock()

    # Node has untolerated taint
    mock_node = MagicMock()
    mock_node.metadata.name = "master-tainted"
    mock_node.spec.unschedulable = False
    taint = MagicMock()
    taint.key = "node-role.kubernetes.io/control-plane"
    taint.value = "true"
    taint.effect = "NoSchedule"
    mock_node.spec.taints = [taint]
    ready_cond = MagicMock()
    ready_cond.type = "Ready"
    ready_cond.status = "True"
    mock_node.status.conditions = [ready_cond]
    mock_node.status.allocatable = {"cpu": "4", "memory": "4Gi"}

    mock_core.list_node.return_value.items = [mock_node]
    mock_core.list_pod_for_all_namespaces.return_value.items = []

    mock_dep = MagicMock()
    mock_dep.spec.template.spec.containers = []
    mock_dep.spec.template.spec.tolerations = []  # No tolerations
    mock_apps.read_namespaced_deployment.return_value = mock_dep

    validator = CapacityValidator(core_v1_api=mock_core, apps_v1_api=mock_apps)
    res = validator.validate_scale_out(delta=1)

    assert res.outcome == CapacityOutcome.NO_ELIGIBLE_NODE
    assert res.is_sufficient is False
    assert "UntoleratedTaints" in res.message


def test_capacity_unknown_when_offline():
    validator = CapacityValidator(core_v1_api=None, apps_v1_api=None)
    res = validator.validate_scale_out(delta=1)

    assert res.outcome == CapacityOutcome.CAPACITY_UNKNOWN
    assert res.is_sufficient is False
    assert "unavailable" in res.message


def test_delta_zero_or_negative_is_always_sufficient():
    validator = CapacityValidator(core_v1_api=None, apps_v1_api=None)
    res_zero = validator.validate_scale_out(delta=0)
    assert res_zero.outcome == CapacityOutcome.CAPACITY_SUFFICIENT
    assert res_zero.is_sufficient is True

    res_neg = validator.validate_scale_out(delta=-1)
    assert res_neg.outcome == CapacityOutcome.CAPACITY_SUFFICIENT
    assert res_neg.is_sufficient is True


def test_strategy_coordinator_blocks_when_capacity_insufficient():
    from controller.strategy_coordinator import StrategyCoordinator
    from controller.guardrails import GuardrailEngine

    mock_executor = MagicMock()
    mock_executor._connected = True
    mock_executor.namespace = "autoscaling-demo"
    mock_executor.deployment_name = "sample-web-app"
    mock_executor._apps_v1_api = None

    guardrails = GuardrailEngine(min_replicas=1, max_replicas=10, max_scale_step_up=2, dry_run=False, enable_live_execution=True)

    mock_validator = MagicMock()
    mock_validator.validate_scale_out.return_value = CapacityValidationResult(
        outcome=CapacityOutcome.INSUFFICIENT_CPU,
        is_sufficient=False,
        requested_replicas_delta=2,
        pod_cpu_m=100,
        pod_memory_bytes=134217728,
        total_additional_cpu_m=200,
        total_additional_memory_bytes=268435456,
        message="Insufficient CPU capacity on eligible nodes for +2 pod(s).",
    )

    coordinator = StrategyCoordinator(
        executor=mock_executor,
        guardrail_engine=guardrails,
        enforce_exclusive_ownership=False,
        capacity_validator=mock_validator,
    )

    guard_res, exec_res = coordinator.coordinate_and_execute(
        proposed_action="SCALE_OUT",
        current_replicas=2,
        target_replicas=4,
        replica_delta=2,
    )

    assert guard_res.approved is False
    assert guard_res.action == "REJECTED"
    assert "Scale-out blocked by capacity guardrail" in guard_res.rejection_reason
    assert exec_res.success is False
    assert exec_res.error == "INSUFFICIENT_CPU"
    mock_executor.execute_scaling.assert_not_called()


def test_strategy_coordinator_allows_when_capacity_sufficient():
    from controller.strategy_coordinator import StrategyCoordinator
    from controller.guardrails import GuardrailEngine
    from controller.kubernetes_executor import ExecutionResult

    mock_executor = MagicMock()
    mock_executor._connected = True
    mock_executor.namespace = "autoscaling-demo"
    mock_executor.deployment_name = "sample-web-app"
    mock_executor._apps_v1_api = None
    mock_executor.execute_scaling.return_value = ExecutionResult(
        success=True,
        dry_run=False,
        initial_replicas=2,
        target_replicas=4,
        confirmed_replicas=4,
        action_type="SCALE_OUT",
        message="Scaled successfully",
    )

    guardrails = GuardrailEngine(min_replicas=1, max_replicas=10, max_scale_step_up=2, dry_run=False, enable_live_execution=True)

    mock_validator = MagicMock()
    mock_validator.validate_scale_out.return_value = CapacityValidationResult(
        outcome=CapacityOutcome.CAPACITY_SUFFICIENT,
        is_sufficient=True,
        requested_replicas_delta=2,
        pod_cpu_m=100,
        pod_memory_bytes=134217728,
        total_additional_cpu_m=200,
        total_additional_memory_bytes=268435456,
        message="Sufficient capacity on 1 node(s) for +2 pod(s).",
    )

    coordinator = StrategyCoordinator(
        executor=mock_executor,
        guardrail_engine=guardrails,
        enforce_exclusive_ownership=False,
        capacity_validator=mock_validator,
    )

    guard_res, exec_res = coordinator.coordinate_and_execute(
        proposed_action="SCALE_OUT",
        current_replicas=2,
        target_replicas=4,
        replica_delta=2,
    )

    assert guard_res.approved is True
    assert guard_res.action == "EXECUTE"
    assert exec_res.success is True
    assert exec_res.confirmed_replicas == 4
    mock_executor.execute_scaling.assert_called_once_with(action="SCALE_OUT", target_replicas=4, dry_run=False)


def test_strategy_coordinator_bypasses_capacity_on_scale_in():
    from controller.strategy_coordinator import StrategyCoordinator
    from controller.guardrails import GuardrailEngine
    from controller.kubernetes_executor import ExecutionResult

    mock_executor = MagicMock()
    mock_executor._connected = True
    mock_executor.namespace = "autoscaling-demo"
    mock_executor.deployment_name = "sample-web-app"
    mock_executor._apps_v1_api = None
    mock_executor.execute_scaling.return_value = ExecutionResult(
        success=True,
        dry_run=False,
        initial_replicas=4,
        target_replicas=3,
        confirmed_replicas=3,
        action_type="SCALE_IN",
        message="Scaled in successfully",
    )

    guardrails = GuardrailEngine(min_replicas=1, max_replicas=10, max_scale_step_down=1, dry_run=False, enable_live_execution=True)

    mock_validator = MagicMock()

    coordinator = StrategyCoordinator(
        executor=mock_executor,
        guardrail_engine=guardrails,
        enforce_exclusive_ownership=False,
        capacity_validator=mock_validator,
    )

    guard_res, exec_res = coordinator.coordinate_and_execute(
        proposed_action="SCALE_IN",
        current_replicas=4,
        target_replicas=3,
        replica_delta=-1,
    )

    assert guard_res.approved is True
    assert exec_res.success is True
    mock_validator.validate_scale_out.assert_not_called()
    mock_executor.execute_scaling.assert_called_once_with(action="SCALE_IN", target_replicas=3, dry_run=False)

