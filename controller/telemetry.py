"""
Telemetry ingestion, validation, and normalization module for Prometheus metrics.
Project ID: 357 | Alliance University, Bengaluru
Module 2: Telemetry Processing & Live Prometheus Integration

Strict engineering requirements:
- Deterministic, rule-based telemetry processing. NO ML, NO FORECASTING, NO AI.
- Never silently replace missing metrics with arbitrary zero or default values.
- Distinguish real measurements (VALID) from UNAVAILABLE, MISSING, STALE, or INVALID data.
- Validate non-finite numbers (reject NaN and +/-Inf).
- Provide controlled fail-safe fallback (HOLD state) in decision pipeline when telemetry is degraded.
"""

from dataclasses import asdict, dataclass
from enum import Enum
import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple
import requests

logger = logging.getLogger("autoscaler.telemetry")

# Central telemetry configuration defaults
DEFAULT_STALENESS_THRESHOLD_SECONDS = 60.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 1.5

METRIC_UNITS: Dict[str, str] = {
    "cpu_utilization_percent": "%",
    "memory_utilization_percent": "%",
    "http_requests_per_second": "req/s",
}


class MetricStatus(str, Enum):
    VALID = "VALID"
    MISSING = "MISSING"
    STALE = "STALE"
    ERROR = "ERROR"
    SIMULATED = "SIMULATED"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class MetricSample:
    metric_name: str
    value: Optional[float]
    timestamp: float
    status: MetricStatus
    source: str
    query: str = ""
    unit: str = "%"
    freshness_seconds: Optional[float] = None
    raw_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    scrape_target: Optional[str] = None

    def __post_init__(self):
        if not self.unit and self.metric_name in METRIC_UNITS:
            self.unit = METRIC_UNITS[self.metric_name]
        if self.freshness_seconds is None and self.timestamp:
            self.freshness_seconds = max(0.0, time.time() - self.timestamp)

    def is_usable(self) -> bool:
        """
        Returns True ONLY if the metric is valid and can be safely evaluated by rules.
        Rejects missing, stale, error, non-finite (NaN/Inf), and unavailable states.
        """
        return (
            self.status in (MetricStatus.VALID, MetricStatus.SIMULATED)
            and self.value is not None
            and isinstance(self.value, (int, float))
            and math.isfinite(self.value)
        )

    def to_dict(self) -> Dict[str, Any]:
        val = None
        if self.value is not None and math.isfinite(self.value):
            val = round(float(self.value), 2)

        return {
            "metric_name": self.metric_name,
            "value": val,
            "unit": self.unit or METRIC_UNITS.get(self.metric_name, ""),
            "timestamp": self.timestamp,
            "freshness_seconds": (
                round(self.freshness_seconds, 1)
                if self.freshness_seconds is not None
                else None
            ),
            "status": self.status.value,
            "is_usable": self.is_usable(),
            "source": self.source,
            "query": self.query,
            "error_message": self.error_message,
            "scrape_target": self.scrape_target,
        }


