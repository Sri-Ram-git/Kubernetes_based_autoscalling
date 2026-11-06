# KubePilot: Implementation Audit & Architecture Verification

**Project:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications  
**Project ID:** 357 | Alliance University, Bengaluru  
**Evaluation Standard:** IEEE Conference Experimental Research Standard (Empirical Evidence)  
**Author / Auditor:** Senior Kubernetes Architect, Software Testing Engineer, and Systems Researcher  
**Date of Audit:** November 5, 2026  
**Cluster Environment:** Minikube v1.38.1 (Kubernetes v1.35.1), Docker Desktop 29.2.1, Prometheus v2.54.0, Debian 12 (WSL2 Kernel 6.6.87)

---

## 1. Executive Summary

This implementation audit provides an exhaustive, evidence-based assessment of the **KubePilot** auto-scaling framework compared to native Kubernetes Horizontal Pod Autoscaler (HPA v2). Every finding, defect, correction, and verification recorded in this report is derived from direct inspection of the codebase, live cluster API responses, genuine Prometheus queries, and reproducible test executions.

### Key Audit Findings
1. **Core Algorithmic Viability:** The Priority-based Rule Arbitration with Hysteresis (PRAH) engine (`controller/decision_controller.py`), operational guardrails (`controller/guardrails.py`), and atomic policy loader (`controller/policy_engine.py`) are deterministically implemented without artificial heuristics or machine learning.
2. **Defect Rectification (Issue A Confirmed):** Pre-scaling capacity validation in `controller/strategy_coordinator.py` was completely unreachable due to an enum mismatch (`guardrail_result.action == "SCALE_OUT"` while `GuardrailEngine` returns `action="EXECUTE"`). This defect was forensically analyzed, corrected, and verified with dedicated regression tests.
3. **Measurement Inconsistency Root Causes Identified (Issues B, C, D):** Previous experimental runs suffered from lack of pod termination delays, residual telemetry bleed across sequential runs, and flawed time-to-first-scale calculations that captured post-cycle state at $t=0$, falsely reporting $0.0\text{ s}$ latency. These were resolved by implementing independent trials with alternating execution order, strict Kubernetes and Prometheus reset protocols, and precise 5-point event timestamp tracking.

---

## 2. Module-by-Module Implementation Status

| Module | Source File | Implemented Capabilities | Verified Deficiencies & Status |
|---|---|---|---|
| **Telemetry Ingestion** | `controller/telemetry.py` | Query instant against Prometheus HTTP API; PromQL generators for container CPU, memory, and HTTP RPS; strict rejection of `NaN`/`Inf`; explicit statuses (`VALID`, `MISSING`, `STALE`, `ERROR`, `UNAVAILABLE`). | **VERIFIED.** Strict requirement met: never silently replaces missing metrics with 0. Stale metrics (>60s) trigger fail-safe `HOLD`. |
| **Policy Engine** | `controller/policy_engine.py` | YAML schema validation; rule duration tracking; explicit operators (`>`, `<`, `>=`, `<=`); atomic file write operations. | **VERIFIED.** Parses 6 active policies cleanly; deterministic evaluation outputs. |
| **PRAH Decision Engine** | `controller/decision_controller.py` | Priority ranking ($0 \le P \le 100$); deterministic tie-breaking favoring scale-out (`SCALE_OUT_WINS`); 5% anti-flapping hysteresis band; configurable cooldown timers. | **VERIFIED.** Priority arbitration selects higher-priority rule deterministically. Fallback to `HOLD` on telemetry degradation confirmed. |
| **Operational Guardrails** | `controller/guardrails.py` | Hard boundary clamping $[min\_replicas, max\_replicas]$; step-rate bounding ($max\_scale\_step\_up=+2, max\_scale\_step\_down=-1$); redundant action filtering; dry-run vs live mutation governance. | **VERIFIED.** Clamping and rejection verified under both boundary and step limit stress tests. |
| **Capacity Validator** | `controller/capacity_validator.py` | Node allocatable CPU/RAM checks; sum of active committed pod requests; pod template requirement extraction; cordon and taint/toleration verification; greedy bin-packing simulation. | **VERIFIED (After Coordinator Fix).** Returns 5 authoritative outcomes: `CAPACITY_SUFFICIENT`, `INSUFFICIENT_CPU`, `INSUFFICIENT_MEMORY`, `NO_ELIGIBLE_NODE`, `CAPACITY_UNKNOWN`. |
| **Strategy Coordinator** | `controller/strategy_coordinator.py` | Conflict detection with native HPA (`check_competing_hpa`); guardrail validation delegation; pre-scaling capacity evaluation; execution routing. | **FIXED & VERIFIED.** Issue A resolved: unreachable capacity validation branch corrected. Confirmed blocking on insufficient CPU/RAM. |
| **Kubernetes Executor** | `controller/kubernetes_executor.py` | Deployment read and scale subresource patching; in-cluster and kubeconfig auth; live pod readiness polling (`ready_replicas == target_replicas`); failure diagnosis. | **VERIFIED.** Synchronously confirms pod rollout before reporting execution success. Attribute initialization bug resolved. |
| **Decision Logger** | `controller/decision_logger.py` | Structured audit logging to JSONL (`logs/decisions.jsonl`); in-memory circular history buffer; consecutive nominal `HOLD` deduplication. | **VERIFIED.** Audit records contain complete telemetry snapshots, guardrail decisions, and cluster execution confirmations. |
| **Dashboard UI & API** | `dashboard/app.py` | Flask REST API (`/api/status`, `/api/workloads`, `/api/metrics`, `/api/policies`, `/api/capacity`, `/api/history`); live operational toggles; responsive Bootstrap/Tailwind web UI. | **VERIFIED.** Real-time endpoints query Kubernetes API and Prometheus directly. Test suite passes 100%. |
| **Experiment Runner** | `controller/experiment_runner.py` | Automated synthetic workload generation; concurrency control; comparative time-series logging; baseline HPA lifecycle management. | **UPGRADED.** Refactored into independent trial framework with alternating execution order, strict resets, and 5-point event timestamping. |

