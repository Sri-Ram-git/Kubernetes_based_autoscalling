# KubePilot – Complete Implementation Audit, Product Readiness Assessment & Remaining Work

**Project:** KubePilot  
**Project Title:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications  
**Audited Repository:** `C:\Users\SRIRAM\design_project\`  
**Auditor Roles:** Senior Kubernetes Architect, Cloud Platform Engineer, DevOps Engineer, Backend Engineer, Technical Product Auditor  
**Audit Date:** 2026-11-01  
**Audit Standard:** Zero Assumptions, Strictly Evidence-Based (Gemini 3.8 Audit Standard)  

---

## 1. Executive Summary

A comprehensive, read-only architectural, functional, security, and verification audit of the **KubePilot** codebase was executed on 2026-11-01.

### 1.1 Core Verdict & Bottom-Line Assessment

KubePilot contains a **well-conceived, modular algorithmic core** for rule-based, deterministic auto-scaling based on the **PRAH (Priority-based Rule Arbitration with Hysteresis)** concept. The mathematical rule evaluation, multi-policy priority ranking, tie-breaking logic, operational guardrails (bounds and step clamps), and JSON Lines audit logger are cleanly written in Python.

However, the framework currently exists primarily as a **standalone Python controller and web dashboard designed for local prototyping and mock demonstrations**, rather than a fully verified, integrated Kubernetes product. 

When audited against live cluster execution and production readiness criteria:
1. **Live Integration is Offline & Unverified:** The local Docker engine and Minikube cluster are stopped. The host `~/.kube/config` contains `contexts: null`. Live cluster communication, active scraping, and real pod mutation could not be verified in this session.
2. **Critical Defect in Kubernetes Executor:** An unhandled attribute initialization bug in `controller/kubernetes_executor.py` (`self._core_v1_api` is omitted from `__init__`) causes unit and mock tests to fail with `AttributeError: 'KubernetesExecutor' object has no attribute '_core_v1_api'` whenever `~/.kube/config` lacks valid context objects, silently flipping cluster connectivity to offline.
3. **Split-Brain Architecture in Containerized / Kubernetes Deployments:** When deployed via `k8s/controller-deployment.yaml` and `k8s/dashboard-deployment.yaml`, the Controller and the Dashboard run as two completely independent pods. Each maintains its own in-memory controller instance, in-memory cooldown state, in-memory telemetry cache, and local ephemeral audit log. UI controls (such as "Enable Live Execution" or manual scaling) mutate only the dashboard pod's local memory and have **zero effect** on the controller pod.
4. **Capacity Validation is Completely Absent:** The system contains zero lines of code inspecting node allocatable CPU/memory, existing pod requests, node schedulability, or pending pod states. It delegates 100% of placement authority to the Kubernetes scheduler and assumes infinite cluster capacity.
5. **Benchmark Experiments Failed to Demonstrate Scaling:** Inspection of the preserved empirical benchmark data in `experiments/results/` (`exp-stable_workload-20261024-074249.json` and `exp-traffic_spike-20261024-074350.json`) reveals that during the "traffic spike" test, CPU utilization reached only 0.44% (well below the 75%/80% scaling thresholds), 47% of requests failed, zero scaling events occurred, and replica counts remained static at 2 for both native HPA and KubePilot.
6. **Docker Compose & ConfigMap Write Inconsistencies:** `docker-compose.yaml` mounts a Kubernetes ConfigMap YAML (`monitoring/prometheus-config.yaml`) directly into Prometheus, which will fail to boot due to schema mismatch. In Kubernetes manifests, `/app/policies` is mounted as a read-only ConfigMap volume, which will crash the dashboard's policy editing API with `OSError: [Errno 30] Read-only file system`.

---

## 2. Actual Repository Architecture

### 2.1 Discovered Component Topology

```
+--------------------------------------------------------------------------------------------------+
|                                    OPERATOR / BROWSER CLIENT                                     |
+--------------------------------------------------------------------------------------------------+
                                                 |
                       HTTP / REST (Port 5055/5000) & Server-Side Rendered Templates
                                                 v
+--------------------------------------------------------------------------------------------------+
|                                     DASHBOARD SERVICE POD                                        |
|  dashboard/app.py (Flask 3.1.3, Jinja2 templates, static vanilla JS dashboard.js)                |
|  - In-process Controller instance: AutoscalingController (evaluates on-demand or single cycle)    |
|  - Policies API: Reads/writes policies/scaling-policies.yaml directly                            |
|  - Workload Scale API: Coordinates guarded manual scaling                                        |
+--------------------------------------------------------------------------------------------------+
         |                                                                |
         | (Shared file path in local dev;                                | PromQL HTTP
         |  DISCONNECTED in multi-pod k8s!)                               v
         v                                                +-------------------------------+
+---------------------------------------------+           |      PROMETHEUS SERVER        |
|          CONTROLLER SERVICE POD             |           |  Port 9090                    |
|  controller/main.py                         |           |  - Active scrape targets      |
|  - start_loop() evaluation every 10s        |           |  - cAdvisor & pod metrics     |
|  - Telemetry: PrometheusTelemetryProvider   |<----------+-------------------------------+
|  - Rules: PolicyEngine                      |                           ^
|  - Arbitration: DecisionController (PRAH)   |                           | Scrapes :8080/metrics
|  - Safety: GuardrailEngine                  |                           |
|  - Coordination: StrategyCoordinator        |           +-------------------------------+
|  - Execution: KubernetesExecutor            |           |    TARGET WORKLOAD POD(S)     |
|  - Persistence: DecisionLogger (.jsonl)     |           |  app/app.py (Flask 3.1.3)     |
+---------------------------------------------+           |  Deployment: sample-web-app   |
         |                                                |  Namespace: autoscaling-demo  |
         | Kubernetes REST API                            +-------------------------------+
         v                                                                ^