class PrometheusTelemetryProvider:
    """Retrieves, validates, and normalizes telemetry from the Prometheus HTTP API."""

    def __init__(
        self,
        prometheus_url: str = "http://localhost:9090",
        staleness_threshold_seconds: float = DEFAULT_STALENESS_THRESHOLD_SECONDS,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ):
        self.prometheus_url = prometheus_url.rstrip("/")
        self.staleness_threshold_seconds = staleness_threshold_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._session = requests.Session()

    @property
    def session(self) -> requests.Session:
        """Returns underlying requests.Session for queries and testing."""
        return self._session

    def check_connection(self) -> Tuple[bool, str]:
        """
        Validates reachability of the Prometheus server using readiness and health endpoints.
        """
        # Try /-/ready first
        ready_endpoint = f"{self.prometheus_url}/-/ready"
        try:
            resp = self._session.get(ready_endpoint, timeout=self.request_timeout_seconds)
            if resp.status_code == 200:
                return True, "Prometheus server is ready."
            if resp.status_code == 503:
                return False, f"Prometheus is initializing (HTTP 503): {resp.text.strip()}"
        except requests.exceptions.RequestException:
            pass

        # Fallback to /-/healthy
        healthy_endpoint = f"{self.prometheus_url}/-/healthy"
        try:
            resp = self._session.get(healthy_endpoint, timeout=self.request_timeout_seconds)
            if resp.status_code == 200:
                return True, "Prometheus server is healthy."
            return False, f"Prometheus returned HTTP {resp.status_code} on /-/healthy"
        except requests.exceptions.RequestException as e:
            return False, f"Cannot connect to Prometheus at {self.prometheus_url}: {e}"

    def get_targets_status(self) -> Dict[str, Any]:
        """
        Queries Prometheus /api/v1/targets to inspect genuine scrape target health.
        """
        endpoint = f"{self.prometheus_url}/api/v1/targets"
        try:
            resp = self._session.get(endpoint, timeout=self.request_timeout_seconds)
            if resp.status_code != 200:
                return {
                    "reachable": False,
                    "error": f"HTTP {resp.status_code}: {resp.text[:100]}",
                    "total_targets": 0,
                    "healthy_targets": 0,
                    "targets": [],
                }

            data = resp.json()
            if data.get("status") != "success":
                return {
                    "reachable": False,
                    "error": f"API error: {data.get('status')}",
                    "total_targets": 0,
                    "healthy_targets": 0,
                    "targets": [],
                }

            active = data.get("data", {}).get("activeTargets", [])
            healthy_count = sum(1 for t in active if t.get("health") == "up")
            target_list = [
                {
                    "job": t.get("labels", {}).get("job", t.get("scrapePool", "unknown")),
                    "instance": t.get("labels", {}).get("instance", ""),
                    "scrape_url": t.get("scrapeUrl", ""),
                    "health": t.get("health", "unknown"),
                    "last_scrape": t.get("lastScrape", ""),
                    "last_error": t.get("lastError", ""),
                }
                for t in active
            ]

            return {
                "reachable": True,
                "total_targets": len(active),
                "healthy_targets": healthy_count,
                "targets": target_list,
            }
        except requests.exceptions.RequestException as e:
            return {
                "reachable": False,
                "error": str(e),
                "total_targets": 0,
                "healthy_targets": 0,
                "targets": [],
            }

    def query_instant(self, query: str, metric_name: str, unit: Optional[str] = None) -> MetricSample:
        """
        Executes an instant vector query against Prometheus /api/v1/query.
        Performs strict normalization:
        - Rejects non-finite values (NaN, +Inf, -Inf).
        - Rejects malformed structures.
        - Calculates freshness and enforces staleness thresholds.
        - Distinguishes empty series (MISSING) from network failure (ERROR/UNAVAILABLE).
        """
        endpoint = f"{self.prometheus_url}/api/v1/query"
        unit = unit or METRIC_UNITS.get(metric_name, "%")
        now = time.time()

        try:
            resp = self._session.get(
                endpoint,
                params={"query": query},
                timeout=self.request_timeout_seconds,
            )
            if resp.status_code != 200:
                logger.warning("Prometheus HTTP %s for query %s: %s", resp.status_code, query, resp.text)
                return MetricSample(
                    metric_name=metric_name,
                    value=None,
                    timestamp=now,
                    status=MetricStatus.ERROR,
                    source="prometheus",
                    query=query,
                    unit=unit,
                    freshness_seconds=0.0,
                    error_message=f"Prometheus HTTP {resp.status_code}: {resp.text[:150]}",
                )

            data = resp.json()
            if data.get("status") != "success":
                return MetricSample(
                    metric_name=metric_name,
                    value=None,
                    timestamp=now,
                    status=MetricStatus.ERROR,
                    source="prometheus",
                    query=query,
                    unit=unit,
                    freshness_seconds=0.0,
                    error_message=f"Prometheus query status error: {data.get('status')}",
                )

            results = data.get("data", {}).get("result", [])
            if not results:
                # Query executed successfully, but no scrape targets or metrics match
                return MetricSample(
                    metric_name=metric_name,
                    value=None,
                    timestamp=now,
                    status=MetricStatus.MISSING,
                    source="prometheus",
                    query=query,
                    unit=unit,
                    freshness_seconds=0.0,
                    error_message=f"No matching series returned by Prometheus for metric '{metric_name}'. Scrape targets may be down or uninstrumented.",
                )

            # Handle multi-series aggregation or pick primary vector item
            sample_item = results[0]
            val_pair = sample_item.get("value")
            if not val_pair or len(val_pair) < 2:
                return MetricSample(
                    metric_name=metric_name,
                    value=None,
                    timestamp=now,
                    status=MetricStatus.INVALID,
                    source="prometheus",
                    query=query,
                    unit=unit,
                    freshness_seconds=0.0,
                    error_message="Malformed value sample vector returned by Prometheus.",
                )

            metric_timestamp = float(val_pair[0])
            val_str = str(val_pair[1]).strip()

            # Robust numerical parsing
            try:
                parsed_value = float(val_str)
            except (ValueError, TypeError):
                return MetricSample(
                    metric_name=metric_name,
                    value=None,
                    timestamp=metric_timestamp,
                    status=MetricStatus.INVALID,
                    source="prometheus",
                    query=query,
                    unit=unit,
                    freshness_seconds=max(0.0, now - metric_timestamp),
                    error_message=f"Non-numeric metric string returned by Prometheus: '{val_str}'",
                )

            # Strict non-finite rejection (NaN / Infinity)
            if not math.isfinite(parsed_value):
                return MetricSample(
                    metric_name=metric_name,
                    value=None,
                    timestamp=metric_timestamp,
                    status=MetricStatus.INVALID,
                    source="prometheus",
                    query=query,
                    unit=unit,
                    freshness_seconds=max(0.0, now - metric_timestamp),
                    error_message=f"Non-finite metric value ({val_str}) rejected by telemetry safety validation.",
                )

            # Staleness verification
            age_seconds = max(0.0, now - metric_timestamp)
            target_str = sample_item.get("metric", {}).get("instance", "")

            if age_seconds > self.staleness_threshold_seconds:
                logger.warning(
                    "Metric %s is STALE (age: %.1fs > threshold: %.1fs)",
                    metric_name,
                    age_seconds,
                    self.staleness_threshold_seconds,
                )
                return MetricSample(
                    metric_name=metric_name,
                    value=parsed_value,
                    timestamp=metric_timestamp,
                    status=MetricStatus.STALE,
                    source="prometheus",
                    query=query,
                    unit=unit,
                    freshness_seconds=age_seconds,
                    scrape_target=target_str,
                    error_message=f"Telemetry is stale by {age_seconds:.1f}s (threshold: {self.staleness_threshold_seconds:.1f}s).",
                )

            # Valid, fresh, normalized sample
            return MetricSample(
                metric_name=metric_name,
                value=parsed_value,
                timestamp=metric_timestamp,
                status=MetricStatus.VALID,
                source="prometheus",
                query=query,
                unit=unit,
                freshness_seconds=age_seconds,
                scrape_target=target_str,
                raw_response=data,
            )

        except requests.exceptions.Timeout:
            logger.error("Timeout querying Prometheus for %s (threshold: %.1fs)", metric_name, self.request_timeout_seconds)
            return MetricSample(
                metric_name=metric_name,
                value=None,
                timestamp=now,
                status=MetricStatus.ERROR,
                source="prometheus",
                query=query,
                unit=unit,
                freshness_seconds=0.0,
                error_message=f"Query timed out after {self.request_timeout_seconds:.1f}s while contacting Prometheus.",
            )
        except requests.exceptions.RequestException as e:
            logger.error("Connection error contacting Prometheus for %s: %s", metric_name, e)
            return MetricSample(
                metric_name=metric_name,
                value=None,
                timestamp=now,
                status=MetricStatus.UNAVAILABLE,
                source="prometheus",
                query=query,
                unit=unit,
                freshness_seconds=0.0,
                error_message=f"Cannot reach Prometheus at {self.prometheus_url}: {e}",
            )