---

## 3. Forensic Investigation of Critical Issues

### Issue A: Capacity Validation Unreachable Branch
* **Investigation:** Inspection of `controller/strategy_coordinator.py` line 140 revealed the condition:
  ```python
  if (guardrail_result.action == "SCALE_OUT" and self.capacity_validator and self.executor._connected and not guardrail_result.is_dry_run):
  ```
  However, `controller/guardrails.py` defines `GuardrailResult.action` as `"EXECUTE"`, `"HOLD"`, or `"REJECTED"`. When a scale-out is authorized, `guardrail_result.action` is `"EXECUTE"`, and `guardrail_result.replica_delta > 0`.
* **Impact:** The capacity validation branch was **100% unreachable**. The controller never called `validate_scale_out()`. Even if the cluster had zero available CPU or RAM, scale-out was never blocked by capacity guardrails.
* **Correction Applied:** Updated `strategy_coordinator.py` to check:
  ```python
  is_scale_out = (proposed_action == "SCALE_OUT" or guardrail_result.replica_delta > 0)
  if is_scale_out and guardrail_result.approved and self.capacity_validator and self.executor._connected:
      cap_res = self.capacity_validator.validate_scale_out(delta=guardrail_result.replica_delta)
      if not cap_res.is_sufficient and cap_res.outcome in (CapacityOutcome.INSUFFICIENT_CPU, CapacityOutcome.INSUFFICIENT_MEMORY, CapacityOutcome.NO_ELIGIBLE_NODE):
          # Block scale-out, return REJECTED
  ```
* **Verification:** Added regression tests in `tests/test_capacity_validator.py` (`test_strategy_coordinator_blocks_when_capacity_insufficient`, `test_strategy_coordinator_allows_when_capacity_sufficient`, `test_strategy_coordinator_bypasses_capacity_on_scale_in`). All 12 unit tests and FT-13 passed against the live cluster.

### Issue B: Benchmark Execution Order & Trial Independence
* **Investigation:** In historical runs, native HPA ran as Phase 1, followed immediately by KubePilot as Phase 2, with only a 3.0s sleep in between.
* **Impact:** A 3-second sleep is grossly inadequate: pods take 10–25s to terminate, and Prometheus cAdvisor queries average over a 1m window. Residual load and high metrics from HPA directly bled into KubePilot's initial seconds. HPA was always tested on cold pods, while KubePilot was tested on hot pods.
* **Correction Applied:** Implemented a new benchmark suite (`scripts/run_benchmarks.py`) enforcing:
  1. Alternating execution order across trials:
     - Trial 1: HPA $\to$ KubePilot
     - Trial 2: KubePilot $\to$ HPA
     - Trial 3: HPA $\to$ KubePilot
     - Trial 4: KubePilot $\to$ HPA
     - Trial 5: HPA $\to$ KubePilot
  2. Mandatory reset protocol before every run:
     - Draining all workload threads.
     - Scaling deployment to 2 replicas.
     - Polling Kubernetes until all terminating pods are gone and exactly 2 `Ready` pods exist.
     - Polling Prometheus until CPU drops below 20%.
     - Resetting KubePilot cooldown and breach timers.

### Issue C: Inconsistent Initial Replica Count (4 vs 2)
* **Investigation:** Historical file `exp-traffic_spike-20261105-010910.json` recorded `initial_replicas = 2` in the summary, but sample $t=0.0\text{ s}$ showed `desired=4, current=4, ready=4`. Forensic audit of `_run_system_test()` revealed:
  1. `initial_replicas = 2` was hardcoded before the sampling loop.
  2. At $t=0.0\text{ s}$, `run_single_cycle()` was called **before** querying the workload state.
  3. Because Prometheus still retained high CPU metrics from the preceding HPA run, `run_single_cycle()` immediately fired a `SCALE_OUT` to 4 replicas.
  4. The subsequent state query recorded `desired=4`, but the summary retained the hardcoded `2`.
