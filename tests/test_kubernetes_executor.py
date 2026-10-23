"""
Unit tests for Kubernetes API Executor and state verification.
"""

from unittest.mock import MagicMock, patch

from controller.kubernetes_executor import (
    ExecutionResult,
    KubernetesExecutor,
    WorkloadState,
)


def test_dry_run_scaling_execution():
    executor = KubernetesExecutor(
        namespace="test-ns",
        deployment_name="test-deploy",
    )
    # Ensure offline mode for unit test
    executor._connected = False
    executor._simulated_replicas = 2

    res = executor.execute_scaling(
        action="SCALE_OUT",
        target_replicas=4,
        dry_run=True,
    )

    assert res.success is True
    assert res.dry_run is True
    assert res.initial_replicas == 2
    assert res.target_replicas == 4
    assert res.confirmed_replicas == 4
    assert "[DRY-RUN PREVIEW]" in res.message


def test_hold_action_is_noop():
    executor = KubernetesExecutor(
        namespace="test-ns",
        deployment_name="test-deploy",
    )
    executor._simulated_replicas = 3

    res = executor.execute_scaling(
        action="HOLD",
        target_replicas=3,
        dry_run=False,
    )

    assert res.success is True
    assert res.action_type == "HOLD"
    assert "No-op scaling" in res.message


def test_live_scaling_fails_safely_when_disconnected():
    executor = KubernetesExecutor(
        namespace="test-ns",
        deployment_name="test-deploy",
    )
    executor._connected = False
    executor._connection_error = "Cluster unavailable"

    res = executor.execute_scaling(
        action="SCALE_OUT",
        target_replicas=5,
        dry_run=False,  # Requesting live mutation
    )

    assert res.success is False
    assert res.dry_run is False
    assert res.confirmed_replicas is None
    assert "Cannot execute live scaling: Kubernetes cluster connection is unavailable" in res.message


def test_live_scaling_verification_success():
    executor = KubernetesExecutor(
        namespace="test-ns",
        deployment_name="test-deploy",
    )
    executor._connected = True
    executor._apps_v1_api = MagicMock()

    # Initial state has 2 replicas; after patch it has 4 replicas
    mock_dep_initial = MagicMock()
    mock_dep_initial.spec.replicas = 2
    mock_dep_initial.status.replicas = 2
    mock_dep_initial.status.ready_replicas = 2
    mock_dep_initial.status.available_replicas = 2

    mock_dep_scaled = MagicMock()
    mock_dep_scaled.spec.replicas = 4
    mock_dep_scaled.status.replicas = 4
    mock_dep_scaled.status.ready_replicas = 4
    mock_dep_scaled.status.available_replicas = 4

    executor._apps_v1_api.read_namespaced_deployment.side_effect = [
        mock_dep_initial,
        mock_dep_scaled,
    ]

    # Patch call succeeds
    executor._apps_v1_api.patch_namespaced_deployment_scale.return_value = MagicMock()

    res = executor.execute_scaling(
        action="SCALE_OUT",
        target_replicas=4,
        dry_run=False,
    )

    assert res.success is True
    assert res.dry_run is False
    assert res.initial_replicas == 2
    assert res.target_replicas == 4
    assert res.confirmed_replicas == 4
    assert "verified by Kubernetes API" in res.message
    executor._apps_v1_api.patch_namespaced_deployment_scale.assert_called_once_with(
        name="test-deploy",
        namespace="test-ns",
        body={"spec": {"replicas": 4}},
    )