class SimulatedTelemetryProvider:
    """
    Explicitly labeled simulated telemetry provider for local demonstration and testing.
    Never presents simulated metrics as real Prometheus measurements.
    """

    def __init__(self, initial_values: Optional[Dict[str, float]] = None):
        self.values = initial_values or {
            "cpu_utilization_percent": 45.0,
            "memory_utilization_percent": 50.0,
            "http_requests_per_second": 80.0,
        }
        self.forced_status: Dict[str, MetricStatus] = {}

    def set_metric(self, name: str, value: Optional[float], status: MetricStatus = MetricStatus.SIMULATED) -> None:
        self.values[name] = value  # type: ignore
        self.forced_status[name] = status

    def query_instant(self, query: str, metric_name: str) -> MetricSample:
        status = self.forced_status.get(metric_name, MetricStatus.SIMULATED)
        val = self.values.get(metric_name)
        unit = METRIC_UNITS.get(metric_name, "%")
        now = time.time()

        if status == MetricStatus.MISSING or val is None:
            return MetricSample(
                metric_name=metric_name,
                value=None,
                timestamp=now,
                status=MetricStatus.MISSING,
                source="SIMULATED",
                query=query,
                unit=unit,
                freshness_seconds=0.0,
                error_message="Metric is missing in simulated dataset",
            )

        if status == MetricStatus.STALE:
            sample_time = now - 120.0
            return MetricSample(
                metric_name=metric_name,
                value=val,
                timestamp=sample_time,
                status=MetricStatus.STALE,
                source="SIMULATED",
                query=query,
                unit=unit,
                freshness_seconds=120.0,
                error_message="Telemetry simulated as stale (age 120s)",
            )

        return MetricSample(
            metric_name=metric_name,
            value=val,
            timestamp=now,
            status=MetricStatus.SIMULATED,
            source="SIMULATED",
            query=query,
            unit=unit,
            freshness_seconds=0.1,
        )


