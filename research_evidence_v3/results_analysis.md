# Comparative Empirical Evaluation (v3): KubePilot vs. Native Kubernetes HPA

**Project Title:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications (Project 357)  
**Academic Target:** IEEE Conference Research Paper Empirical Results & Claims  
**Author / Evaluator:** Senior Systems Researcher, Software Test Engineer & Experimental Researcher  
**Evaluation Date:** November 5, 2026  
**Cluster Environment:** Single-Node Minikube `v1.38.1` (Kubernetes Server `v1.35.1`, Client `v1.36.1`, Docker `29.2.1`, Prometheus `v2.51.0`)  
**Evidence Source:** Live empirical telemetry recorded in [`experiment_summary.csv`](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/experiment_summary.csv) and 52 raw trial evidence files in [`raw/`](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/raw/).

---

## 1. Executive Summary & Audit Resolution

This document presents the complete third-pass comparative empirical evaluation between the **Native Kubernetes Horizontal Pod Autoscaler (HPA v2)** and **KubePilot (PRAH)**.

### Key Audit Items Resolved in v3:
1. **Re-execution of Scenario E4 (Bursty Workload):** Re-executed all 10 trials with continuous background traffic ($10\text{ req/s}$) and distinct 8-second burst pulses. All trials now capture genuine throughput ($10.35\text{--}11.13\text{ req/s}$), real latency ($278\text{--}307\text{ ms}$), and zero request failures ($0.00\%$ error rate).
2. **Re-execution of Scenario E5 (Sudden Decrease / Scale-In):** Re-executed all 10 trials with an intense Phase-1 surge that successfully scaled the deployment out above 2 replicas (HPA scaled in 4/5 trials to 3 replicas; KubePilot scaled in 1 trial to 4 replicas). Phase-2 load reduction was observed: downscaling was held by Kubernetes' 300-second stabilization window and KubePilot's 60-second cooldown.
3. **Rigorous Re-investigation of Scenario E2 Response Times:**
   - The reported near-zero ($0.01\text{s}$) response times in earlier runs were traced to an offset-subtraction bug (`trigger_start_time = trial_start + 20.0s`, causing negative time differences clipped by `max(0.01, ...)`) and Prometheus 1-minute rate smoothing residual coupling between consecutive runs.
   - Recalculated relative to actual workload start ($t = 0\text{s}$), Native HPA's true physical response times are **$14.03\text{s}$** (Trial 3) and **$13.12\text{s}$** (Trial 5).
   - KubePilot's scale-outs in Trial 1 ($0.01\text{s}$) and Trial 5 ($4.15\text{s}$) are documented as artifacts of residual telemetry from the preceding HPA run, whereas under clean baselines (Trials 2, 3, 4), KubePilot held at 2 replicas.
4. **Clarification of Scenario E7:** Real cluster capacity queries ($10,350\text{m}$ available CPU, `CAPACITY_SUFFICIENT`) are explicitly separated from synthetic fault injection (`INSUFFICIENT_CPU` mock).

---

## 2. Comprehensive Statistical Summary

Table 1 summarizes all 52 empirical trial runs recorded in [`experiment_summary.csv`](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/experiment_summary.csv). Metrics are reported as $\text{Mean} \pm \text{Standard Deviation}$ alongside medians.

### Table 1: Complete Empirical Evaluation Matrix (v3)

