"""
Main Controller Lifecycle Coordinator.
Project ID: 357 | Alliance University, Bengaluru
Algorithm: PRAH (Priority-based Rule Arbitration with Hysteresis)

Coordinates telemetry, rule evaluation, PRAH decision-making, guardrails,
Kubernetes execution, and audit logging in an explainable, deterministic loop.
"""

import argparse
import logging
from pathlib import Path
import signal
import sys
import threading
import time

# Ensure project root is in sys.path when invoked directly as a script
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from typing import Any, Dict, Optional, Tuple

from controller.config import ControllerConfig
from controller.decision_controller import Decision, DecisionController
from controller.decision_logger import DecisionLogger
from controller.guardrails import GuardrailEngine, GuardrailResult
from controller.kubernetes_executor import ExecutionResult, KubernetesExecutor, WorkloadState
from controller.policy_engine import PolicyEngine
from controller.strategy_coordinator import StrategyCoordinator
from controller.experiment_runner import ExperimentManager
from controller.telemetry import (
    MetricSample,
    MetricStatus,
    PrometheusTelemetryProvider,
    SimulatedTelemetryProvider,
    build_metric_queries,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("autoscaler.main")


class AutoscalingController:
    """Central orchestrator for the Kubernetes-Based Auto-Scaling Framework."""

    def __init__(self, config: Optional[ControllerConfig] = None):
        self.config = config or ControllerConfig.load()
        self._stop_event = threading.Event()
        self._cycle_lock = threading.Lock()

        # Initialize core components
        self.policy_engine = PolicyEngine(self.config.policies_path)
        self.decision_controller = DecisionController(
            policy_engine=self.policy_engine,
            default_cooldown_seconds=self.config.cooldown_seconds,
            hysteresis_band_percent=self.config.hysteresis_band_percent,
        )
        self.guardrail_engine = GuardrailEngine(
            min_replicas=self.config.min_replicas,
            max_replicas=self.config.max_replicas,
            max_scale_step_up=self.config.max_scale_step_up,
            max_scale_step_down=self.config.max_scale_step_down,
            dry_run=self.config.dry_run,
            enable_live_execution=self.config.enable_live_execution,
        )
        self.executor = KubernetesExecutor(
            namespace=self.config.target_namespace,
            deployment_name=self.config.target_deployment,
            kubeconfig_path=self.config.kubeconfig_path,
        )
        self.strategy_coordinator = StrategyCoordinator(
            executor=self.executor,
            guardrail_engine=self.guardrail_engine,
        )
        self.decision_logger = DecisionLogger(log_file_path=self.config.log_file_path)

        # Telemetry provider setup
        self.prometheus_provider = PrometheusTelemetryProvider(
            prometheus_url=self.config.prometheus_url,
            staleness_threshold_seconds=self.config.metric_staleness_seconds,
        )
        self.simulated_provider = SimulatedTelemetryProvider()

        # Cache latest cycle snapshot for dashboard
        self.latest_telemetry: Dict[str, MetricSample] = {}
        self.latest_decision: Optional[Decision] = None
        self.latest_guardrail: Optional[GuardrailResult] = None
        self.latest_execution: Optional[ExecutionResult] = None
        self.latest_workload_state: Optional[WorkloadState] = None
        self.experiment_manager = ExperimentManager(self)

        # Track policy file modification time for dynamic reloads
        self._last_policies_mtime: float = 0.0
        try:
            p_init = Path(self.config.policies_path)
            if p_init.exists():
                self._last_policies_mtime = p_init.stat().st_mtime
        except Exception:
            pass

    def set_live_execution(self, enabled: bool) -> None:
        """Enables or disables live execution safely."""
        self.config.enable_live_execution = enabled
        self.config.dry_run = not enabled
        self.guardrail_engine.set_live_execution(enabled)
        logger.warning(
            "OPERATIONAL MODE CHANGED: Live Execution = %s | Dry Run = %s",
            self.config.enable_live_execution,
            self.config.dry_run,
        )

    def reload_policies(self, path: Optional[str] = None) -> None:
        """Safely reload policies from disk and update target workload."""
        target_path = path or self.config.policies_path
        self.policy_engine.load_from_yaml(target_path)
        if self.policy_engine.target_workload:
            ns = self.policy_engine.target_workload.get("namespace")
            name = self.policy_engine.target_workload.get("name")
            if ns:
                self.config.target_namespace = ns
                self.executor.namespace = ns
            if name:
                self.config.target_deployment = name
                self.executor.deployment_name = name
        logger.info("Policies successfully reloaded from %s", target_path)

    def fetch_current_telemetry(self) -> Dict[str, MetricSample]:
        """Collects telemetry from Prometheus, falling back to simulated source if requested/offline."""
        queries = build_metric_queries(self.config.target_namespace, self.config.target_deployment)
        metrics: Dict[str, MetricSample] = {}

        if self.config.simulation_mode:
            for metric_name, query in queries.items():
                metrics[metric_name] = self.simulated_provider.query_instant(query, metric_name)
            return metrics

        # Live query against Prometheus
        prom_ready, _ = self.prometheus_provider.check_connection()
        if not prom_ready:
            logger.debug("Prometheus connection unavailable at %s", self.config.prometheus_url)

        for metric_name, query in queries.items():
            sample = self.prometheus_provider.query_instant(query, metric_name)
            metrics[metric_name] = sample

        return metrics

    def run_single_cycle(self, now: Optional[float] = None, forced_metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes one full iteration of the auto-scaling pipeline.
        Thread-safe; can be called on schedule or triggered by dashboard.
        Supports optional forced_metrics injection for controlled live evaluation scenarios.
        """
        with self._cycle_lock:
            # Check for policy updates on disk (e.g. edited via dashboard or PVC)
            try:
                p_check = Path(self.config.policies_path)
                if p_check.exists():
                    current_mtime = p_check.stat().st_mtime
                    if current_mtime > self._last_policies_mtime:
                        if self._last_policies_mtime > 0.0:
                            logger.info("Policies file modified on disk (%s). Reloading active policies.", p_check)
                            self.reload_policies()
                        self._last_policies_mtime = current_mtime
            except Exception as e:
                logger.debug("Policy mtime check skipped: %s", e)

            # 1. Read current workload state from Kubernetes
            workload_state = self.executor.get_workload_state()
            self.latest_workload_state = workload_state
            current_replicas = workload_state.desired_replicas

            # 2. Collect & validate telemetry
            if forced_metrics is not None:
                metrics = {}
                cycle_time = now or time.time()
                for m_name, m_val in forced_metrics.items():
                    if isinstance(m_val, MetricSample):
                        metrics[m_name] = m_val
                    elif isinstance(m_val, dict):
                        metrics[m_name] = MetricSample(
                            metric_name=m_name,
                            value=m_val.get("value"),
                            timestamp=cycle_time,
                            status=MetricStatus(m_val.get("status", "VALID")),
                            source=m_val.get("source", "forced"),
                        )
                    else:
                        metrics[m_name] = MetricSample(
                            metric_name=m_name,
                            value=float(m_val),
                            timestamp=cycle_time,
                            status=MetricStatus.VALID,
                            source="forced",
                        )
            else:
                metrics = self.fetch_current_telemetry()
            self.latest_telemetry = metrics

            # 3. Compute decision via PRAH
            decision = self.decision_controller.compute_decision(
                metrics=metrics,
                current_replicas=current_replicas,
                now=now,
                workload=workload_state,
            )
            self.latest_decision = decision

            # 4. Operational Guardrails and Execution
            guardrail_res, exec_res = self.strategy_coordinator.coordinate_and_execute(
                proposed_action=decision.action,
                current_replicas=current_replicas,
                target_replicas=decision.target_replicas,
                replica_delta=decision.proposed_replica_delta,
            )
            self.latest_guardrail = guardrail_res
            self.latest_execution = exec_res

            # 5. If action was executed, update cooldown in decision controller
            if exec_res.success and guardrail_res.action == "EXECUTE":
                cooldown_sec = self.config.cooldown_seconds
                self.decision_controller.record_action_executed(
                    action=decision.action,
                    policy_id=decision.selected_policy_id,
                    cooldown_seconds=cooldown_sec,
                    now=now,
                )

            # 6. Structured audit logging
            metrics_summary = {
                name: {
                    "value": s.value,
                    "status": s.status.value,
                    "source": s.source,
                }
                for name, s in metrics.items()
            }
            log_record = self.decision_logger.log_cycle(
                decision=decision.to_dict(),
                guardrail_result=guardrail_res.to_dict(),
                execution_result=exec_res.to_dict(),
                metrics=metrics_summary,
                error=exec_res.error or guardrail_res.rejection_reason,
                target_namespace=self.config.target_namespace,
                target_deployment=self.config.target_deployment,
            )

            logger.info(
                "Cycle Completed | Action: %s (Δ: %+d -> %d) | DryRun: %s | Replicas: %d | Guardrail: %s",
                decision.action,
                guardrail_res.replica_delta,
                guardrail_res.authorized_target_replicas,
                guardrail_res.is_dry_run,
                workload_state.desired_replicas,
                guardrail_res.action,
            )

            return log_record

    def start_loop(self) -> None:
        """Starts the autonomous evaluation loop until stopped."""
        logger.info(
            "Starting PRAH Autoscaling Controller loop for %s/%s (Interval: %.1fs)",
            self.config.target_namespace,
            self.config.target_deployment,
            self.config.evaluation_interval_seconds,
        )
        self._stop_event.clear()

        while not self._stop_event.is_set():
            try:
                self.run_single_cycle()
            except Exception as e:
                logger.exception("Unexpected error during controller cycle: %s", e)

            self._stop_event.wait(timeout=self.config.evaluation_interval_seconds)

        logger.info("Autoscaling Controller loop stopped gracefully.")

    def stop(self) -> None:
        """Signals controller loop to stop."""
        self._stop_event.set()


def main():
    parser = argparse.ArgumentParser(description="Kubernetes Auto-Scaling Framework Controller (Project 357)")
    parser.add_argument("--config", "-c", type=str, default=None, help="Path to scaling-policies.yaml")
    parser.add_argument("--dry-run", action="store_true", default=None, help="Force dry-run mode")
    parser.add_argument("--live", action="store_true", default=False, help="Enable live execution")
    parser.add_argument("--simulate", action="store_true", default=False, help="Use simulated metrics")
    parser.add_argument("--once", action="store_true", default=False, help="Run single evaluation cycle and exit")
    args = parser.parse_args()

    cfg = ControllerConfig.load(args.config)
    if args.dry_run is not None:
        cfg.dry_run = args.dry_run
    if args.live:
        cfg.enable_live_execution = True
        cfg.dry_run = False
    if args.simulate:
        cfg.simulation_mode = True

    controller = AutoscalingController(config=cfg)

    # Clean signal handling
    def sig_handler(signum, frame):
        logger.info("Signal %s received. Initiating graceful shutdown...", signum)
        controller.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    if args.once:
        logger.info("Running single evaluation cycle...")
        result = controller.run_single_cycle()
        print("\n=== Single Cycle Evaluation Record ===")
        import json
        print(json.dumps(result, indent=2))
    else:
        controller.start_loop()


if __name__ == "__main__":
    main()