def build_metric_queries(namespace: str, deployment: str) -> Dict[str, str]:
    """
    Generates standard PromQL queries targeted at the application workload.
    Supports:
    1. Kubernetes cAdvisor container infrastructure metrics (CPU quota/usage, Memory working set/limits).
    2. Fallback to process/application-level Prometheus instrumentation via PromQL 'or'.
    """
    return {
        "cpu_utilization_percent": (
            f'(sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}", pod=~"{deployment}-.*"}}[1m])) / '
            f'(sum(container_spec_cpu_quota{{namespace="{namespace}", pod=~"{deployment}-.*"}}) / avg(container_spec_cpu_period{{namespace="{namespace}", pod=~"{deployment}-.*"}})) * 100) '
            f'or (sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}", pod=~"{deployment}-.*"}}[1m])) * 100) '
            f'or sum(sample_app_cpu_utilization_percent{{namespace="{namespace}"}}) '
            f'or sum(sample_app_cpu_utilization_percent)'
        ),
        "memory_utilization_percent": (
            f'(sum(container_memory_working_set_bytes{{namespace="{namespace}", pod=~"{deployment}-.*"}}) / '
            f'sum(container_spec_memory_limit_bytes{{namespace="{namespace}", pod=~"{deployment}-.*"}}) * 100) '
            f'or sum(sample_app_memory_utilization_percent{{namespace="{namespace}"}}) '
            f'or sum(sample_app_memory_utilization_percent)'
        ),
        "http_requests_per_second": (
            f'sum(rate(sample_app_requests_total{{namespace="{namespace}"}}[1m])) '
            f'or sum(rate(sample_app_requests_total[1m]))'
        ),
    }