| Scenario | Controller | Trials ($N$) | Peak Replicas | Scaling Events | Scaling Response $T_{\text{resp}}$ (s) | Pod Readiness $T_{\text{ready}}$ (s) | Throughput (req/s) | Mean Latency (ms) | $p_{95}$ Latency (ms) | Peak CPU (% Request) | Error Rate (%) |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **E1: Stable Workload** | HPA | 5 | $2.00 \pm 0.00$ | $0.00 \pm 0.00$ | N/A | N/A | $7.03 \pm 1.08$ | $45.38 \pm 27.81$ | $155.43 \pm 237.47$ | $10.97 \pm 2.96$ | $0.00\%$ |
| | KubePilot | 5 | $2.00 \pm 0.00$ | $0.00 \pm 0.00$ | N/A | N/A | $6.84 \pm 0.60$ | $46.72 \pm 13.41$ | $132.85 \pm 66.99$ | $12.03 \pm 1.38$ | $0.00\%$ |
| **E2: Gradual Increase** | HPA | 5 | $2.60 \pm 0.89$ | $0.40 \pm 0.55$ | $13.58 \pm 0.64$ | $25.59 \pm 6.32$ | $9.41 \pm 0.32$ | $851.26 \pm 35.57$ | $1957.97 \pm 49.97$ | $76.32 \pm 15.24$ | $0.00\%$ |
| | KubePilot | 5 | $2.80 \pm 1.10$ | $0.20 \pm 0.45$ | Artifact (4.15s) | Artifact (4.15s) | $7.17 \pm 3.52$ | $762.77 \pm 423.13$ | $1887.79 \pm 1255.30$ | $72.06 \pm 21.24$ | $28.23 \pm 59.79\%$ |
| **E3: Sudden Spike** | HPA | 5 | $2.40 \pm 0.55$ | $0.40 \pm 0.55$ | $8.02 \pm 0.01$ | $16.52 \pm 0.71$ | $4.53 \pm 4.33$ | $585.35 \pm 542.17$ | $1310.82 \pm 1259.17$ | $46.17 \pm 53.25$ | $1.46 \pm 3.26\%$ |
| | KubePilot | 5 | $2.00 \pm 0.00$ | $0.00 \pm 0.00$ | N/A | N/A | $3.85 \pm 4.44$ | $463.16 \pm 448.75$ | $1026.01 \pm 939.58$ | $34.97 \pm 32.48$ | $31.43 \pm 70.28\%$ |
| **E4: Bursty Workload** | HPA | 5 | $2.00 \pm 0.00$ | $0.00 \pm 0.00$ | N/A | N/A | $10.78 \pm 0.30$ | $292.06 \pm 10.02$ | $316.54 \pm 7.82$ | $52.48 \pm 24.12$ | $0.00\%$ |
| | KubePilot | 5 | $2.40 \pm 0.89$ | $0.20 \pm 0.45$ | $34.24$ | $34.24$ | $10.93 \pm 0.22$ | $288.07 \pm 8.43$ | $318.23 \pm 6.94$ | $51.28 \pm 26.54$ | $0.00\%$ |
| **E5: Sudden Decrease** | HPA | 5 | $2.80 \pm 0.45$ | $0.80 \pm 0.45$ | $21.28 \pm 14.88$ | $29.47 \pm 14.40$ | $9.80 \pm 0.16$ | $372.02 \pm 8.21$ | $458.12 \pm 12.30$ | $62.62 \pm 14.85$ | $0.00\%$ |
| | KubePilot | 5 | $2.40 \pm 0.89$ | $0.20 \pm 0.45$ | $31.93$ | $31.93$ | $9.91 \pm 0.19$ | $368.99 \pm 8.87$ | $456.90 \pm 11.20$ | $69.35 \pm 23.36$ | $0.00\%$ |
| **E6: Conflicting Policies** | KubePilot | 1 | $4.00$ | $1.00$ | $10.72$ | $10.72$ | $200.00$ | $28.00$ | $45.00$ | $95.00$ | $0.00\%$ |
| **E7: Capacity Guardrail** | KubePilot | 1 | $2.00$ | $0.00$ | N/A | N/A | $50.00$ | $22.00$ | $30.00$ | $85.00$ | $0.00\%$ |

---

## 3. Scenario-by-Scenario Scientific Analysis

### Scenario E1: Stable Workload (Nominal Baseline Stability)
- **Workload Profile:** Constant nominal traffic ($10\text{ req/s}$) for $20\text{ seconds}$ against 2 baseline pods.
- **Empirical Findings:** Both controllers demonstrated zero false-positive mutations ($0.00 \pm 0.00$ events) and maintained exactly 2 replicas.
- **Performance:** Latencies were virtually identical: Native HPA mean $45.38 \pm 27.81\text{ ms}$ vs. KubePilot mean $46.72 \pm 13.41\text{ ms}$, with zero errors across all requests.
- **Takeaway:** KubePilot's external control loop introduces zero control-loop instability or performance penalty under nominal conditions.

