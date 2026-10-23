"""
Configuration module for Kubernetes Auto-Scaling Framework (Project 357).
Handles loading from environment variables, YAML files, and safe defaults.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


@dataclass
class ControllerConfig:
    # Telemetry settings
    prometheus_url: str = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    metric_staleness_seconds: float = float(os.getenv("METRIC_STALENESS_SECONDS", "60.0"))
    metric_timeout_seconds: float = float(os.getenv("METRIC_TIMEOUT_SECONDS", "1.5"))

    # Policy configuration
    policies_path: str = os.getenv("POLICIES_PATH", "policies/scaling-policies.yaml")

    # Target Kubernetes deployment
    target_namespace: str = os.getenv("TARGET_NAMESPACE", "autoscaling-demo")
    target_deployment: str = os.getenv("TARGET_DEPLOYMENT", "sample-web-app")
    kubeconfig_path: Optional[str] = os.getenv("KUBECONFIG_PATH", None)

    # Operational safety controls & guardrails
    dry_run: bool = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
    enable_live_execution: bool = os.getenv("ENABLE_LIVE_EXECUTION", "false").lower() in ("true", "1", "yes")
    min_replicas: int = int(os.getenv("MIN_REPLICAS", "1"))
    max_replicas: int = int(os.getenv("MAX_REPLICAS", "10"))
    max_scale_step_up: int = int(os.getenv("MAX_SCALE_STEP_UP", "2"))
    max_scale_step_down: int = int(os.getenv("MAX_SCALE_STEP_DOWN", "1"))
    cooldown_seconds: float = float(os.getenv("COOLDOWN_SECONDS", "60.0"))
    hysteresis_band_percent: float = float(os.getenv("HYSTERESIS_BAND_PERCENT", "5.0"))

    # Controller lifecycle
    evaluation_interval_seconds: float = float(os.getenv("EVALUATION_INTERVAL_SECONDS", "10.0"))
    log_file_path: str = os.getenv("LOG_FILE_PATH", "logs/decisions.jsonl")

    # Simulation mode support for local demonstrations without Prometheus
    simulation_mode: bool = os.getenv("SIMULATION_MODE", "false").lower() in ("true", "1", "yes")

    def is_live_execution_permitted(self) -> bool:
        """Live execution is permitted only when dry_run is False and enable_live_execution is True."""
        return (not self.dry_run) and self.enable_live_execution

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prometheus_url": self.prometheus_url,
            "metric_staleness_seconds": self.metric_staleness_seconds,
            "policies_path": self.policies_path,
            "target_namespace": self.target_namespace,
            "target_deployment": self.target_deployment,
            "dry_run": self.dry_run,
            "enable_live_execution": self.enable_live_execution,
            "live_execution_permitted": self.is_live_execution_permitted(),
            "min_replicas": self.min_replicas,
            "max_replicas": self.max_replicas,
            "max_scale_step_up": self.max_scale_step_up,
            "max_scale_step_down": self.max_scale_step_down,
            "cooldown_seconds": self.cooldown_seconds,
            "hysteresis_band_percent": self.hysteresis_band_percent,
            "evaluation_interval_seconds": self.evaluation_interval_seconds,
            "log_file_path": self.log_file_path,
            "simulation_mode": self.simulation_mode,
        }

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "ControllerConfig":
        """Load configuration from file if provided, overriding with environment variables."""
        instance = cls()
        if config_path and Path(config_path).exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            
            # Parse workload
            workload = data.get("target_workload", {})
            if "namespace" in workload:
                instance.target_namespace = workload["namespace"]
            if "name" in workload:
                instance.target_deployment = workload["name"]

            # Parse guardrails
            guardrails = data.get("guardrails", {})
            if "min_replicas" in guardrails:
                instance.min_replicas = int(guardrails["min_replicas"])
            if "max_replicas" in guardrails:
                instance.max_replicas = int(guardrails["max_replicas"])
            if "max_scale_step_up" in guardrails:
                instance.max_scale_step_up = int(guardrails["max_scale_step_up"])
            if "max_scale_step_down" in guardrails:
                instance.max_scale_step_down = int(guardrails["max_scale_step_down"])
            if "cooldown_seconds" in guardrails:
                instance.cooldown_seconds = float(guardrails["cooldown_seconds"])
            if "hysteresis_band_percent" in guardrails:
                instance.hysteresis_band_percent = float(guardrails["hysteresis_band_percent"])
            if "dry_run_default" in guardrails and "DRY_RUN" not in os.environ:
                instance.dry_run = bool(guardrails["dry_run_default"])

        return instance