* **Correction Applied:** In `scripts/run_benchmarks.py`, the initial workload state is queried directly from Kubernetes **before** initiating traffic or the control loop, ensuring initial replicas truthfully reflect cluster reality at $t=0.0\text{ s}$.

### Issue D: Scaling Response Time Artifact (Reported 0.0s)
* **Investigation:** In `exp-traffic_spike-20261105-010910.json`, KubePilot reported `time_to_first_scale_seconds = 0.0`.
* **Root Cause:**
  1. `loop_start = time.time()` was recorded at $t=0$.
  2. `run_single_cycle()` executed synchronously, taking several seconds to patch Kubernetes and await pod readiness.
  3. Upon returning, `elapsed = loop_start - start_time = 0.0`. Because `desired` (4) differed from `last_replicas` (2), `time_to_first_scale` was assigned `elapsed = 0.0`.
  4. Furthermore, the traffic spike did not even begin until $t=5.0\text{ s}$! Measuring latency from test initialization rather than trigger onset produced invalid physical numbers.
* **Correction Applied:**
  1. Defined scaling response time strictly as:
     $$\text{Scaling Response Time} = t_{\text{desired\_observed}} - t_{\text{trigger\_start}}$$
  2. Defined pod readiness time as:
     $$\text{Pod Readiness Time} = t_{\text{ready\_observed}} - t_{\text{trigger\_start}}$$
  3. Tracked distinct timestamps for:
     - $t_{\text{trigger\_start}}$: when workload surge begins
     - $t_{\text{policy\_detected}}$: when controller detects threshold breach
     - $t_{\text{scale\_request}}$: when `patch_namespaced_deployment_scale` is sent
     - $t_{\text{desired\_observed}}$: when Kubernetes reports desired replica count updated
     - $t_{\text{ready\_observed}}$: when all target pods report `Ready=True`

---

## 4. Known Limitations & Architecture Boundaries

1. **External Out-of-Cluster Controller:** KubePilot operates as an external controller client communicating over the Kubernetes API, rather than an in-tree admission webhook or custom scheduler.
2. **Heuristic Scheduling Check:** The Capacity Validator evaluates node allocatable CPU/RAM requests against existing pod requests via greedy bin-packing. It is a pre-execution safety guardrail; the native `kube-scheduler` remains authoritative for placement.
3. **Single-Node Minikube Topology:** All tests were conducted on a single Minikube control-plane node (12 vCPUs, 7.62 GiB allocatable RAM). Multi-node zone affinity and topology spread constraints are not evaluated.
4. **Reactive Telemetry Boundary:** In compliance with the prompt's strict constraints, KubePilot contains zero machine learning, zero predictive forecasting, and zero statistical models. All scaling actions are strictly reactive to observed telemetry.

---

## 5. Proposed vs. Implemented Functionality Matrix

| Proposed Framework Feature | Implementation Status | Evidence / Verification Location |
|---|:---:|---|
| Deterministic Multi-Rule Policy Engine | **100% IMPLEMENTED** | `controller/policy_engine.py`, `tests/test_policy_engine.py` |
| Priority-Based Rule Arbitration (PRAH) | **100% IMPLEMENTED** | `controller/decision_controller.py`, `tests/test_decision_controller.py` |
| Hysteresis Anti-Flapping Band (5%) | **100% IMPLEMENTED** | `controller/decision_controller.py`, `tests/test_hysteresis.py` |
| Configurable Cooldown Timers | **100% IMPLEMENTED** | `controller/decision_controller.py`, `tests/test_hysteresis.py` |
| Hard Replica Boundaries & Step Clamping | **100% IMPLEMENTED** | `controller/guardrails.py`, `tests/test_guardrails.py` |
| Pre-Scaling Node Capacity Validation | **100% IMPLEMENTED & FIXED** | `controller/capacity_validator.py`, `controller/strategy_coordinator.py` |
| Kubernetes API Readiness Verification | **100% IMPLEMENTED** | `controller/kubernetes_executor.py`, `tests/test_kubernetes_executor.py` |
| Native HPA Collision Detection | **100% IMPLEMENTED** | `controller/strategy_coordinator.py:check_competing_hpa()` |
| Structured JSONL Audit Logging | **100% IMPLEMENTED** | `controller/decision_logger.py`, `logs/decisions.jsonl` |
| Live Web Dashboard & REST API | **100% IMPLEMENTED** | `dashboard/app.py`, `tests/test_dashboard_api.py` |
| Predictive / Machine Learning Scaling | **EXCLUDED (By Constraint)** | Strict zero-ML rule observed. |
| Automated Cluster Node Provisioning | **EXCLUDED (By Scope)** | Cluster Autoscaler out of project scope. |
