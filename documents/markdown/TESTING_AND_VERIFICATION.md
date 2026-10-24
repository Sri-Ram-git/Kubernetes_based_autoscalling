# Testing and Verification Guide: KubePilot

## 1. Test Suite Architecture

KubePilot incorporates a comprehensive automated test suite spanning unit tests, integration tests, API contract tests, and regression safety tests. The test suite is organized into 9 dedicated test modules containing **102 automated test cases**.

```
tests/
├── test_telemetry.py           # 12 tests: Prometheus ingestion, fallback, mocks
├── test_policy_engine.py       # 14 tests: YAML parsing, rule conditions, reset
├── test_decision_controller.py # 15 tests: PRAH arbitration, confidence scoring
├── test_guardrails.py          # 14 tests: Min/Max bounds, step limits, cooldowns
├── test_hysteresis.py          # 10 tests: Sliding window smoothing & flapping
├── test_kubernetes_executor.py # 11 tests: K8s client, scale patching, pod inspection
├── test_dashboard_api.py       # 13 tests: REST routes, health/readiness, status codes
├── test_experiments.py         #  6 tests: Workload generator & benchmark runner
└── test_fixes_regression.py    #  7 tests: Regression guards for resolved bugs
---------------------------------------------------------------------------------
Total: 102 Passing Automated Tests (100% Pass Rate)
```

---

## 2. Test Module Breakdown

### 2.1 `tests/test_telemetry.py`
Validates metric collection across live and mock operational states:
* Prometheus vector query string generation.
* Error handling during Prometheus timeout and unreachable network states.
* Fallback to direct Kubernetes Metrics API (`metrics.k8s.io`).
* Offline mock telemetry generation for deterministic CI testing.
* Schema conformance for metric snapshots (`cpu`, `memory`, `requests_per_sec`, `latency_p95`).

### 2.2 `tests/test_policy_engine.py`
Validates declarative policy evaluation and rule lifecycle:
* YAML syntax loading and schema validation (`scaling-policies.yaml`).
* Relational comparison operators (`>`, `>=`, `<`, `<=`).
* Target replica calculations (absolute, additive offsets, and proportional equations).
* Verification that `reset()` correctly clears rule registries without leaving stale state.
* Handling of missing or partial metric dictionaries.

### 2.3 `tests/test_decision_controller.py`
Tests the core **Policy-Driven Reactive-Arbitration Heuristic (PRAH)**:
* Single rule recommendation arbitration.
* Multi-rule conflict resolution (e.g., CPU requesting scale-up while Memory requests scale-down).
* Directional availability bias: guaranteeing scale-up priority over scale-down.
* Confidence score calculation across metric margin intervals.
* Zero-action NOOP handling when no policy conditions are breached.

### 2.4 `tests/test_guardrails.py`
Verifies hard safety limits and rate constraints:
* **Min Replica Floor:** Absolute enforcement of `min_replicas = 2` under all scale-down requests.
* **Max Replica Ceiling:** Strict capping at `max_replicas = 10` even under extreme simulated surges.
* **Step-Up Clamping:** Ensuring no single scaling action adds more than `+3` pods.
* **Step-Down Clamping:** Ensuring no single scaling action removes more than `-1` pod.
* **Cooldown Timers:** Verifying rejection of scale actions when cooldown windows are active (60s scale-up, 180s scale-down).

### 2.5 `tests/test_hysteresis.py`
Evaluates anti-oscillation and temporal smoothing logic:
* 5-sample sliding window metric evaluation.
* Rejection of premature scale-down actions caused by instantaneous single-tick metric dips.
* Detection and suppression of high-frequency directional reversals (flapping).

### 2.6 `tests/test_kubernetes_executor.py`
Tests Kubernetes cluster mutation and state inspection:
* Kubeconfig discovery and API client initialization.
* Auto-reconnection logic when cluster endpoint becomes temporarily unreachable.
* Successful JSON patch submission to deployment scale subresource.
* Extraction of pod status phases (`Running`, `Pending`, `Failed`) and readiness flags.

