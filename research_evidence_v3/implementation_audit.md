# Technical Implementation & Architecture Audit (v3)

**Project Title:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications (Project 357)  
**Standard:** IEEE Conference Research Paper System Verification  
**Evaluator:** Senior Kubernetes Systems Engineer & Software Test Engineer  
**Evaluation Date:** November 5, 2026  

---

## 1. Verified Architectural Components

The KubePilot framework was audited against the repository source code and live cluster deployment:

```
[Prometheus Telemetry Provider] 
       │ (1m rate PromQL)
       ▼
[PRAH Decision Controller] ◄── [Policy Engine (YAML rules)]
       │ (Action: SCALE_OUT / SCALE_IN / HOLD)
       ▼
[Guardrail Safety Engine] (Clamp to [2, 10], Cooldown 60s, Hysteresis 5%)
       │ (Approved Action: EXECUTE / REJECTED)
       ▼
[Strategy Coordinator] ◄── [Capacity Validator (Node allocatable check)]
       │ (Authorized Scale-Out Check)
       ▼
[Kubernetes API Executor] (Terminating pod filter, Ready probe poll)
       │ (HTTP PATCH Deployment.spec.replicas)
       ▼
[Kubernetes Deployment: sample-web-app] (autoscaling-demo)
```

---

## 2. Source Code Audits & Defect Corrections

### Audit 1: Pre-Scaling Capacity Guardrail (Issue A)
- **Component:** [`controller/strategy_coordinator.py`](file:///c:/Users/SRIRAM/design_project/controller/strategy_coordinator.py) and [`controller/capacity_validator.py`](file:///c:/Users/SRIRAM/design_project/controller/capacity_validator.py).
- **Audit Findings:** Previously, `StrategyCoordinator.coordinate_and_execute()` checked for `proposed_action == "SCALE_OUT"`, but the guardrail engine returned `action = "EXECUTE"` for approved scaling actions, making the capacity check unreachable.
- **Correction Verified:** Lines 138-153 now evaluate `is_scale_out = (proposed_action == "SCALE_OUT" or guardrail_result.replica_delta > 0)`. When capacity is insufficient, the coordinator intercepts execution, returning `guardrail_res.action = "REJECTED"` and `exec_res.action_type = "HOLD"`, with error code `INSUFFICIENT_CPU`.

### Audit 2: CPU Metric Equivalence (Priority 1)
- **Component:** [`controller/telemetry.py`](file:///c:/Users/SRIRAM/design_project/controller/telemetry.py).
- **Audit Findings:** PromQL query previously calculated CPU relative to limits (500m) or quota, yielding an effective threshold of 375m/pod. Native HPA evaluated 75% of request quota (100m -> 75m/pod).
- **Correction Verified:** PromQL query updated to divide by `count(pods) * 0.1` (pod requests). Both systems evaluate against the identical physical threshold: **$75\text{m}$ CPU per pod** ($0.150\text{ cores}$ for 2 pods).

### Audit 3: Terminating Pod Exclusion Filter (Priority 4 / FT-15)
- **Component:** [`controller/kubernetes_executor.py`](file:///c:/Users/SRIRAM/design_project/controller/kubernetes_executor.py).
- **Audit Findings:** `get_workload_state()` listed all pods returned by `list_namespaced_pod`, including pods undergoing termination with `deletionTimestamp` set.
- **Correction Verified:** Line 221 filters out pods where `pod.metadata.deletion_timestamp is not None`. Rerun verified in FT-15: exactly 2 desired, 2 ready, and 2 active pods reported.

---

## 3. Five-Level Scientific Maturity Classification

To ensure complete transparency for IEEE peer review, all system capabilities are classified into five distinct maturity levels:

| Capability / Mechanism | Maturity Level | Evidence Basis |
|---|:---:|---|
| **Deterministic Priority Arbitration (PRAH)** | **Statistically Supported** | FT-06, FT-07, Scenario E6. Competing rules resolved deterministically; 4/4 pods scaled on Kubernetes API. |
| **Anti-Flapping & Hysteresis Band (5%)** | **Statistically Supported** | FT-08, Scenarios E1, E4, E5. Zero flapping across all nominal and bursty runs. |
| **Pre-Scaling Capacity Guardrails** | **Functionally Verified** | FT-13, Scenario E7. Real cluster capacity queried ($10,350\text{m}$ available); simulated exhaustion blocked with `INSUFFICIENT_CPU`. |
| **Pod Readiness Verification Loop** | **Experimentally Observed** | FT-09, FT-10, FT-15, Scenarios E2, E3, E5, E6. CoreV1 API polling confirms readiness before unlocking. |
| **Fail-Safe Operation on Outages** | **Functionally Verified** | FT-14 (API 404), FT-18 (Prometheus timeout). Holds last confirmed replica count without mutation. |
| **Step-Up Demand Scaling Under Metric Equivalence** | **Experimentally Observed** | Scenario E2. Both HPA (Trials 3 & 5) and KubePilot (Trial 1 & 5) scaled out when CPU crossed 75m/pod. |
| **Reactivity Advantage on Short Spikes (<25s)** | **Not Demonstrated / Unsupported** | Scenario E3. Native HPA reacted in $8.02\text{s}$; KubePilot did not scale due to 1-minute rate smoothing. |
| **Automatic Concurrency Latency Protection** | **Partially Supported / Conditional** | Scenario E3. Connection pool saturation occurred under single-metric CPU; requires concurrent RPS policies. |
| **Machine Learning / Predictive Scaling** | **Not Implemented (Explicit Non-Claim)** | No predictive models exist in the codebase. All logic is rule-based and deterministic. |
| **Vertical Pod Autoscaling (VPA) / KEDA** | **Not Implemented (Explicit Non-Claim)** | Framework operates exclusively as a Horizontal Pod Autoscaler for Deployments. |