+-------------------------------------------------------------------------+------------------------+
|                                      KUBERNETES CONTROL PLANE                                    |
|  - apps/v1: deployments, deployments/scale (Patches spec.replicas)                               |
|  - core/v1: pods (Queries readiness and restart status)                                         |
|  - autoscaling/v2: horizontalpodautoscalers (Collision detection)                                |
+--------------------------------------------------------------------------------------------------+
```

### 2.2 Discovered File and Directory Map

| Path | Primary Responsibility | Connected Components |
|---|---|---|
| `app/app.py` | Sample microservice instrumented with Prometheus client (`/metrics`, `/load`, `/generate-traffic`, `/healthz`, `/readyz`). | Prometheus, Kubernetes Deployment |
| `app/sample-app.yaml` | Kubernetes Deployment and ClusterIP Service manifests for `sample-web-app`. | Minikube, Kubernetes API |
| `controller/config.py` | Dataclass `ControllerConfig` managing environment variables, fallback defaults, and absolute path anchoring. | All controller modules, `dashboard/app.py` |
| `controller/decision_controller.py` | PRAH decision algorithm: telemetry health gating, priority ranking, tie-breaking, hysteresis, cooldowns. | `PolicyEngine`, `TelemetryProvider`, `GuardrailEngine` |
| `controller/decision_logger.py` | Thread-safe audit logger writing normalized JSON Lines to `logs/decisions.jsonl` and keeping in-memory deque. | `dashboard/app.py`, `controller/main.py` |
| `controller/experiment_runner.py` | Background runner for Stable Workload & Traffic Spike comparative experiments; synthetic workload generator. | `KubernetesExecutor`, `PrometheusTelemetryProvider` |
| `controller/guardrails.py` | Operational bounds checking (`min_replicas`, `max_replicas`, step clamps, duplicate action suppression). | `StrategyCoordinator`, `DecisionController` |
| `controller/kubernetes_executor.py` | Kubernetes API client (AppsV1Api, CoreV1Api) for deployment inspection, scale subresource patching, and verification. | Kubernetes API, `StrategyCoordinator` |
| `controller/main.py` | CLI entry point and continuous polling loop (`start_loop()`) running every 10 seconds. | All controller modules |
| `controller/policy_engine.py` | Parser and mathematical condition evaluator for `scaling-policies.yaml`. | `scaling-policies.yaml`, `DecisionController` |
| `controller/strategy_coordinator.py` | Scaling mechanism coordinator; checks native HPA collision and delegates to `GuardrailEngine` and `KubernetesExecutor`. | `KubernetesExecutor`, `GuardrailEngine` |
| `controller/telemetry.py` | Ingestion, validation, staleness checking, and PromQL query builder for Prometheus metrics. | Prometheus API, `DecisionController` |
| `dashboard/app.py` | Flask REST API and web application server exposing dashboard routes and API endpoints. | Controller modules, `dashboard.js`, templates |
| `dashboard/static/js/dashboard.js` | Client-side frontend JavaScript handling polling, modal dialogs, status badges, and user interactions. | `dashboard/app.py` REST endpoints |
| `dashboard/templates/*.html` | Jinja2 HTML templates for Overview, Workloads, Telemetry, Policies, Decisions, History, and System Health. | `dashboard/app.py` |
| `experiments/results/*.json|.csv` | Persisted empirical output files from past benchmark runs. | `ExperimentManager` |
| `k8s/*.yaml` | Kubernetes manifests for namespace, RBAC, ConfigMaps, controller deployment, dashboard deployment, and baseline HPA. | Kubernetes cluster |
| `monitoring/*.yaml|.yml` | Prometheus configuration, Deployment manifest, and local Prometheus Windows binary bundle. | Prometheus, Kubernetes |
| `policies/scaling-policies.yaml` | Declarative YAML configuration containing workload target, guardrails, fallback behavior, and 6 scaling policies. | `PolicyEngine`, `ControllerConfig` |
| `tests/*.py` | Pytest test suite containing 102 collected tests across 9 test files. | Python pytest test runner |

---

## 3. Complete Module-by-Module Implementation Matrix

The table below provides a strictly audited assessment of every system module.

| Module | Core Files | Responsibility | Verified Functionality | Broken / Incomplete Aspects | Audit Status |
|---|---|---|---|---|---|
| **Monitoring & Metrics** | `controller/telemetry.py`, `monitoring/prometheus.yml` | Prometheus HTTP query, response normalization, metric extraction. | PromQL query construction (`build_metric_queries`), numerical parsing, timeout handling. | Live Prometheus instance is offline. Static Windows YAML has hardcoded pod label `sample-web-app-5858cfd795-x9z4p`. | **PARTIALLY IMPLEMENTED** |
| **Telemetry Processing** | `controller/telemetry.py` | Metric validation, staleness detection, non-finite rejection, safe state classification. | Rejection of NaN/Inf, enforcement of `staleness_threshold_seconds`, categorization of VALID/MISSING/STALE/INVALID/UNAVAILABLE. | Works in unit tests; unverified against high-throughput live Prometheus stream. | **IMPLEMENTED, NOT VERIFIED** |
| **Policy Engine** | `controller/policy_engine.py`, `policies/scaling-policies.yaml` | YAML parsing, schema validation, multi-rule evaluation against telemetry vector. | Boundary checking (`>`, `<`, `>=`, `<=`), duration persistence, deterministic evaluation, atomic YAML file persistence. | Rule duration persistence (`_breach_timestamps`) is held in-memory and lost upon process restart. | **IMPLEMENTED, NOT VERIFIED** |
| **Decision Controller (PRAH)** | `controller/decision_controller.py` | Multi-rule arbitration, priority sorting, tie-breaking, direction-flip hysteresis, cooldowns. | Telemetry failure fallback to HOLD, highest priority selection, scale-out preference on tie, anti-flapping direction delay. | Cooldown state is held in-memory; lost upon pod restart. No persistence of decision controller state. | **IMPLEMENTED, NOT VERIFIED** |
| **Strategy Coordinator** | `controller/strategy_coordinator.py` | Scale mechanism selection, native HPA conflict detection, execution delegation. | Queries `AutoscalingV2Api` to detect competing HPAs targeting the same deployment; aborts on conflict. | Only supports direct Deployment scale patching. No VPA or KEDA integration. | **IMPLEMENTED, NOT VERIFIED** |
| **Guardrails Engine** | `controller/guardrails.py` | Operational constraint enforcement (`min/max` bounds, step clamping, dry-run flags). | Strict `min_replicas` and `max_replicas` boundary enforcement, step clamping, duplicate action filtering. | Step size limits only clamp delta; do not account for cluster-wide node constraints. | **IMPLEMENTED, NOT VERIFIED** |
| **Kubernetes Executor** | `controller/kubernetes_executor.py` | Kubernetes API communication, pod listing, deployment scale patching, verification polling. | Dry-run preview execution, simulated fallback workload state, retry logic. | **BROKEN:** Missing `self._core_v1_api = None` in `__init__` crashes with `AttributeError` when kubeconfig contexts are missing. Verification only checks `spec.replicas`, not `ready_replicas`. | **BROKEN** |
| **Capacity Validation** | N/A | Node allocatable resource verification, pod scheduling feasibility, pending pod checks. | None. | **COMPLETELY ABSENT.** No node inspection, no schedulability checks, no allocatable CPU/RAM calculations. | **NOT IMPLEMENTED** |
| **Audit Logger & Persistence** | `controller/decision_logger.py`, `logs/decisions.jsonl` | Structured JSON Lines audit logging, memory buffer, deduplication. | Atomic append to `logs/decisions.jsonl`, in-memory deque buffer, normalization of decision records. | Ephemeral in Kubernetes container. No rotation, retention policy, or centralized storage. | **PARTIALLY IMPLEMENTED** |
| **Experiment Runner** | `controller/experiment_runner.py`, `experiments/results/` | Automated benchmark suite for Stable Workload and Sudden Traffic Spike. | Subprocess execution of `kubectl apply/delete/scale`, synthetic workload generation, JSON/CSV export. | Experiments recorded in `experiments/results/` failed to generate adequate load to trigger scaling (CPU 0.44%). | **PARTIALLY IMPLEMENTED** |
| **Dashboard UI & API** | `dashboard/app.py`, `dashboard/static/js/dashboard.js`, templates | Operator web interface, metrics visualization, policy management, manual scaling. | Page rendering, REST error handling in JSON, modal forms for policy CRUD, status pills. | No continuous background loop in dashboard process. Read-only ConfigMap mount in k8s blocks policy editing. `/experiments` UI removed. | **PARTIALLY IMPLEMENTED** |
| **Cluster Manifests** | `k8s/*.yaml`, `docker-compose.yaml` | Kubernetes RBAC, Deployments, Services, ConfigMaps, Docker Compose. | Syntax is valid Kubernetes YAML. RBAC role correctly restricts permissions. | `docker-compose.yaml` mounts k8s ConfigMap into Prometheus. RBAC lacks Node read permissions. Ephemeral storage for logs. | **PARTIALLY IMPLEMENTED** |

---

## 4. Evidence and Verification Report

### 4.1 Pytest Test Suite Execution Evidence

The test suite was executed in the workspace using the local Python 3.13.14 environment:
- **Command:** `python -m pytest -v`
- **Total Tests Collected:** 102
- **Passed:** 99
- **Skipped:** 1 (`tests/test_fixes_regression.py::test_case_5_live_scaling_real_deployment_mutation` — skipped because Minikube cluster was offline)
- **Failed:** 2 (`tests/test_fixes_regression.py::test_case_6_failed_kubernetes_request_preserves_actual_state` and `tests/test_kubernetes_executor.py::test_live_scaling_verification_success`)
- **Execution Duration:** 117.20 seconds

#### Failure Analysis & Root Cause Evidence

Both test failures trace directly to an identical bug in `controller/kubernetes_executor.py`:

```python
# controller/kubernetes_executor.py (lines 79-84)
        self._apps_v1_api = None
        self._connected = False
        self._connection_error: Optional[str] = None
        self._simulated_replicas = 2  # Used when running without live cluster

        self._initialize_client()
```

Notice that `self._core_v1_api` is **not initialized** before calling `_initialize_client()`.
In `_initialize_client()` (lines 110-126):
```python
            # Try local kubeconfig
            config.load_kube_config(config_file=self.kubeconfig_path)
            k8s_conf = client.Configuration.get_default_copy()
            ...
            self._apps_v1_api = client.AppsV1Api(api_client)
            self._core_v1_api = client.CoreV1Api(api_client)
            self._connected = True
        except Exception as e:
            self._connected = False
            self._connection_error = f"Kubernetes initialization error: {str(e)}"
```

When `load_kube_config()` throws an exception (due to `~/.kube/config` containing `contexts: null`), execution jumps directly to `except Exception:`. Consequently, `self._core_v1_api` **is never added to `self` as an attribute**.

Subsequently, in `get_workload_state()` (line 191):
```python
        # Query individual pod readiness if core API is available
        pod_list = []
        if self._core_v1_api:
```
Because `self._core_v1_api` was never set on `self`, accessing it raises:
`AttributeError: 'KubernetesExecutor' object has no attribute '_core_v1_api'`

This error is caught by the blanket `except Exception as e:` at line 249 of `kubernetes_executor.py`:
```python
        except Exception as e:
            self._connected = False
            msg = f"Cluster connection offline: {str(e)[:80]}..."
            logger.debug(msg)
            return WorkloadState(...)
```
This silently overrides `self._connected = False`, causing mock-based tests and subsequent scaling calls to fail with:
`ExecutionResult(success=False, ..., message='Cannot execute live scaling: Kubernetes cluster connection is unavailable.')`

**Independent Verification:** Running a direct reproduction script confirmed that setting `ex._core_v1_api = None` in `__init__` resolves the attribute error and allows both mock tests to pass completely.

---

## 5. What Is Working Well – Do Not Disturb

The following components and architectural choices are properly implemented, well-structured, and technically sound. **They should not be disturbed during future development:**

1. **PRAH Arbitration Algorithm (`controller/decision_controller.py`):**
   - Clean, deterministic multi-rule arbitration.
   - Exact tie-breaking logic prioritizing scale-out over scale-in when priorities are equal (lines 212-221) to protect workload availability.
   - Conservative scale-in resolution picking the smallest contraction delta among equal-priority scale-in proposals (lines 231-237).
   - Strict telemetry degradation fail-safe: if any metric evaluated by policies is marked `MISSING`, `STALE`, `INVALID`, or `ERROR`, the decision is immediately converted to `HOLD` with a clear explanation (lines 137-156).

2. **Metric Safety & Normalization Model (`controller/telemetry.py`):**
   - Clean enumeration `MetricStatus` (VALID, MISSING, STALE, ERROR, SIMULATED, INVALID, UNAVAILABLE).
   - Explicit `is_usable()` method (lines 65-75) that strictly rejects `NaN`, `+Inf`, `-Inf`, missing values, and stale data.
   - Missing metrics are **never** silently fabricated as zero.
   - Freshness tracking calculates elapsed seconds since Prometheus scrape timestamp and compares against `staleness_threshold_seconds`.

3. **Declarative Policy Schema & Atomic Persistence (`controller/policy_engine.py` & `dashboard/app.py`):**
   - Mathematical boundary conditions (`>`, `>=`, `<`, `<=`, `==`, `!=`) evaluated explicitly using Python's `operator` module.
   - Comprehensive semantic validation rejecting duplicate IDs, negative scale-out deltas, positive scale-in deltas, non-finite thresholds, and percentages outside `[0.0, 100.0]`.
   - Atomic file updates in `dashboard/app.py` (`_persist_policy_document`, lines 72-89) write to a temporary file in the target directory and execute an atomic `os.replace`, preventing configuration file corruption.

4. **Operational Guardrail Bounds (`controller/guardrails.py`):**
   - Enforces strict lower (`min_replicas >= 1`) and upper (`max_replicas`) bounds.
   - Clamps scale-out steps to `max_scale_step_up` and scale-in steps to `max_scale_step_down`.
   - Filters redundant actions where `target_replicas == current_replicas`.
   - Distinct separation between proposal authorization (`GuardrailResult`) and cluster mutation (`ExecutionResult`).

5. **Competing Autoscaler Collision Protection (`controller/strategy_coordinator.py`):**
   - Actively checks `AutoscalingV2Api` for existing native Kubernetes `HorizontalPodAutoscaler` objects targeting the same deployment (lines 47-74).
   - Aborts execution with a clear conflict error if a native HPA is present, preventing dual-controller thrashing.

6. **Structured Audit Trail (`controller/decision_logger.py`):**
   - Thread-safe append-only persistence to `logs/decisions.jsonl`.
   - Truthful outcome tagging (`PROPOSED`, `BLOCKED`, `DRY_RUN`, `EXECUTED`, `VERIFIED`, `FAILED`).
   - Clean normalization preventing duplicate logs from dashboard polling refreshes.

7. **Dashboard UI Visual Design and Error Hygiene:**
   - Dark-mode, accessible web interface styled with custom CSS (`dashboard/static/css/style.css`).
   - All REST API endpoints return structured JSON errors (`{"error": "...", "status": ...}`) even during 400/404/500 conditions (`dashboard/app.py:804-816`).
   - UI explicitly reflects whether telemetry is `PROMETHEUS` or `SIMULATED`, and whether the cluster connection is `Live` or `Offline`.

---

## 6. Problems, Risks and Incomplete Implementations

The audit identified several critical and high-severity architectural, functional, and operational defects.

### 6.1 Issue Matrix

| Issue | Severity | Evidence | Actual Impact | Recommended Correction | Dependencies |
|---|---|---|---|---|---|
| **Uninitialized `_core_v1_api` Attribute Bug** | **CRITICAL** | `controller/kubernetes_executor.py:79-84` lacks `self._core_v1_api = None`. | When kubeconfig lacks valid context, accessing `_core_v1_api` raises `AttributeError`, causing `get_workload_state()` to silently drop cluster connection to offline. Breaks unit tests and live verification. | Add `self._core_v1_api: Optional[Any] = None` in `KubernetesExecutor.__init__` before `_initialize_client()`. | None |
| **Split-Brain Architecture (Controller vs Dashboard)** | **CRITICAL** | `k8s/controller-deployment.yaml` and `k8s/dashboard-deployment.yaml` run separate pods with separate in-memory `AutoscalingController` instances. | Operator changes in UI (live execution toggle, threshold edits, manual scaling) do not reach the autonomous controller pod. Autonomous controller decisions do not appear in dashboard. | Refactor dashboard to act purely as an API gateway / client to a single controller daemon, or use a shared state store (e.g., Redis, etcd, or unified backend service). | Architecture Refactoring |
| **Read-Only ConfigMap Mounts in Kubernetes** | **HIGH** | `k8s/dashboard-deployment.yaml:46-52` mounts `scaling-policies-cm` at `/app/policies`. | Kubernetes ConfigMaps are mounted read-only. Calling `POST /api/policies` or `PUT /api/policies/<id>` in container throws `OSError: [Errno 30] Read-only file system`. | Store dynamic policies in a PersistentVolumeClaim, Kubernetes Custom Resource Definition (CRD), or database instead of mounting ConfigMap directly to write path. | K8s Manifests |
| **Docker Compose ConfigMap Schema Error** | **HIGH** | `docker-compose.yaml:10` mounts `./monitoring/prometheus-config.yaml` to `/etc/prometheus/prometheus.yml`. | `prometheus-config.yaml` is a Kubernetes ConfigMap containing metadata, not raw Prometheus YAML. Prometheus container fails on boot. | Update `docker-compose.yaml` to mount `./monitoring/prometheus.yml` instead. | `docker-compose.yaml` |
| **Capacity Validation is Completely Missing** | **HIGH** | `controller/` contains zero queries for node allocatable resources, node capacity, or pending pods. | Scale-out commands execute even when nodes have no CPU/memory capacity. Pods become stuck in `Pending` without controller detection. | Implement node capacity checks querying `v1Node.status.allocatable` and summing existing pod resource requests before authorizing scale-out. | Kubernetes API |
| **Execution Verification Only Checks Spec Replicas** | **HIGH** | `controller/kubernetes_executor.py:348-354` verifies scaling by checking `current_state.desired_replicas == target_replicas`. | Scaling is marked "VERIFIED" immediately after spec is patched, even if pods crash (`CrashLoopBackOff`), fail to schedule (`Pending`), or fail readiness probes. | Update verification loop to wait for `ready_replicas == target_replicas` or check rollout status (`status.observedGeneration >= metadata.generation`). | `KubernetesExecutor` |
| **Experiments Failed Under Real Load** | **HIGH** | `experiments/results/exp-traffic_spike-20261024-074350.json` shows CPU remained at 0.36%-0.44%; 34 of 72 requests failed; zero scaling events occurred. | Academic claims of benchmark superiority over HPA are unsupported by the saved empirical data. Peak replicas remained 2 for both systems. | Fix workload generator networking (use reachable cluster service endpoint), tune synthetic CPU burn loop, and re-run experiments until scaling thresholds (>75%) are actually breached. | Minikube, Target Workload |
| **In-Memory State Loss on Pod Restart** | **MEDIUM** | `controller/decision_controller.py:82-85` stores `last_action_timestamp`, `last_action_direction`, and `active_cooldown_seconds` in instance attributes. | Restarting the controller pod resets cooldowns and hysteresis delay, allowing immediate opposite scaling actions (flapping). | Persist controller runtime state into a lightweight state file (e.g. `logs/state.json`) or Redis. | `DecisionController` |
| **Missing `/experiments` Web Page** | **MEDIUM** | `dashboard/templates/` lacks `experiments.html`; `tests/test_experiments.py:165` asserts `/experiments` returns 404. | Operators cannot view, trigger, or monitor experiments from the dashboard; functionality is restricted to CLI. | Create `dashboard/templates/experiments.html` and connect it to `/api/experiments` endpoints. | Frontend Templates |
| **Static Hardcoded Pod Label in Prometheus Config** | **LOW** | `monitoring/prometheus.yml:20` has hardcoded pod label `sample-web-app-5858cfd795-x9z4p`. | When running Prometheus locally on Windows, metrics are tagged with an obsolete, nonexistent pod name. | Remove hardcoded label or dynamically discover running pod names. | Prometheus Config |

---

## 7. Frontend and Backend Connectivity Audit

Every interactive button, form, and page in the dashboard was traced from the Jinja2 template and client-side JavaScript (`dashboard.js`) through the Flask backend (`dashboard/app.py`) to the underlying controller and Kubernetes/Prometheus integration.

### 7.1 Page and Route Audit

| Page Route | Template | JavaScript Handler | Backend Endpoint(s) | Underlying Component | Connectivity Status | Notes |
|---|---|---|---|---|---|---|
| `/` or `/overview` | `overview.html` | `fetchStatus()`, `fetchMetrics()`, `fetchDecisions()`, `fetchHistory()` | `/api/status`, `/api/metrics`, `/api/decisions`, `/api/history` | `KubernetesExecutor`, `PrometheusProvider`, `DecisionController`, `DecisionLogger` | **VERIFIED CONNECTED (Local Backend)** | Correctly pulls real data or falls back gracefully to offline state indicators. |
| `/workloads` | `workloads.html` | `fetchWorkloads()`, `handleManualScale(e)` | `/api/workloads`, `/api/workloads/scale` | `KubernetesExecutor`, `StrategyCoordinator` | **VERIFIED CONNECTED (Local Backend)** | Submits guarded scale requests. Blocks with HTTP 409 if cluster is offline. |
| `/telemetry` | `telemetry.html` | `fetchMetrics()`, `refreshTelemetry()`, `simulateMetric()` | `/api/metrics`, `/api/telemetry/refresh`, `/api/controls/simulate-metric` | `PrometheusTelemetryProvider`, `SimulatedTelemetryProvider` | **VERIFIED CONNECTED (Local Backend)** | Interactive simulation controls inject test values into in-memory provider. |
| `/policies` | `policies.html` | `fetchPolicies()`, `savePolicy()`, `togglePolicy()`, `updateThreshold()` | `GET/POST /api/policies`, `PUT /api/policies/<id>`, `PATCH /api/policies/<id>/enabled`, `POST /api/policies/update-threshold` | `PolicyEngine`, `scaling-policies.yaml` | **VERIFIED CONNECTED (Local Backend)** | Persists atomically to disk. Fails if mounted as read-only ConfigMap in k8s. |
| `/decisions` | `decisions.html` | `fetchDecisions()`, `triggerEvaluation()`, `toggleLiveExecution()`, `resetCooldown()` | `/api/decisions`, `/api/evaluate`, `/api/controls/live-execution`, `/api/controls/reset-cooldown` | `AutoscalingController`, `DecisionController` | **VERIFIED CONNECTED (Local Backend)** | Single-cycle trigger works. Does not affect external `controller.main` process. |
| `/history` | `history.html` | `fetchHistory()` | `/api/history?limit=30` | `DecisionLogger`, `logs/decisions.jsonl` | **VERIFIED CONNECTED (Local Backend)** | Displays formatted audit log records. |
| `/system-health` | `system_health.html` | `fetchStatus()` | `/api/status`, `/api/telemetry/targets` | `PrometheusTelemetryProvider`, `KubernetesExecutor` | **VERIFIED CONNECTED (Local Backend)** | Diagnostics view inspecting scrape target health and API reachability. |
| `/experiments` | *None* | `fetchExperiments()`, `startExperiment()`, `stopExperiment()` in `dashboard.js` | `/api/experiments`, `/api/experiments/<id>/run`, `/api/experiments/stop` | `ExperimentManager`, `WorkloadGenerator` | **UI ONLY / ORPHANED API** | API routes exist, but HTML template was removed. Returns 404. |

---

## 8. Kubernetes and Prometheus Live Integration Audit

An environmental audit was performed on the host machine to assess live cluster and telemetry integration.

### 8.1 Environmental Inspection Findings

1. **Docker Engine:**
   - **Command:** `minikube status`
   - **Evidence:** `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine... The system cannot find the file specified.`
   - **Verdict:** Docker Desktop Linux Engine is **stopped**.

2. **Kubernetes Cluster (Minikube):**
   - **Command:** `kubectl cluster-info`
   - **Evidence:** `Unable to connect to the server: dial tcp [::1]:8080: connectex: No connection could be made because the target machine actively refused it.`
   - **Context Inspection:** `kubectl config get-contexts` returned an empty table. `C:\Users\SRIRAM\.kube\config` has `clusters: null`, `contexts: null`, `current-context: ""`.
   - **Verdict:** Minikube is **not running**, and no active Kubernetes cluster context is configured.

3. **Prometheus Server:**
   - **Command:** `Get-NetTCPConnection -State Listen` for ports 9090, 8000, 8080, 5000.
   - **Evidence:** No listeners found on port 9090.
   - **Verdict:** Prometheus is **not running**.

4. **Sample Application Workload:**
   - No listeners found on port 8080.
   - **Verdict:** Sample application workload is **offline**.

5. **Current Operating State of the Framework:**
   - In accordance with Rule 3 and Rule 5, live cluster integration is classified as **BLOCKED / OFFLINE**.
   - The framework gracefully falls back to local simulation mode when queries are initiated in the dashboard.

---

## 9. Experiment and Benchmark Completion Audit

The project specification mandates two standardized benchmark experiments comparing native Kubernetes HPA against KubePilot:

1. **Experiment 1: Stable Workload** (10–30 req/s constant load).
2. **Experiment 2: Sudden Traffic Spike** (abrupt surge driving CPU >80%).

### 9.1 Audit of Preserved Benchmark Results (`experiments/results/`)

Six JSON result files and six CSV time-series files were inspected in `experiments/results/`:
- `exp-stable_workload-20261024-060551.json` / `.csv`
- `exp-stable_workload-20261024-072157.json` / `.csv`
- `exp-stable_workload-20261024-074249.json` / `.csv`
- `exp-traffic_spike-20261024-060718.json` / `.csv`
- `exp-traffic_spike-20261024-072306.json` / `.csv`
- `exp-traffic_spike-20261024-074350.json` / `.csv`

#### Detailed Audit of Experiment 2 (Traffic Spike: `exp-traffic_spike-20261024-074350.json`)

The preserved JSON artifact claims to demonstrate KubePilot's response to an abrupt traffic spike. Inspection of the raw telemetry vectors revealed:

```json
  "baseline_result": {
    "duration_seconds": 35.6,
    "initial_replicas": 2,
    "peak_replicas": 2,
    "final_replicas": 2,
    "scaling_events_count": 0,
    "time_to_first_scale_seconds": null,
    "max_cpu_percent": 0.44,
    "avg_cpu_percent": 0.37,
    "total_requests_sent": 72,
    "successful_requests": 38,
    "failed_requests": 34
  },
  "proposed_result": {
    "duration_seconds": 36.2,
    "initial_replicas": 2,
    "peak_replicas": 2,
    "final_replicas": 2,
    "scaling_events_count": 0,
    "time_to_first_scale_seconds": null,
    "max_cpu_percent": 0.36,
    "avg_cpu_percent": 0.33,
    "total_requests_sent": 72,
    "successful_requests": 48,
    "failed_requests": 24
  },
  "comparison_summary": {
    "baseline_peak_replicas": 2,
    "proposed_peak_replicas": 2,
    "baseline_scale_latency_seconds": null,
    "proposed_scale_latency_seconds": null,
    "scale_latency_improvement_seconds": null,
    "baseline_scaling_events": 0,
    "proposed_scaling_events": 0
  }
```

### 9.2 Critical Audit Findings on Experiments

1. **Failure to Induce Load:** In both the baseline HPA and proposed KubePilot runs, CPU utilization never exceeded **0.44%** (0.0044 of pod quota). The scale-out policy threshold is **75.0%** (with critical spike at **90.0%**). Because the workload generator failed to generate actual load on the cluster, the threshold was never breached.
2. **Zero Scaling Events Occurred:** `scaling_events_count` was **0** for both systems. Both systems remained at exactly **2 replicas** throughout the entire test.
3. **Key Benchmark Metrics are Null:** `time_to_first_scale_seconds` and `scale_latency_improvement_seconds` are both `null`.
4. **Severe Request Failure Rate:** Out of 72 HTTP requests, 34 failed (47.2%) during baseline and 24 failed (33.3%) during proposed runs, indicating network connection timeouts or misconfigured target URLs (`http://localhost:8080`) rather than application overload.
5. **Documentation Discrepancy:** `documents/markdown/EXPERIMENTS_AND_EVALUATION.md` presents these results as evidence of superior scaling stability and lower latency, claiming KubePilot used "Composite: Latency + Throughput" arbitration, despite the fact that no latency policies exist in the policy configuration and no scaling occurred.

**Verdict:** The benchmark execution engine is **PARTIALLY IMPLEMENTED**, but valid empirical demonstration of auto-scaling under load is **INCOMPLETE AND UNVERIFIED**.

---

## 10. Product Scalability Assessment

To evaluate KubePilot beyond an academic demonstration, 20 production-grade architectural dimensions were analyzed:

| Dimension | Classification | Detailed Technical Assessment |
|---|---|---|
| **1. Multiple Application Workloads** | **Not Implemented** | `ControllerConfig` hardcodes a single `target_namespace` and `target_deployment`. Cannot scale multiple deployments concurrently. |
| **2. Multiple Namespaces** | **Not Implemented** | Controller RBAC and configuration are locked to a single namespace. Multi-tenancy is unsupported. |
| **3. Multiple Clusters** | **Not Implemented** | Uses a single static `kubeconfig` client. No federation or multi-cluster context switching. |
| **4. Multiple Kubernetes Environments** | **Partially Implemented** | Supports in-cluster ServiceAccount authentication and out-of-cluster kubeconfig, but lacks cloud IAM (EKS IRSA, GKE Workload Identity) testing. |
| **5. Concurrent Policy Evaluation** | **Implemented, Not Verified** | Evaluates all loaded rules synchronously in a single thread across the telemetry snapshot. Fast for small rule sets; untested for hundreds of policies. |
| **6. Controller Scalability** | **Partially Implemented** | Single-threaded polling loop (`start_loop()`). Thread-safe locks exist, but no horizontal scaling or sharding mechanism. |
| **7. High Availability & Leader Election** | **Not Implemented** | No Kubernetes Lease-based leader election (`coordination.k8s.io`). Running `replicas > 1` in `controller-deployment.yaml` will cause split-brain thrashing. |
| **8. Persistent Decision History** | **Partially Implemented** | Writes to local flat file `logs/decisions.jsonl`. In Kubernetes, logs are lost on pod restart unless a PVC is mounted. |
| **9. Controller Restart Recovery** | **Partially Implemented** | Preloads recent history from JSON Lines file, but cooldown and duration timers are kept in-memory and lost upon restart. |
| **10. Kubernetes API Rate Limiting** | **Partially Implemented** | Fast check timeout is set to 2.0s; polling interval is 10s. No client-side rate-limiting or backoff retry queue (`client-go` token bucket). |
| **11. Prometheus Availability & Query Perf** | **Implemented, Not Verified** | Employs 1.5s query timeouts and `requests.Session` pooling. Gracefully handles Prometheus connection drops by converting to HOLD. |
| **12. Large Numbers of Policies** | **Partially Implemented** | $O(N)$ rule iteration is lightweight for $<50$ policies. Lacks indexing by metric name or namespace. |
| **13. Multiple Users & Permissions** | **Not Implemented** | Dashboard has zero authentication, session management, or RBAC. Any user with network access can execute manual scaling or mutate policies. |
| **14. Configuration Management** | **Partially Implemented** | Supports environment variables and YAML files. Lacks live config reloading via Kubernetes ConfigMap file watcher. |
| **15. Deployment & Upgrades** | **Partially Implemented** | Basic manifests and Dockerfile provided. No Helm chart, Kustomize overlay, or zero-downtime rolling update configuration. |
| **16. Monitoring & Alerting (Self)** | **Partially Implemented** | Exposes `/healthz` and `/readyz` probes on dashboard and sample app. Lacks Prometheus `/metrics` instrumentation on the controller itself. |
| **17. Security & Secrets Management** | **Partially Implemented** | Avoids hardcoded secrets; binds to ServiceAccount. Lacks TLS encryption for dashboard (plain HTTP) and network security policies. |
| **18. Failure Recovery** | **Partially Implemented** | Recovers automatically from transient Prometheus or Kubernetes outages by holding state. No dead-letter recovery for failed scale calls. |
| **19. Resource Consumption of KubePilot** | **Implemented, Not Verified** | Highly efficient Python footprint (requests CPU limit 200m, RAM limit 128Mi in manifests). |
| **20. Operational Maintainability** | **Implemented, Not Verified** | Code is cleanly formatted with clear docstrings, standardized dataclasses, and descriptive logging. |

---

## 11. Security and Reliability Assessment

### 11.1 Security Findings

1. **Unauthenticated Dashboard & API:** The Flask web application does not implement any authentication (OAuth2, OIDC, HTTP Basic, or JWT). Anyone who can reach port 5055/5000 can scale deployments, toggle live execution, or modify scaling policies.
2. **Kubernetes RBAC Scope:** The ServiceAccount `autoscaling-controller-sa` is appropriately bound to a namespace-scoped `Role` rather than a `ClusterRole`. Verbs are properly restricted to `deployments`, `deployments/scale`, `pods`, and `horizontalpodautoscalers`.
3. **No Secret Leakage:** The policy engine, logger, and telemetry provider sanitize inputs and do not log credentials or sensitive environment variables.
4. **Missing TLS:** Both the dashboard and the sample application run on unencrypted plain HTTP.
5. **CORS & CSRF:** The Flask application does not implement CSRF protection (e.g. Flask-WTF) on state-mutating POST/PUT endpoints.

### 11.2 Reliability & Fault-Tolerance Findings

1. **Safe Fallback on Metric Loss:** If Prometheus goes down, the controller reliably halts all scaling operations and converts decisions to `HOLD`, preventing erratic scaling under blackout conditions.
2. **Thread Safety:** The controller uses `threading.Lock()` (`_cycle_lock` in `AutoscalingController`, `_lock` in `DecisionLogger`, `_run_lock` in `ExperimentManager`) to prevent race conditions during concurrent REST requests.
3. **Verification Gap:** As identified, `KubernetesExecutor.execute_scaling` verifies scaling by polling `spec.replicas` rather than pod readiness. If new pods fail due to image pull errors, missing secrets, or resource exhaustion, KubePilot incorrectly reports success.

---

## 12. Remaining Work – Complete Product Roadmap

This roadmap organizes all outstanding work into practical, sequential phases.

### Phase 1 – Core Functionality Fixes (Mandatory for Academic & Baseline Integrity)
*Goal: Fix broken execution paths, resolve unit test failures, and eliminate container mount incompatibilities.*

| Task ID | Task Description | Current Status | Exact Work Required | Priority | Dependencies | Acceptance Criteria |
|---|---|---|---|---|---|---|
| **T-1.1** | Fix `_core_v1_api` attribute defect | BROKEN | Add `self._core_v1_api: Optional[Any] = None` to `KubernetesExecutor.__init__` in `controller/kubernetes_executor.py:82`. | P0 | None | All 102 pytest tests pass without attribute errors even when kubeconfig contexts are empty. |
| **T-1.2** | Correct `docker-compose.yaml` Prometheus mount | BROKEN | Change volume mount from `./monitoring/prometheus-config.yaml` to `./monitoring/prometheus.yml` at line 10. | P1 | None | `docker compose up prometheus` boots cleanly without YAML parsing errors. |
| **T-1.3** | Fix Pod Readiness Verification in Executor | PARTIAL | Update `KubernetesExecutor.execute_scaling` verification loop (lines 345-356) to poll `ready_replicas == target_replicas` or check rollout status. | P1 | T-1.1 | Live scaling is only reported as VERIFIED when all desired pods reach `Ready=True`. |

### Phase 2 – Architecture & Reliability (Necessary for Functional Product)
*Goal: Resolve the split-brain issue between Dashboard and Controller, and enable state persistence.*

| Task ID | Task Description | Current Status | Exact Work Required | Priority | Dependencies | Acceptance Criteria |
|---|---|---|---|---|---|---|
| **T-2.1** | Unify Controller-Dashboard Architecture | BROKEN ARCHITECTURE | Option A: Embed background `start_loop()` thread directly inside `dashboard/app.py` when running single-pod. Option B: Refactor `controller/main.py` as a standalone daemon exposing a lightweight control socket/API that `dashboard/app.py` calls. | P0 | T-1.1 | Toggling live execution or editing a policy in UI instantly affects the running controller loop without container split-brain. |
| **T-2.2** | Fix Policy Persistence in Kubernetes Manifests | BROKEN IN K8S | Replace read-only ConfigMap mount at `/app/policies` in `k8s/dashboard-deployment.yaml` with a PersistentVolumeClaim, or store policies in a Kubernetes CRD / database. | P1 | T-2.1 | `POST /api/policies` persists without `[Errno 30] Read-only file system` errors when running in a Kubernetes pod. |
| **T-2.3** | Persist Controller Cooldown & Hysteresis State | PARTIAL | Save `last_action_timestamp`, `last_action_direction`, and active timers into a persistent state file or volume upon every scaling event. | P2 | T-2.1 | Cooldown and anti-flapping timers survive controller pod restarts. |

### Phase 3 – Capacity Validation & Guardrail Completion (Necessary for Cloud Reliability)
*Goal: Implement genuine node capacity validation before authorizing scale-out operations.*

| Task ID | Task Description | Current Status | Exact Work Required | Priority | Dependencies | Acceptance Criteria |
|---|---|---|---|---|---|---|
| **T-3.1** | Implement Node Allocatable Capacity Inspector | NOT IMPLEMENTED | Create `controller/capacity_validator.py`. Query `CoreV1Api.list_node()` and calculate total allocatable CPU/RAM minus current pod resource requests. | P1 | T-1.1 | Guardrail blocks scale-out if the cluster lacks unreserved allocatable resources for the additional pod requests. |
| **T-3.2** | Grant Node Read Permissions in RBAC | INCOMPLETE | Add `nodes` resource with `get`, `list` verbs to `k8s/controller-rbac.yaml`. | P1 | T-3.1 | ServiceAccount can read node allocatable metrics in-cluster without RBAC authorization denial. |

### Phase 4 – Empirical Benchmark Experiments (Mandatory for Academic Validation)
*Goal: Demonstrate genuine auto-scaling under real, reproducible load.*

| Task ID | Task Description | Current Status | Exact Work Required | Priority | Dependencies | Acceptance Criteria |
|---|---|---|---|---|---|---|
| **T-4.1** | Tune Synthetic Load Generator | PARTIAL | Update `WorkloadGenerator.run_spike_traffic` in `controller/experiment_runner.py` to route to reachable NodePort / Ingress, and increase concurrency so pod CPU actually exceeds 75%. | P0 | T-1.1 | CPU metric exceeds 80% on Prometheus during traffic spike. |
| **T-4.2** | Execute and Record Real Experiments | PARTIAL | Run both Stable Workload and Traffic Spike benchmarks against Minikube. Record actual scaling events (replicas 2 -> 4 -> 2) and latency improvements. | P0 | T-4.1 | JSON/CSV artifacts record non-null `scale_latency_improvement_seconds` and verified replica transitions. |
| **T-4.3** | Restore UI for Benchmark Experiments | UI MISSING | Create `dashboard/templates/experiments.html` and link it to `/api/experiments` endpoints so users can launch and inspect benchmarks from the UI. | P2 | T-4.2 | Operators can trigger experiments and view side-by-side HPA comparison tables directly in the dashboard. |

### Phase 5 – Product Readiness & Security (Production Deployment Scope)
*Goal: Enterprise hardening, multi-workload support, and observability.*

| Task ID | Task Description | Current Status | Exact Work Required | Priority | Dependencies | Acceptance Criteria |
|---|---|---|---|---|---|---|
| **T-5.1** | Multi-Workload Scaling Engine | NOT IMPLEMENTED | Refactor `ControllerConfig` and `PolicyEngine` to support a list of workload specifications across multiple namespaces. | P3 | Phase 2 | Framework independently monitors and scales multiple deployments. |
| **T-5.2** | Dashboard Authentication & RBAC | NOT IMPLEMENTED | Implement OIDC / basic auth session middleware on Flask endpoints. | P3 | Phase 2 | Unauthenticated requests to dashboard endpoints are rejected with HTTP 401. |
| **T-5.3** | Controller Self-Instrumentation | NOT IMPLEMENTED | Add Prometheus `/metrics` endpoint to the controller exposing evaluation duration, scaling action counts, and error rates. | P3 | Phase 2 | Controller health and evaluation latency are monitored by Prometheus. |

---

## 13. Quantitative Completion Assessment

### 13.1 Dimension-by-Dimension Completion Scores

| Dimension | Completion % | What Is Complete | What Is Incomplete | Supporting Evidence |
|---|---:|---|---|---|
| **Architecture Implementation** | **70%** | Clear module separation, dataclass contracts, clean config loader, PRAH pipeline. | Split-brain execution in k8s deployment; no IPC between dashboard and controller pods. | `controller/main.py:281`, `k8s/controller-deployment.yaml`, `k8s/dashboard-deployment.yaml` |
| **Monitoring and Telemetry** | **65%** | PromQL query generator, `requests.Session` querying, instant vector parser, offline simulation provider. | Live cluster Prometheus is offline; local Windows config has hardcoded pod label; no p95 latency or 5xx queries. | `controller/telemetry.py:440-465`, `monitoring/prometheus.yml:20` |
| **Policy Engine** | **85%** | Declarative YAML parser, mathematical condition evaluator, boundary validation, atomic YAML writes. | Breach duration persistence is in-memory only; loses state on process restart. | `controller/policy_engine.py:145-265`, `dashboard/app.py:72-89` |
| **PRAH Controller** | **85%** | Priority ranking, scale-out win tie-breaking, direction-flip hysteresis delay, telemetry fallback to HOLD. | Cooldown and hysteresis state are kept in-memory; lost upon pod restart. | `controller/decision_controller.py:102-318` |
| **Scaling Execution** | **60%** | Scale subresource patch generator, dry-run preview mode, rollback handling. | Verification polls `spec.replicas` instead of pod readiness; missing `_core_v1_api` attribute defect breaks execution. | `controller/kubernetes_executor.py:79-84, 345-356` |
| **Guardrails & Capacity Validation** | **45%** | Min/max bounds enforcement, step clamping, duplicate action suppression. | Capacity validation is **0% implemented** (no node allocatable CPU/RAM checks). | `controller/guardrails.py:80-216` |
| **Kubernetes Integration** | **50%** | RBAC manifests, Deployment/Service manifests, AppsV1 scale subresource client. | Live cluster offline; missing context in kubeconfig; RBAC lacks Node read permissions. | `k8s/controller-rbac.yaml`, `minikube status`, `kubectl cluster-info` |
| **Dashboard Functionality** | **75%** | Responsive web interface, clean JSON error handling, status badges, policy editing modals. | No background loop in dashboard process; `/experiments` HTML page missing; read-only ConfigMap in k8s. | `dashboard/app.py:804-823`, `dashboard/templates/` |
| **Persistence** | **60%** | Structured JSON Lines audit logging, atomic YAML policy file updates. | Log files are ephemeral in Kubernetes containers; no database or PVC integration. | `controller/decision_logger.py:31-43`, `k8s/dashboard-deployment.yaml` |
| **Testing and Verification** | **70%** | 102 collected tests across 9 test files; 99 tests pass; comprehensive mock coverage. | 2 tests fail due to `_core_v1_api` attribute defect; live cluster mutation test is skipped. | Pytest run output (99 passed, 2 failed, 1 skipped) |
| **Experiments & Benchmarks** | **40%** | Benchmark runner code, workload generator, JSON/CSV export routines. | Traffic spike experiment failed to generate load (CPU stayed at 0.44%); zero scaling events recorded; metrics null. | `experiments/results/exp-traffic_spike-20261024-074350.json` |
| **Security and Reliability** | **50%** | Safe fallback on telemetry outage, thread locks, no credential leaks, restricted RBAC. | Zero dashboard authentication, no TLS, no CSRF protection, ConfigMap write collision. | `dashboard/app.py`, `k8s/controller-rbac.yaml` |
| **Product Scalability** | **30%** | Low memory footprint, fast query timeouts. | Single workload only, single namespace only, no leader election, no multi-cluster support. | `controller/config.py:24-25` |

---

### 13.2 Overall Readiness Metrics

- **Overall Academic Project Completion Estimate:** **72%**  
  *(The algorithmic core, policy engine, mathematical arbitration, mock tests, and dashboard UI are largely complete. However, real benchmark scaling evidence and the bug fix in the executor are required to fulfill the academic claim).*
- **Overall Functional Product Completion Estimate:** **48%**  
  *(Requires fixing the controller-dashboard split-brain, implementing node capacity validation, ensuring persistent storage in Kubernetes, and verifying pod readiness).*
- **Production Readiness Assessment:** **NOT PRODUCTION READY (Prototype / Academic Prototype Stage)**  
  *(Lacks authentication, high-availability leader election, multi-workload support, and TLS encryption).*

### 13.3 Module Status Summary Counts

- **Number of Verified Working Modules (Unit / Local):** 3 (Policy Engine, Guardrails Engine, PRAH Decision Controller)
- **Number of Partially Implemented Modules:** 6 (Dashboard, Telemetry Provider, Audit Logger, Strategy Coordinator, Experiments Suite, Cluster Manifests)
- **Number of Unverified Modules (due to offline cluster):** 2 (Live Kubernetes Deployment Mutation, Live Prometheus Scrape Vector)
- **Number of Broken Modules:** 1 (`KubernetesExecutor` attribute initialization error)
- **Number of Completely Missing Modules:** 1 (Capacity Validation Engine)

---

## 14. Top 10 Immediate Priorities

1. **Fix `KubernetesExecutor` Attribute Bug:** Add `self._core_v1_api = None` to `KubernetesExecutor.__init__` in `controller/kubernetes_executor.py` so unit tests pass and offline cluster detection does not crash.
2. **Correct `docker-compose.yaml`:** Point Prometheus volume mount to `./monitoring/prometheus.yml` instead of the Kubernetes ConfigMap file.
3. **Resolve Dashboard / Controller Split-Brain:** Enable `dashboard/app.py` to run the background evaluation loop directly or communicate with `controller/main.py` through a shared mechanism.
4. **Boot Minikube & Deploy Workload:** Start Docker Desktop, execute `minikube start`, and deploy `sample-web-app` and Prometheus to establish a real Kubernetes environment.
5. **Re-run Live Regression Tests:** Run `pytest tests/test_fixes_regression.py -k test_case_5` against the running Minikube cluster to verify live deployment mutation.
6. **Re-run Benchmark Experiments with Real Load:** Calibrate the workload generator in `controller/experiment_runner.py` so pod CPU utilization breaches 75%, generating verifiable scaling events (2 -> 4 pods) and populating non-null latency improvement metrics.
7. **Fix Verification in Executor:** Update `KubernetesExecutor.execute_scaling` to verify that `ready_replicas == target_replicas` rather than only checking `spec.replicas`.
8. **Fix Kubernetes Manifest Volumes:** Replace read-only ConfigMap mount in `k8s/dashboard-deployment.yaml` with persistent volume storage for dynamic policy editing.
9. **Build Capacity Validation Module:** Create `controller/capacity_validator.py` to inspect node allocatable CPU/RAM and reject scale-out when the cluster is saturated.
10. **Restore `/experiments` Dashboard Page:** Create `dashboard/templates/experiments.html` and connect it to `/api/experiments` so operators can run and review benchmarks from the UI.

---

## 15. Final Technical Verdict

KubePilot possesses an **exceptionally solid theoretical and algorithmic foundation**. The PRAH decision logic, guardrail constraints, explicit comparison rules, and fallback mechanisms are cleanly designed and demonstrate sound systems thinking.

However, the repository currently reflects a **disconnect between documented claims and actual runtime execution**. The benchmark data saved in `experiments/results/` reveals that no scaling occurred during the spike test; the Kubernetes executor contains a latent attribute defect that breaks test execution when context is missing; capacity validation was never written; and deploying the framework as separate pods in Kubernetes produces a split-brain state.

By executing the prioritized Phase 1 and Phase 2 corrections outlined in this audit—specifically fixing the executor bug, unifying the controller process, tuning the load generator, and verifying real pod readiness against a live Minikube cluster—KubePilot can rapidly transition from an unverified prototype into an exemplary, fully functional auto-scaling platform.
