"""
Unit tests for Prometheus Telemetry ingestion, staleness checking, non-finite handling,
scrape target discovery, and fallback validation.
"""

import math
from unittest.mock import MagicMock, patch
import requests

from controller.telemetry import (
    MetricSample,
    MetricStatus,
    PrometheusTelemetryProvider,
    SimulatedTelemetryProvider,
)


def test_telemetry_valid_response():
    provider = PrometheusTelemetryProvider(
        prometheus_url="http://mock-prom:9090",
        staleness_threshold_seconds=60.0,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {"pod": "sample-web-app-xyz"},
                    "value": [1000.0, "82.4"],
                }
            ],
        },
    }

    with patch.object(provider.session, "get", return_value=mock_resp), patch("time.time", return_value=1020.0):
        # 1020.0 - 1000.0 = 20s age (< 60s)
        sample = provider.query_instant("up", "test_metric", unit="%")

        assert sample.status == MetricStatus.VALID
        assert sample.value == 82.4
        assert sample.unit == "%"
        assert sample.is_usable() is True
        assert sample.error_message is None
        assert sample.freshness_seconds == 20.0


def test_telemetry_stale_response():
    provider = PrometheusTelemetryProvider(
        prometheus_url="http://mock-prom:9090",
        staleness_threshold_seconds=60.0,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {},
                    "value": [1000.0, "75.0"],
                }
            ],
        },
    }

    with patch.object(provider.session, "get", return_value=mock_resp), patch("time.time", return_value=1095.0):
        # 1095.0 - 1000.0 = 95s age (> 60s threshold)
        sample = provider.query_instant("up", "test_metric")

        assert sample.status == MetricStatus.STALE
        assert sample.value == 75.0
        assert sample.is_usable() is False
        assert "stale by 95.0s" in sample.error_message


def test_telemetry_empty_results_marked_missing():
    provider = PrometheusTelemetryProvider(prometheus_url="http://mock-prom:9090")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [],
        },
    }

    with patch.object(provider.session, "get", return_value=mock_resp):
        sample = provider.query_instant("up", "test_metric")

        assert sample.status == MetricStatus.MISSING
        assert sample.value is None
        assert sample.is_usable() is False
        assert "No matching series returned" in sample.error_message


def test_telemetry_non_finite_rejected_as_invalid():
    provider = PrometheusTelemetryProvider(prometheus_url="http://mock-prom:9090")

    # NaN test
    mock_resp_nan = MagicMock()
    mock_resp_nan.status_code = 200
    mock_resp_nan.json.return_value = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {}, "value": [1000.0, "NaN"]}],
        },
    }

    with patch.object(provider.session, "get", return_value=mock_resp_nan), patch("time.time", return_value=1010.0):
        sample_nan = provider.query_instant("up", "test_metric")
        assert sample_nan.status == MetricStatus.INVALID
        assert sample_nan.value is None
        assert sample_nan.is_usable() is False
        assert "Non-finite metric value" in sample_nan.error_message

    # +Inf test
    mock_resp_inf = MagicMock()
    mock_resp_inf.status_code = 200
    mock_resp_inf.json.return_value = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {}, "value": [1000.0, "+Inf"]}],
        },
    }

    with patch.object(provider.session, "get", return_value=mock_resp_inf), patch("time.time", return_value=1010.0):
        sample_inf = provider.query_instant("up", "test_metric")
        assert sample_inf.status == MetricStatus.INVALID
        assert sample_inf.value is None
        assert sample_inf.is_usable() is False
        assert "Non-finite metric value" in sample_inf.error_message


def test_telemetry_http_error_marked_error():
    provider = PrometheusTelemetryProvider(prometheus_url="http://mock-prom:9090")

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    with patch.object(provider.session, "get", return_value=mock_resp):
        sample = provider.query_instant("up", "test_metric")

        assert sample.status == MetricStatus.ERROR
        assert sample.value is None
        assert sample.is_usable() is False
        assert "HTTP 500" in sample.error_message


def test_telemetry_connection_timeout_marked_error():
    provider = PrometheusTelemetryProvider(prometheus_url="http://mock-prom:9090")

    with patch.object(provider.session, "get", side_effect=requests.exceptions.Timeout("Connection timed out")):
        sample = provider.query_instant("up", "test_metric")

        assert sample.status == MetricStatus.ERROR
        assert sample.value is None
        assert "timed out" in sample.error_message


