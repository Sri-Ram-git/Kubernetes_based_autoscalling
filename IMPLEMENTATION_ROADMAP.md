# PROJECT 357 — Implementation & Verification Roadmap

**Project Title:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications  
**Roadmap Version:** 1.0  
**Project ID:** 357 | Alliance University, Bengaluru  

---

## 1. Module Status Matrix

The following table summarizes the verified status of the framework's components based on code audit and test execution:

| Module | Real File Path | Current Status | Coverage | Tests Passing |
| :--- | :--- | :--- | :---: | :---: |
| **Module 1: Telemetry Collector** | [`controller/telemetry.py`](file:///C:/Users/SRIRAM/design_project/controller/telemetry.py) | **Unit tested** (Mocked) | 87% | 6 / 6 |
| **Module 2: Policy Engine** | [`controller/policy_engine.py`](file:///C:/Users/SRIRAM/design_project/controller/policy_engine.py) | **Unit tested** | 88% | 9 / 9 |
| **Module 3: PRAH Decision Controller** | [`controller/decision_controller.py`](file:///C:/Users/SRIRAM/design_project/controller/decision_controller.py) | **Unit tested** | 93% | 8 / 8 |
| **Module 4: Strategy Coordinator** | [`controller/strategy_coordinator.py`](file:///C:/Users/SRIRAM/design_project/controller/strategy_coordinator.py) | **Integration tested** (Mocked) | 59% | 2 / 2 |
| **Module 5: Guardrails** | [`controller/guardrails.py`](file:///C:/Users/SRIRAM/design_project/controller/guardrails.py) | **Unit tested** | 99% | 8 / 8 |
| **Module 6: Kubernetes Executor** | [`controller/kubernetes_executor.py`](file:///C:/Users/SRIRAM/design_project/controller/kubernetes_executor.py) | **Integration tested** (Mocked) | 70% | 4 / 4 |
| **Module 7: Decision Logger** | [`controller/decision_logger.py`](file:///C:/Users/SRIRAM/design_project/controller/decision_logger.py) | **Unit tested** | 83% | 3 / 3 |
| **Web Dashboard & REST APIs** | [`dashboard/app.py`](file:///C:/Users/SRIRAM/design_project/dashboard/app.py) | **Integration tested** | 79% | 13 / 13 |
| **Live Minikube Cluster Integration** | Cluster manifests (`k8s/`) | **Inspected** (Offline) | N/A | 0 (Docker offline) |

*Status definitions: Not inspected $\to$ Inspected $\to$ Implemented $\to$ Unit tested $\to$ Integration tested $\to$ End-to-end verified.*

---

## 2. Module Analysis & Improvement Backlog

### Phase 2.1: Telemetry Collector (Module 1)
* **What Already Works:**
  - Standard PromQL queries targeting deployment CPU, memory, and HTTP RPS.
  - Staleness threshold validation ($>60\text{s}$).
  - Classification into `VALID`, `MISSING`, `STALE`, `ERROR`, `SIMULATED`.
  - Offline simulation provider for demonstration without Prometheus.
* **Defects / Gaps Identified:**
  - Queries assume a single vector result `results[0]`. If multiple pods or containers return series, vector aggregation is required.
  - No retry backoff on transient connection resets.
* **Dependencies:** None.
* **Required Tests:**
  - Test vector response with multiple series items.
  - Test query with NaN or Infinite values.
* **Acceptance Criteria:** Robust against malformed Prometheus responses without unhandled exceptions.

---

### Phase 2.2: Policy Engine (Module 2)
* **What Already Works:**
  - YAML schema parsing and strict semantic validation.
  - Operators: `>`, `>=`, `<`, `<=`, `==`, `!=`.
  - Duration persistence tracking (`duration_seconds`).
  - Action sign validation (positive for scale-out, negative for scale-in, zero for hold).
* **Defects / Gaps Identified:**
  - `_breach_timestamps` is memory-only; process restart clears active breach duration.
  - No compound conditions (e.g. `CPU > 80% AND memory > 70%`).
* **Dependencies:** Module 1.
* **Required Tests:**
  - Test duration timer reset when metric dips below threshold and breaches again.
  - Test policy hot-reloading while evaluation loop is running.
* **Acceptance Criteria:** Deterministic evaluation output for all supported mathematical operators.

---

### Phase 2.3: PRAH Decision Controller (Module 3)
* **What Already Works:**
  - Telemetry degradation safe fallback (forced HOLD at priority 999).
  - Priority sorting and candidate filtering.
  - Conflict resolution tie-breaking: Scale-out wins over scale-in at equal priority.
  - Direction flip suppression (30s window).
  - Cooldown timer enforcement.
* **Defects / Gaps Identified:**
  - Metric deadband hysteresis percentage (`hysteresis_band_percent = 5.0`) is parsed but directional time delay is currently the primary anti-flapping guard.
* **Dependencies:** Module 1, Module 2.
* **Required Tests:**
  - Conflict resolution with 3+ policies at equal priority.
  - Deadband threshold test (verifying metric within $\pm 5\%$ of threshold does not flip).
* **Acceptance Criteria:** Every decision includes a full human-readable explanation and rejected competing candidates.

---

### Phase 2.4: Strategy Coordinator & Guardrails (Modules 4 & 5)
* **What Already Works:**
  - Single-owner enforcement: checks `AutoscalingV2Api` for competing native HPAs.
  - Guardrail replica limits: $[1, 10]$ boundaries.
  - Step size clamping: $+2$ max scale-out, $-1$ max scale-in.
  - Redundant action filtering (no-op when target equals current).
  - Dry-run mode vs live execution gating.
* **Defects / Gaps Identified:**
  - When HPA collision occurs, error message is logged but dashboard does not surface an explicit persistent warning badge.
* **Dependencies:** Module 6.
* **Required Tests:**
  - Dedicated unit test mocking a discovered competing native HPA.
  - Test guardrail behavior when initial replicas are already out of bounds.
* **Acceptance Criteria:** 100% of scaling proposals pass through guardrail clamping before reaching the executor.

---

### Phase 2.5: Kubernetes Executor & Live Cluster (Module 6)
* **What Already Works:**
  - In-cluster and local kubeconfig initialization with short timeouts.
  - Deployment spec and pod readiness parsing.
  - Scale subresource patching via `AppsV1Api.patch_namespaced_deployment_scale`.
  - Post-scaling verification polling loop with timeout.
  - Dry-run preview simulation mode.
* **Defects / Gaps Identified:**
  - Live cluster execution requires Docker Desktop and Minikube to be started.
* **Dependencies:** Kubernetes API (`AppsV1Api`, `CoreV1Api`).
* **Required Tests:**
  - Live execution test against a real Minikube node.
  - Test verification failure when pods get stuck in `Pending` state.
* **Acceptance Criteria:** Verified replica count confirmed via Kubernetes API before reporting success.

---

### Phase 2.6: Decision Logger & History Audit (Module 7)
* **What Already Works:**
  - Atomic JSON Lines append to `logs/decisions.jsonl`.
  - In-memory ring buffer (deque) preloaded on startup.
  - Thread-safe access via mutex.
  - REST endpoints for recent history.
* **Defects / Gaps Identified:**
  - No log file rotation or retention pruning for long-running deployments.
* **Dependencies:** None.
* **Required Tests:**
  - Concurrency test with multiple threads calling `log_cycle`.
* **Acceptance Criteria:** Fast, non-blocking structured audit trail with zero secret exposure.

---

## 3. Recommended Implementation Order

1. **Step 1 (Immediate - Foundational Contracts):**
   - Add multi-series vector handling to [`controller/telemetry.py`](file:///C:/Users/SRIRAM/design_project/controller/telemetry.py).
   - Add competing HPA unit test in `tests/test_strategy_coordinator.py`.
2. **Step 2 (Local Cluster Readiness):**
   - Start Docker Desktop and Minikube (`minikube start --driver=docker`).
   - Deploy sample application and RBAC manifests:
     ```powershell
     kubectl apply -f k8s/namespace.yaml
     kubectl apply -f k8s/controller-rbac.yaml
     kubectl apply -f app/sample-app.yaml
     ```
3. **Step 3 (Live End-to-End Verification):**
   - Trigger a live scaling action via the controller or dashboard.
   - Verify that `sample-web-app` scales from 2 to 3 replicas and pod readiness is confirmed by the Kubernetes API.
