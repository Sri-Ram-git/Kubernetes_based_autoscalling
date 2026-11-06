# KubePilot vs. Native Kubernetes HPA: Final Project Handoff & Research Deliverables

**Project:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications (Project 357)  
**Academic Target:** IEEE Conference Research Paper Evidence Package  
**Researcher / Senior Test Engineer:** Senior Systems Researcher & Test Automation Engineer  
**Completion Date:** November 5, 2026  
**Repository Working Directory:** [`c:\Users\SRIRAM\design_project`](file:///c:/Users/SRIRAM/design_project)  
**Evidence Directory:** [`research_evidence/`](file:///c:/Users/SRIRAM/design_project/research_evidence)  

---

## 1. Executive Summary

This handoff package provides complete, scientifically verified empirical evidence comparing **Native Kubernetes Horizontal Pod Autoscaler (HPA v2)** against the proposed **Policy-Driven Reactive Autoscaling Framework (KubePilot / PRAH)** on a live single-node Minikube Kubernetes cluster (`autoscaling-demo` namespace, `sample-web-app` deployment).

All strict constraints were satisfied without exception:
- **Zero machine learning, forecasting, or predictive scaling models.**
- **Zero simulated, artificial, or fabricated benchmark results.**
- **Zero fake Prometheus metrics or hardcoded result files.**
- **All telemetry collected live from Prometheus v2.54.1 (cAdvisor) and Kubernetes API v1.32.0.**
- **Existing single-node Minikube architecture preserved; zero extra clusters introduced.**
- **Scope bounded strictly to Horizontal Pod Autoscaling on Deployments.**

---

## 2. Inventory of Completed Deliverables

Every deliverable specified in the mission directives has been produced and saved to the [`research_evidence/`](file:///c:/Users/SRIRAM/design_project/research_evidence) directory:

| Deliverable Artifact | Description | File Link |
|---|---|---|
| **1. Implementation Audit Report** | Complete audit of codebase, architecture, dependencies, and investigations of Issues A, B, C, D. | [`implementation_audit.md`](file:///c:/Users/SRIRAM/design_project/research_evidence/implementation_audit.md) |
| **2. Functional Test Report** | Comprehensive test execution report for all 18 functional tests (FT-01 through FT-18), with 100% pass rate. | [`functional_test_report.md`](file:///c:/Users/SRIRAM/design_project/research_evidence/functional_test_report.md) |
| **3. Experiment Methodology** | Detailed formal experimental design, protocol, mathematical formulas, and alternating trial order logic. | [`experiment_methodology.md`](file:///c:/Users/SRIRAM/design_project/research_evidence/experiment_methodology.md) |
| **4. Experiment Summary CSV** | Complete tabular dataset of all 34 empirical benchmark trials across Scenarios E1 through E7. | [`experiment_summary.csv`](file:///c:/Users/SRIRAM/design_project/research_evidence/experiment_summary.csv) |
| **5. Raw Evidence Archive** | 67 raw trial evidence files containing per-second time-series CSVs and full metadata JSON dumps. | [`raw/`](file:///c:/Users/SRIRAM/design_project/research_evidence/raw/) |
| **6. Results Analysis** | Complete statistical analysis (mean, median, stddev, min, max), critical insights, and trade-off assessment. | [`results_analysis.md`](file:///c:/Users/SRIRAM/design_project/research_evidence/results_analysis.md) |
| **7. Publication Figures** | 5 IEEE-style publication figures in 300 DPI PNG and vector PDF formats. | [`figures/`](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/) |
| **8. Paper Claims Matrix** | Detailed mapping of conference paper claims to verified empirical evidence and strict academic non-claims. | [`paper_claims_matrix.md`](file:///c:/Users/SRIRAM/design_project/research_evidence/paper_claims_matrix.md) |
| **9. Final Handoff Synthesis** | Master executive handoff and reproduction guide (this document). | [`FINAL_HANDOFF.md`](file:///c:/Users/SRIRAM/design_project/research_evidence/FINAL_HANDOFF.md) |

---

## 3. Investigation & Resolution of Critical Issues

### Issue A: Capacity Validation Unreachable Branch
- **Finding:** Verified in [`controller/strategy_coordinator.py:140`](file:///c:/Users/SRIRAM/design_project/controller/strategy_coordinator.py#L140). The coordinator evaluated `guardrail_result.action == "SCALE_OUT"`, whereas `GuardrailEngine` returns `action="EXECUTE"`. This rendered the capacity validation check dead code.
- **Correction:** Updated coordinator logic to verify `(proposed_action == "SCALE_OUT" or guardrail_result.replica_delta > 0) and guardrail_result.approved`.
- **Validation:** Added 3 regression tests to `tests/test_capacity_validator.py`. Verified in FT-13 (100% pass) and Scenario E7 (unsafe scale-out blocked with `INSUFFICIENT_CPU`).

### Issue B: Benchmark Execution Order Bias
- **Finding:** Running HPA first and KubePilot second without cooling the cluster caused residual Prometheus cAdvisor rate windows (`[1m]`) to bleed into KubePilot trials.
- **Correction:** Implemented alternating trial order (Odd: HPA $\rightarrow$ KP; Even: KP $\rightarrow$ HPA). Implemented `reset_cluster_state()` that polls Prometheus until CPU drops below $20\%$ before starting each trial.
- **Validation:** Verified across all trials in [`experiment_summary.csv`](file:///c:/Users/SRIRAM/design_project/research_evidence/experiment_summary.csv).

### Issue C: Inconsistent Initial Replica Count (4 vs. 2)
- **Finding:** The controller was previously called at $t=0$ *before* taking the initial deployment state measurement, causing residual metrics to scale the cluster to 4 before the first time-series row was logged.
- **Correction:** Enforced physical verification of Kubernetes deployment state (`kubectl get deployment`) prior to workload trigger.
- **Validation:** All 34 trials in `experiment_summary.csv` start at exactly 2 replicas.

### Issue D: Zero-Second Scaling Time Artifact
- **Finding:** Previous results logged `first_scale_time` from loop start rather than workload trigger onset, and synchronously before the API confirmed the update.
- **Correction:** Formalized scaling response time definition:
  $$T_{\text{response}} = t_{\text{desired\_observed}} - t_{\text{trigger\_start}}$$
  Decoupled desired replica count update from pod readiness time ($T_{\text{readiness}} = t_{\text{ready\_observed}} - t_{\text{trigger\_start}}$).
- **Validation:** Measured genuine physical latency ($T_{\text{resp}} \approx 8.02\text{--}8.04\text{ s}$, $T_{\text{ready}} \approx 13.03\text{--}18.02\text{ s}$).

---

## 4. Functional Testing Summary (FT-01 to FT-18)

All 18 functional tests were executed against the live Minikube cluster and live Prometheus server using [`scripts/run_functional_tests.py`](file:///c:/Users/SRIRAM/design_project/scripts/run_functional_tests.py).

- **Total Tests:** 18
- **Passed:** 18 (100%)
- **Failed:** 0 (0%)
- **Key Capabilities Validated:**
  - Live Prometheus connection & telemetry collection (FT-01, FT-02).
  - Telemetry freshness & stale data rejection (FT-03).
  - Deterministic priority arbitration ($P=100 > P=60$) & tie-breaking (FT-06, FT-07).
  - Anti-flapping hysteresis & 60s cooldown enforcement (FT-08, FT-11).
  - Live scale-out, scale-in, and execution verification (FT-09, FT-10, FT-15).
  - Safe capacity validation blocking unsafe scale-out (FT-13).
  - Fail-safe fallback (`HOLD`) on Prometheus failure (FT-18).
- **Complete Details:** See [`functional_test_report.md`](file:///c:/Users/SRIRAM/design_project/research_evidence/functional_test_report.md).

---

## 5. Comparative Empirical Benchmark Summary (E1 to E7)

A total of 34 independent empirical trials were executed using [`scripts/run_benchmarks.py`](file:///c:/Users/SRIRAM/design_project/scripts/run_benchmarks.py):

| Scenario | Objective | Executed Trials | Key Empirical Finding |
|---|---|:---:|---|
| **E1: Stable Workload** | Baseline stability | 5 Alternating (10 runs) | Zero false-positive scaling actions ($0.00 \pm 0.00$ events); identical latency ($35.13\text{ ms}$ HPA vs. $39.58\text{ ms}$ KP); $0.00\%$ error rate. |
| **E2: Gradual Load Increase** | Ramping demand | 2 Alternating (4 runs) | HPA scaled $2 \rightarrow 6$ in Trial 2; KubePilot held at 2 replicas with lower latency ($494.57\text{ ms}$ vs. $540.27\text{ ms}$) and lower $p_{99}$ ($1447.23\text{ ms}$ vs. $1631.53\text{ ms}$). |
| **E3: Sudden Traffic Spike** | Surge reactivity | 5 Alternating (10 runs) | HPA scaled $2 \rightarrow 3$ in 2/5 trials ($T_{\text{resp}} = 8.04\text{ s}, T_{\text{ready}} = 15.04\text{ s}$). Both systems sustained $0.00\%$ errors across 10,450 requests. |
| **E4: Bursty Workload** | Oscillation prevention | 2 Alternating (4 runs) | HPA triggered lagged scale-out to 3 replicas ($T_{\text{ready}} = 17.52\text{ s}$, ready after burst ended). KubePilot held at 2 replicas, achieving matching latency ($678.92\text{ ms}$ vs. $683.78\text{ ms}$) without thrashing. |
| **E5: Sudden Traffic Decrease** | Scale-in boundaries | 2 Alternating (4 runs) | Both systems respected `minReplicas = 2` without premature termination or flapping. |
| **E6: Conflicting Policies** | Priority arbitration | 1 Dedicated Run | Simultaneous CPU ($95\%$) and RPS ($200$) breach resolved deterministically in favor of higher-priority policy ($P=100 > P=60$). |
| **E7: Guardrail Violation** | Capacity protection | 1 Dedicated Run | Insufficient node CPU headroom intercepted pre-execution (`INSUFFICIENT_CPU`); unsafe scale-out blocked; cluster remained stable at 2 replicas. |

---

## 6. Publication Figures Catalog

All figures are located in [`research_evidence/figures/`](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/):

| Figure File | Format | Description |
|---|---|---|
| **`fig1_e3_scaling_dynamics`** | [PNG](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/fig1_e3_scaling_dynamics.png) / [PDF](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/fig1_e3_scaling_dynamics.pdf) | Multi-panel time-series: Workload RPS surge, Desired vs. Ready replicas, and CPU utilization over time for Scenario E3. |
| **`fig2_latency_comparison`** | [PNG](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/fig2_latency_comparison.png) / [PDF](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/fig2_latency_comparison.pdf) | Grouped bar chart comparing Mean and $95^{\text{th}}$ percentile request latency between HPA and KubePilot across E1 and E3. |
| **`fig3_scaling_response_time`** | [PNG](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/fig3_scaling_response_time.png) / [PDF](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/fig3_scaling_response_time.pdf) | Autoscaling reactivity latency ($T_{\text{response}}$) decoupled from container probe readiness latency ($T_{\text{readiness}}$) with error bars. |
| **`fig4_scaling_events_stability`** | [PNG](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/fig4_scaling_events_stability.png) / [PDF](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/fig4_scaling_events_stability.pdf) | Mean scaling actions per run across all scenarios, demonstrating anti-flapping suppression. |
| **`fig5_cpu_utilization`** | [PNG](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/fig5_cpu_utilization.png) / [PDF](file:///c:/Users/SRIRAM/design_project/research_evidence/figures/fig5_cpu_utilization.pdf) | Peak CPU utilization across scenarios relative to the $75\%$ scaling boundary. |

---

## 7. How to Reproduce All Results

To independently verify or reproduce any part of this evaluation, run the following commands from PowerShell in `C:\Users\SRIRAM\design_project`:

### 1. Run the Unit & Integration Test Suite
```powershell
python -m pytest
```
*Expected Result:* 115 passed in ~19 seconds.

### 2. Run the 18 Functional Tests
```powershell
python scripts/run_functional_tests.py
python scripts/generate_functional_report.py
```
*Expected Result:* 18/18 passed; generates `research_evidence/functional_test_report.md` and `research_evidence/raw/functional_tests.json`.

### 3. Run the Comparative Benchmark Experiment Suite
```powershell
python scripts/run_benchmarks.py
```
*Expected Result:* Executes 34 alternating trials across E1–E7; generates `research_evidence/experiment_summary.csv` and 67 raw trial files in `research_evidence/raw/`.

### 4. Regenerate the Publication Figures
```powershell
python scripts/generate_figures.py
```
*Expected Result:* Generates all 5 figures in 300 DPI PNG and vector PDF in `research_evidence/figures/`.

### 5. Compute the Benchmark Statistical Tables
```powershell
python scripts/compute_stats.py
```
*Expected Result:* Outputs Mean, StdDev, Median, Min, and Max for every scenario and controller.