def test_telemetry_connection_error_marked_unavailable():
    provider = PrometheusTelemetryProvider(prometheus_url="http://mock-prom:9090")

    with patch.object(provider.session, "get", side_effect=requests.exceptions.ConnectionError("Refused")):
        sample = provider.query_instant("up", "test_metric")

        assert sample.status == MetricStatus.UNAVAILABLE
        assert sample.value is None
        assert sample.is_usable() is False
        assert "Cannot reach Prometheus" in sample.error_message


def test_scrape_targets_status_parsing():
    provider = PrometheusTelemetryProvider(prometheus_url="http://mock-prom:9090")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "success",
        "data": {
            "activeTargets": [
                {
                    "scrapeUrl": "http://localhost:9090/metrics",
                    "health": "up",
                    "lastScrape": "2026-10-23T16:00:00Z",
                    "lastError": "",
                    "labels": {"job": "prometheus", "instance": "localhost:9090"},
                },
                {
                    "scrapeUrl": "http://localhost:8080/metrics",
                    "health": "down",
                    "lastScrape": "2026-10-23T16:00:01Z",
                    "lastError": "connection refused",
                    "labels": {"job": "sample-web-app", "instance": "localhost:8080"},
                },
            ]
        },
    }

    with patch.object(provider.session, "get", return_value=mock_resp):
        info = provider.get_targets_status()
        assert info["reachable"] is True
        assert info["total_targets"] == 2
        assert info["healthy_targets"] == 1
        assert len(info["targets"]) == 2
        assert info["targets"][0]["health"] == "up"
        assert info["targets"][1]["health"] == "down"


def test_simulated_telemetry_provider_labels():
    sim = SimulatedTelemetryProvider({"cpu_utilization_percent": 65.0})
    sample = sim.query_instant("q", "cpu_utilization_percent")

    assert sample.status == MetricStatus.SIMULATED
    assert sample.source == "SIMULATED"
    assert sample.value == 65.0
    assert sample.is_usable() is True


def test_telemetry_malformed_json_response():
    """Verifies that non-success Prometheus responses are tagged as ERROR."""
    provider = PrometheusTelemetryProvider(prometheus_url="http://mock-prom:9090")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "error",
        "errorType": "execution",
        "error": "many-to-many match not allowed: matching labels must be unique",
    }

    with patch.object(provider.session, "get", return_value=mock_resp):
        sample = provider.query_instant("query_with_error", "cpu_utilization_percent")
        assert sample.status == MetricStatus.ERROR
        assert sample.value is None
        assert sample.is_usable() is False
        assert "error" in sample.error_message


def test_telemetry_malformed_vector_value():
    """Verifies that non-numeric or malformed vector values are rejected safely as INVALID."""
    provider = PrometheusTelemetryProvider(prometheus_url="http://mock-prom:9090")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {},
                    "value": [1000.0, "not_a_valid_number"],
                }
            ],
        },
    }

    with patch.object(provider.session, "get", return_value=mock_resp):
        sample = provider.query_instant("bad_query", "cpu_utilization_percent")
        assert sample.status == MetricStatus.INVALID
        assert sample.value is None
        assert sample.is_usable() is False


def test_telemetry_build_metric_queries():
    """Verifies generated PromQL queries contain expected workload selectors and fallback chains."""
    from controller.telemetry import build_metric_queries
    queries = build_metric_queries(namespace="autoscaling-demo", deployment="sample-web-app")

    assert "cpu_utilization_percent" in queries
    assert "memory_utilization_percent" in queries
    assert "http_requests_per_second" in queries

    # Asserts query targets deployment and namespace properly
    assert 'namespace="autoscaling-demo"' in queries["cpu_utilization_percent"]
    assert 'pod=~"sample-web-app-.*"' in queries["cpu_utilization_percent"]
    assert 'container_spec_cpu_quota' in queries["cpu_utilization_percent"]

    assert 'namespace="autoscaling-demo"' in queries["memory_utilization_percent"]
    assert 'container_spec_memory_limit_bytes' in queries["memory_utilization_percent"]

    assert 'sample_app_requests_total' in queries["http_requests_per_second"]

