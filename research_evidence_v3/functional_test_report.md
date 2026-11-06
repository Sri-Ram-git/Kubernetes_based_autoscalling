# Comprehensive Functional Test Report (v3)

**Project Title:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications (Project 357)  
**Target:** IEEE Conference Research Paper Functional Validation  
**Author / Evaluator:** Senior Systems Researcher & Software Test Engineer  
**Evaluation Date:** November 5, 2026  
**Cluster Environment:** Single-Node Minikube `v1.38.1` (Kubernetes Server `v1.35.1`, Client `v1.36.1`, Docker `29.2.1`, Prometheus `v2.51.0`)  
**Primary Execution Evidence:**
- Raw pytest Terminal Output: [`logs/pytest_terminal_output.txt`](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/logs/pytest_terminal_output.txt) (115/115 passed)
- Raw Functional Test Runner Output: [`logs/functional_test_terminal_output.txt`](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/logs/functional_test_terminal_output.txt) (18/18 passed)
- Raw Machine-Readable Evidence: [`raw/functional_tests.json`](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/raw/functional_tests.json)

---

## 1. Executive Summary & Verification Outcomes

All 18 required functional tests (FT-01 through FT-18) were executed on the live Minikube cluster and passed at **100% (18/18)**. In addition, the complete unit and integration test suite (`pytest`) passed at **100% (115/115)** in 11.52 seconds.

### Table 1: Complete Functional Test Matrix (FT-01 to FT-18)

| Test ID | Test Name | Target Mechanism | Command / API Invoked | Status | Evidence Reference |
|---|---|---|---|:---:|---|
| **FT-01** | Application Startup | Controller, dashboard, and Kubernetes connection | `AutoscalingController()`, `KubernetesExecutor._connect()` | **PASSED** | Core components initialized, kubeconfig verified. |
| **FT-02** | Telemetry Collection | Prometheus ingestion of CPU and memory metrics | `PrometheusTelemetryProvider.query_instant(...)` | **PASSED** | Live container CPU (10.97%) and RAM (15.07%) ingested. |
| **FT-03** | Telemetry Freshness | Detection of stale Prometheus samples | Simulated stale metric timestamp ($t_{\text{now}} - 65\text{s}$) | **PASSED** | Correctly marked as `MetricStatus.STALE`. |
| **FT-04** | Policy Loading | YAML policy parsing and schema validation | `PolicyEngine(config.policies_path)` | **PASSED** | 6 active policies parsed from `scaling-policies.yaml`. |
| **FT-05** | Policy Matching | Activation of scaling rules on threshold breach | `PolicyEngine.evaluate_policies(metrics)` | **PASSED** | `CPU_HIGH_LOAD` activated on CPU = 85.0% > 75.0%. |
| **FT-06** | Priority Arbitration | Higher-priority policy wins over lower-priority | Simultaneous CPU 90% (P100) vs RPS 120 (P80) | **PASSED** | `CPU_CRITICAL_SPIKE` (Priority 100) selected. |
| **FT-07** | Tie-Breaking | Conflict resolution on equal priority | Simultaneous equal-priority scale-out policies | **PASSED** | Deterministic arbitration (`SCALE_OUT_WINS`). |
| **FT-08** | Hysteresis | Suppression of marginal boundary flapping | 5% hysteresis band on threshold boundaries | **PASSED** | Direction reversal suppressed within deadband. |
| **FT-09** | Live Scale-Out | Live Kubernetes API patch and readiness check | `KubernetesExecutor.execute_scaling("SCALE_OUT", 3)` | **PASSED** | Scaled 2 $\rightarrow$ 3 pods on Minikube; verified 3/3 Ready. |
| **FT-10** | Live Scale-In | Live Kubernetes API scale-in down to baseline | `KubernetesExecutor.execute_scaling("SCALE_IN", 2)` | **PASSED** | Scaled 3 $\rightarrow$ 2 pods on Minikube; verified 2/2 Ready. |
| **FT-11** | Cooldown Enforcement | Blocking rapid repeated mutations | `DecisionController.record_action_executed(...)` | **PASSED** | 60s cooldown timer enforced; immediate scaling blocked. |
| **FT-12** | Boundary Limits | Clamping to minReplicas (2) and maxReplicas (10) | Guardrail clamp on out-of-bounds proposals | **PASSED** | Clamped -5 to min (2) and +15 to max (10). |
| **FT-13** | Capacity Validation | Pre-scaling check of node allocatable headroom | `CapacityValidator.validate_scale_out(delta=2)` | **PASSED** | Real cluster verified sufficient ($10,350\text{m}$); simulated exhaustion blocked with `INSUFFICIENT_CPU`. |
| **FT-14** | Error Handling | Graceful handling of Kubernetes API failures | Targeting nonexistent namespace `nonexistent-namespace-357` | **PASSED** | Captured HTTP 404 error without controller crash. |
| **FT-15** | Pod Listing Filter | Elimination of terminating pods from active list | `KubernetesExecutor.get_workload_state()` | **PASSED** | Terminating pods (`deletion_timestamp is not None`) filtered; verified exactly 2 ready pods. |
| **FT-16** | Audit Logging | JSON Lines structured audit trail | `DecisionLogger.log_cycle(...)` | **PASSED** | Valid JSONL cycle appended to `logs/decisions.jsonl`. |
| **FT-17** | Dashboard API | Flask dashboard HTTP API endpoints | Test client GET on `/api/status`, `/api/workloads`, etc. | **PASSED** | All 5 endpoints returned HTTP 200 with valid JSON. |
| **FT-18** | Fail-Safe Operation | Fallback to `HOLD` on telemetry outage | Simulated Prometheus connection timeout (0.2s) | **PASSED** | Cycle completed with `HOLD` without modifying replicas. |