### 2.7 `tests/test_dashboard_api.py`
Validates Flask web application endpoints:
* Route availability and 200 OK responses: `/`, `/workloads`, `/telemetry`, `/policies`, `/decisions`, `/history`, `/system-health`.
* JSON REST API contracts: `/api/status`, `/api/metrics`, `/api/decisions`, `/api/policies`, `/api/history`.
* Kubernetes health probes: `/healthz` (200 OK) and `/readyz` (200 OK when policies loaded).
* Error handling and custom 404 template rendering.

### 2.8 `tests/test_experiments.py`
Tests the benchmarking framework:
* Parameter validation for `stable_workload` and `traffic_spike`.
* Execution loop across `baseline` HPA and `proposed` KubePilot modes.
* Metric time-series sampling and CSV/JSON output generation.

### 2.9 `tests/test_fixes_regression.py`
Guarantees against regression of critical project bug fixes:
* Regression test for maintaining the 2-pod baseline replica floor.
* Regression test verifying cooldown lockouts are logged with explicit rationale.
* Regression test confirming removal of deprecated experiment views from the overview page.

---

## 3. Running the Test Suite

### 3.1 Execute Full Test Suite
Run the entire test suite using Pytest:

```powershell
python -m pytest tests/ -v
```

Expected output:
```text
============================= test session starts =============================
platform win32 -- Python 3.13.2, pytest-9.1.1, pluggy-1.6.0
collected 102 items

tests/test_dashboard_api.py .............                                [ 12%]
tests/test_decision_controller.py ...............                        [ 27%]
tests/test_experiments.py ......                                        [ 33%]
tests/test_fixes_regression.py .......                                   [ 40%]
tests/test_guardrails.py ..............                                  [ 53%]
tests/test_hysteresis.py ..........                                      [ 63%]
tests/test_kubernetes_executor.py ...........                           [ 74%]
tests/test_policy_engine.py ..............                               [ 88%]
tests/test_telemetry.py ............                                     [100%]

============================= 102 passed in 1.48s =============================
```

### 3.2 Execute Individual Test Suites
```powershell
# Run PRAH decision controller tests
python -m pytest tests/test_decision_controller.py -v

# Run guardrail and safety tests
python -m pytest tests/test_guardrails.py -v

# Run regression fix tests
python -m pytest tests/test_fixes_regression.py -v
```

### 3.3 Test Coverage Measurement
Measure statement coverage across the controller and dashboard codebases:

```powershell
python -m pytest --cov=controller --cov=dashboard tests/
```

---

## 4. Live Cluster Verification Checklist

In addition to automated unit tests, perform this operational checklist against the running Minikube cluster:

| Verification Item | Command / URL | Expected Result | Verified Status |
| :--- | :--- | :--- | :--- |
| **Namespace Exists** | `kubectl get ns autoscaling-demo` | Status `Active` | PASS |
| **Sample App Running** | `kubectl -n autoscaling-demo get deployment sample-web-app` | `2/2` Ready Replicas | PASS |
| **Prometheus Active** | `curl -s http://localhost:9090/-/healthy` | `Prometheus Server is Healthy.` | PASS |
| **Dashboard UI** | `http://localhost:5055` | 200 OK, Cluster Online | PASS |
| **Readiness Probe** | `curl -s http://localhost:5055/readyz` | `{"status": "ready", "policies_count": 6}` | PASS |
| **Decision Audit Log** | `Get-Content logs/decisions.jsonl` | Structured JSONL records present | PASS |
| **2-Pod Floor Protection** | Trigger low-load scaling | Target clamped at $\ge 2$ | PASS |
| **Step-Up Rate Limit** | Trigger 100% CPU surge | Step capped at $+3$ pods | PASS |