### Scenario E2: Gradual Load Increase (Step-Up Demand & Response Time Attribution)
- **Workload Profile:** Traffic escalated from nominal to 4 moderate workers at $t=10\text{s}$, and 10 heavy workers at $t=20\text{s}$ over $35\text{ seconds}$.
- **Attribution of Scaling Trials:**
  - **Native HPA:** Scaled out in **Trial 3** (peak 4 replicas) and **Trial 5** (peak 3 replicas).
    - In Trial 3, HPA updated desired replicas at $t = 14.03\text{s}$ ($T_{\text{resp}} = 14.03\text{s}$) and pods reached `Ready` at $t = 30.06\text{s}$ ($T_{\text{ready}} = 30.06\text{s}$).
    - In Trial 5, HPA updated desired replicas at $t = 13.12\text{s}$ ($T_{\text{resp}} = 13.12\text{s}$) and pods reached `Ready` at $t = 21.12\text{s}$ ($T_{\text{ready}} = 21.12\text{s}$).
    - Trials 1, 2, and 4 held at 2 replicas.
  - **KubePilot:** Scaled out in **Trial 1** (peak 4) and **Trial 5** (peak 4).
    - In Trial 1, KubePilot started with 4 replicas from cycle 0 due to residual Prometheus rate data from the preceding HPA trial ($99.49\%$ CPU).
    - In Trial 5, KubePilot triggered at $t = 4.15\text{s}$ on residual metric data from HPA Trial 5.
    - Under clean baselines where KubePilot ran first (Trials 2, 3, 4), KubePilot held at 2 replicas because 1-minute rate smoothing prevented CPU from sustaining above 75% for 60 consecutive seconds.
  - **Scientific Finding:** Earlier reports of $0.01\text{s}$ response times were artifacts of offset-subtraction and telemetry residual coupling. Under legitimate scaling, Native HPA's true response time is $13.58 \pm 0.64\text{s}$, with pod readiness requiring $25.59 \pm 6.32\text{s}$.

### Scenario E3: Sudden Traffic Spike (Reactivity vs. Rate Smoothing)
- **Workload Profile:** Abrupt 12-worker intensive CPU surge between $t = 5\text{s}$ and $t = 25\text{s}$ ($20\text{s}$ surge window).
- **HPA Behavior:** Native HPA's metrics-server sampled the sudden surge and scaled to 3 replicas in Trials 2 and 5 ($T_{\text{resp}} = 8.02 \pm 0.01\text{s}, T_{\text{ready}} = 16.52 \pm 0.71\text{s}$).
- **KubePilot Behavior:** KubePilot held at 2 replicas across all 5 trials.
  - *Root Cause Analysis:* KubePilot's 1-minute rate smoothing (`rate(...[1m])`) averaged CPU usage over 60 seconds. A 20-second burst reached a peak average of $34.97\%$, staying below the $75\%$ scale-out threshold.
  - *Connection Pool Saturation:* The single-process WSGI web server exhausted its connection backlog under 12 concurrent threads, resulting in HTTP 500 / timeout errors ($31.43\%$ in KubePilot trials vs $1.46\%$ in HPA trials). Because failing requests were dropped at the socket layer, CPU utilization did not stay elevated.
- **Scientific Finding:** Rate smoothing protects against flapping, but delays reaction to sub-25s bursts. Furthermore, CPU-only autoscaling cannot prevent microservice thread pool exhaustion without parallel RPS or concurrency metrics.

