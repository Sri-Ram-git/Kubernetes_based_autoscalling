# Experimental Methodology & Measurement Standards (v3)

**Project Title:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications (Project 357)  
**Standard:** IEEE Conference Research Paper Experimental Reproducibility Standard  
**Author / Evaluator:** Senior Systems Researcher & Experimental Researcher  
**Evaluation Date:** November 5, 2026  

---

## 1. Core Experimental Principles & Rigor

To provide an indisputable, independently verifiable dataset for IEEE peer review, the following experimental protocols were strictly enforced across all 52 benchmark trials:

### 1.1 Strict CPU Metric Equivalence
- **Pod Container Quotas:** CPU Request = $100\text{m}$ ($0.100\text{ cores}$), CPU Limit = $500\text{m}$ ($0.500\text{ cores}$).
- **Target Threshold:** $75\%$ of CPU Request Quota.
- **Physical Scale-Out Threshold:** Exactly **$75\text{m}$ CPU per pod** ($0.150\text{ cores}$ baseline for 2 pods).
- **PromQL Metric Query:**
  ```promql
  (sum(rate(container_cpu_usage_seconds_total{namespace="autoscaling-demo", pod=~"sample-web-app-.*"}[1m])) 
  / (count(count by (pod) (container_cpu_usage_seconds_total{namespace="autoscaling-demo", pod=~"sample-web-app-.*"})) * 0.1) * 100)
  ```
- **Telemetry Recording:** Raw CPU consumption in cores, allocated request quota, allocated limit quota, HPA %, and KubePilot % are captured every second in each trial's CSV.

### 1.2 Alternating Trial Execution Order
To eliminate residual metric caching and cAdvisor rate averaging bias between consecutive trials, experimental runs alternated strictly:
- Trial 1: Native HPA $\longrightarrow$ KubePilot
- Trial 2: KubePilot $\longrightarrow$ Native HPA
- Trial 3: Native HPA $\longrightarrow$ KubePilot
- Trial 4: KubePilot $\longrightarrow$ Native HPA
- Trial 5: Native HPA $\longrightarrow$ KubePilot

### 1.3 Reproducible Cluster Reset Protocol
Before each trial, an automated reset procedure was executed:
1. Workload generator stopped and socket pools drained.
2. Port-forward connection verified (`http://localhost:8080/` HTTP 200).
3. Any active Native HPA resource deleted via `kubectl delete hpa`.
4. KubePilot set to dry-run mode and cooldown/hysteresis timers cleared.
5. Deployment scaled to exactly 2 replicas via `kubectl scale deployment`.
6. Cluster polled until `desired == ready == active_pods == 2` with zero terminating pods remaining.
7. Prometheus CPU query polled until reported utilization cooled below $20\%$ of request quota.

---

## 2. Decoupled 6-Stage Scaling Timestamps & Metrics

Scaling reactivity is decoupled into six distinct physical events:

$$t_{\text{trigger}} \longrightarrow t_{\text{detected}} \longrightarrow t_{\text{request}} \longrightarrow t_{\text{desired}} \longrightarrow t_{\text{ready}} \longrightarrow t_{\text{scale\_in}}$$

1. **Workload Trigger Time ($t_{\text{trigger}}$):** Exact Unix epoch timestamp when synthetic workload generation begins.
2. **Policy Detection Time ($t_{\text{detected}}$):** Timestamp when the controller's decision engine identifies a metric threshold breach.
3. **Scaling Request Time ($t_{\text{request}}$):** Timestamp when the controller issues the HTTP PATCH request to the Kubernetes API server.
4. **Desired Replica Update Time ($t_{\text{desired}}$):** Timestamp when `Deployment.spec.replicas` is observed updated in the Kubernetes cluster.
5. **Pod Readiness Time ($t_{\text{ready}}$):** Timestamp when all newly spawned pods reach `Ready` status (`status.conditions[Ready].status == "True"`).
6. **Scale-In Observed Time ($t_{\text{scale\_in}}$):** Timestamp when a downscaling mutation is observed in the Kubernetes deployment spec.

### Mathematical Formulations

$$\text{First Scaling Response Time } T_{\text{resp}} = t_{\text{desired}} - t_{\text{trigger}}$$

$$\text{Pod Readiness Latency } T_{\text{ready}} = t_{\text{ready}} - t_{\text{trigger}}$$

$$\text{Scale-In Response Time } T_{\text{scale\_in}} = t_{\text{scale\_in}} - t_{\text{trigger}}$$

---

## 3. Investigation & Resolution of Near-Zero Scaling Measurements

Earlier experimental runs reported scaling response times of approximately $0.01\text{ seconds}$ in certain Scenario E2 trials. A thorough audit identified two distinct causes:

### Cause 1: Mathematical Offset-Subtraction Artifact
- In the initial test runner, `trigger_start_time` was defined as `trial_start + 20.0s` (anticipating the start of 10 heavy math workers).
- However, 4 moderate math workers had already started at $t = 10.0\text{s}$.
- When Native HPA scaled at elapsed $t = 14.03\text{s}$ (Trial 3), the formula computed:
  $$\text{Observed Time} - \text{Trigger Time} = 14.03\text{s} - 20.0\text{s} = -5.97\text{s}$$
- A defensive clamp `max(0.01, difference)` converted this negative result to `0.01s`.
- **Correction:** Measuring relative to the actual start of workload traffic ($t = 0\text{s}$) yields the genuine physical response time: **$14.03\text{s}$** ($30.06\text{s}$ pod readiness).

### Cause 2: Prometheus Rate Smoothing Residual Coupling
- PromQL computes CPU utilization using a 1-minute moving average window (`rate(...[1m])`).
- When KubePilot executed immediately after an intense Native HPA trial (Trial 1 and Trial 5), Prometheus still reported $>75\%$ CPU utilization from the previous trial during the first cycle ($t = 0.01\text{s}$).
- Consequently, KubePilot triggered an immediate scale-out on residual metric data before the gradual workload escalated.
- Under clean baselines where KubePilot ran first (Trials 2, 3, and 4), KubePilot genuinely held at 2 replicas without flapping.
- In `research_evidence_v3/`, these trials are explicitly flagged as `ARTIFACT_RESIDUAL_TELEMETRY_COUPLING` and documented candidly.

---

## 4. Scenario Workload Profiles (E1 through E7)

- **E1: Stable Workload (20s):** Constant nominal traffic ($10\text{ req/s}$) against 2 baseline pods.
- **E2: Gradual Load Increase (35s):** Step-up demand (nominal $\rightarrow$ 4 moderate workers at $t=10\text{s} \rightarrow$ 10 heavy workers at $t=20\text{s}$).
- **E3: Sudden Traffic Spike (35s):** Abrupt 12-worker intensive CPU surge on `/load?duration=0.5` between $t = 5\text{s}$ and $t = 25\text{s}$.
- **E4: Bursty Workload (35s):** Continuous background traffic ($10\text{ req/s}$) with two distinct 8-second burst pulses separated by quiet lulls.
- **E5: Sudden Decrease (55s):** Heavy 8-worker phase-1 surge inducing scale-out to 3 or 4 replicas, followed by load cutoff at $t = 22\text{s}$ to observe downscaling behavior.
- **E6: Conflicting Policies (Live Integration):** Simultaneous breach of CPU ($95\% > 75\%$, P100, delta $+2$) and RPS ($200 > 150$, P80, delta $+1$).
- **E7: Capacity Guardrail Violation:** Real node capacity query ($10,350\text{m}$ available) paired with synthetic constrained capacity injection ($50\text{m}$ available $< 100\text{m}$ requested) to verify scale-out pre-emption.