---

## 2. In-Depth Verification of Critical Functional Behaviors

### FT-15: Pod Count Correction & Terminating Pod Exclusion
- **Defect Investigated:** In the initial testing phase, `get_workload_state()` listed 3 pods while reporting 2 ready replicas.
- **Root Cause:** When scaling down from 3 to 2 pods (FT-10), the terminated pod entered a 30-second graceful termination period. The un-filtered Kubernetes pod listing query (`list_namespaced_pod`) included the terminating pod because it still existed in the namespace.
- **Code Fix:** Added filter in [`controller/kubernetes_executor.py:221`](file:///c:/Users/SRIRAM/design_project/controller/kubernetes_executor.py#L221):
  ```python
  if pod.metadata.deletion_timestamp is not None:
      continue  # Exclude terminating pods from active workload state
  ```
- **Empirical Verification:** During FT-15 execution:
  - `ws_current.desired_replicas`: 2
  - `ws_current.ready_replicas`: 2
  - `len(ws_current.pods)`: 2
  - Active Pod Names: `sample-web-app-59c6d8b9b8-tphhg`, `sample-web-app-59c6d8b9b8-zghmp`
  - Terminating pods excluded: 100% verified.

### FT-13: Pre-Scaling Capacity Guardrail Enforcement
- **Defect Investigated (Issue A):** The coordinator previously checked for `proposed_action == "SCALE_OUT"`, but the guardrails returned `action = "EXECUTE"`, rendering the capacity check unreachable.
- **Code Fix:** Updated [`controller/strategy_coordinator.py:138`](file:///c:/Users/SRIRAM/design_project/controller/strategy_coordinator.py#L138):
  ```python
  is_scale_out = (proposed_action == "SCALE_OUT" or guardrail_result.replica_delta > 0)
  if is_scale_out and guardrail_result.approved and self.capacity_validator:
      cap_res = self.capacity_validator.validate_scale_out(delta=guardrail_result.replica_delta)
      if not cap_res.is_sufficient:
          # Block execution with REJECTED and HOLD
  ```
- **Live Verification:**
  1. *Real Cluster Check:* Queried Minikube node allocatable capacity for $+2$ pods. Returned `CAPACITY_SUFFICIENT` ($10,350\text{m}$ CPU available, $6,409.2\text{ MiB}$ RAM available).
  2. *Simulated Insufficient Capacity Check:* Injected mock validator returning `INSUFFICIENT_CPU` ($50\text{m}$ available $< 100\text{m}$ requested).
  3. *Result:* `guardrail_result.action = "REJECTED"`, `execution_result.action_type = "HOLD"`, `error = "INSUFFICIENT_CPU"`. The scaling mutation was completely intercepted and blocked before touching the Kubernetes API.

### FT-18: Fail-Safe Operation During Telemetry Outages
- **Procedure:** Configured a mock Prometheus provider targeting an unreachable port (`http://localhost:19099`) with a 0.2-second timeout.
- **Execution Log Output:**
  `[ERROR] [autoscaler.telemetry] Timeout querying Prometheus for cpu_utilization_percent (threshold: 0.2s)`
- **Controller Decision:** Returned `action = "HOLD"`, `selected_policy_id = None`, `proposed_replica_delta = 0`.
- **Finding:** Under telemetry failure, the controller enters a fail-safe hold state. No uncommanded scale-out or scale-in occurs, preventing catastrophic cluster instability during monitoring outages.

---

## 3. Real Execution Logs

The complete terminal output capturing all 18 functional tests is preserved in [`logs/functional_test_terminal_output.txt`](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/logs/functional_test_terminal_output.txt).  
The complete pytest terminal output capturing all 115 tests is preserved in [`logs/pytest_terminal_output.txt`](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/logs/pytest_terminal_output.txt).