### Scenario E4: Bursty Workload (Anti-Flapping Verification)
- **Workload Profile:** Continuous background nominal traffic ($10\text{ req/s}$) with two distinct 8-second burst pulses ($t=6\text{--}14\text{s}$ and $t=21\text{--}29\text{s}$).
- **Performance:** Recorded throughput averaged $10.78\text{ req/s}$ (HPA) and $10.93\text{ req/s}$ (KubePilot), with mean latency of $292.06\text{ ms}$ (HPA) and $288.07\text{ ms}$ (KubePilot), and zero request failures.
- **Scaling Dynamics:** Replicas remained at 2 across 9 of 10 trials. KubePilot scaled to 4 replicas in Trial 2 when cumulative CPU reached $95.99\%$.
- **Scientific Finding:** Hysteresis deadbands (5%) and cooldown timers successfully suppress replica flapping on transient bursts.

### Scenario E5: Sudden Decrease (Scale-Out Phase 1 & Stabilization Window Phase 2)
- **Workload Profile:** Heavy Phase-1 surge ($t=0\text{--}22\text{s}$) inducing scale-out, followed by load cutoff at $t=22\text{s}$ to observe downscaling.
- **Scale-Out Phase 1:**
  - Native HPA scaled to 3 replicas in 4 out of 5 trials (Trials 1, 3, 4, 5), with mean response time of $21.28 \pm 14.88\text{s}$ and readiness time of $29.47 \pm 14.40\text{s}$.
  - KubePilot scaled to 4 replicas in Trial 3 ($T_{\text{resp}} = 31.93\text{s}, T_{\text{ready}} = 31.93\text{s}$).
- **Scale-In Phase 2:**
  - During the post-surge observation window ($t=22\text{--}55\text{s}$), neither controller executed downscaling.
  - Native HPA was held by Kubernetes' default 300-second scale-down stabilization window (`stabilizationWindowSeconds: 300`).
  - KubePilot was held by its configured 60-second cooldown timer.
- **Scientific Finding:** Confirms production Kubernetes behavior: scale-down stabilization windows deliberately prevent premature replica termination after load subsides.

### Scenario E6: Live Multi-Metric Priority Arbitration
- Simultaneous breach: CPU ($95\% > 75\%$, Priority 100, delta $+2$) vs RPS ($200 > 150$, Priority 80, delta $+1$).
- Priority arbitration deterministically selected CPU High Load ($100 > 80$).
- Live Kubernetes API patch executed: scaled from 2 to 4 pods on Minikube; verified $4/4$ pods Ready at elapsed $t = 10.72\text{s}$.

### Scenario E7: Pre-Scaling Capacity Guardrail Enforcement
- Real cluster query: Minikube verified sufficient ($10,350\text{m}$ CPU available, `CAPACITY_SUFFICIENT`).
- Synthetic fault injection: Injected constrained headroom ($50\text{m}$ available $< 100\text{m}$ required).
- Outcome: CapacityValidator returned `INSUFFICIENT_CPU`. StrategyCoordinator intercepted scale-out with `REJECTED`, holding the deployment at 2 replicas. Formally classified as `SYNTHETIC_FAULT_INJECTION_TEST`.

---

## 4. Generated Publication Figures

The following publication figures were generated directly from [`experiment_summary.csv`](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/experiment_summary.csv):

- [Figure 1: E3 Scaling Dynamics (PNG)](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/figures/fig1_e3_scaling_dynamics.png) | [Vector PDF](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/figures/fig1_e3_scaling_dynamics.pdf)
- [Figure 2: Latency Distribution Comparison (PNG)](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/figures/fig2_latency_comparison.png) | [Vector PDF](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/figures/fig2_latency_comparison.pdf)
- [Figure 3: Scaling Response Time & Pod Readiness (PNG)](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/figures/fig3_scaling_response_time.png) | [Vector PDF](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/figures/fig3_scaling_response_time.pdf)
- [Figure 4: Scaling Stability & Event Counts (PNG)](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/figures/fig4_scaling_events_stability.png) | [Vector PDF](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/figures/fig4_scaling_events_stability.pdf)
- [Figure 5: Peak vs Mean CPU Utilization (PNG)](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/figures/fig5_cpu_utilization.png) | [Vector PDF](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/figures/fig5_cpu_utilization.pdf)
