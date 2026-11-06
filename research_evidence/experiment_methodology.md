# KubePilot vs. Native Kubernetes HPA: Experimental Methodology

**Project Title:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications  
**Project ID:** 357 | Alliance University, Bengaluru  
**Standard:** IEEE Conference Experimental Research Standard (Empirical Evaluation)  
**Author:** Software Testing Engineer & Experimental Systems Researcher  
**Date:** November 5, 2026  

---

## 1. Experimental Environment & Infrastructure

All experiments were executed on a live, single-node Kubernetes cluster. No synthetic, simulated, or mocked cluster responses were used for benchmark measurements.

| Environment Property | Measured Specification | Source of Verification |
|---|---|---|
| **Host Operating System** | Microsoft Windows 11 Enterprise (Build 26100, x86_64) | Host OS System Properties |
| **Virtualization Platform** | Docker Desktop 29.2.1 on WSL2 (Linux Kernel 6.6.87.2-microsoft-standard-WSL2) | `kubectl get nodes -o wide` |
| **Kubernetes Distribution** | Minikube v1.38.1 (Single-Node Control Plane) | `minikube status`, `kubectl version` |
| **Kubernetes Version** | Server: v1.35.1 \| Client: v1.36.1 | `kubectl version` |
| **Container Runtime** | `docker://29.2.1` | `kubectl describe node minikube` |
| **Node Allocatable Resources**| 12 vCPUs (12,000m) \| 7.62 GiB Allocatable Memory (7,990,476 KiB) | Node Status Allocatable Spec |
| **Pre-Experiment Node Commit**| Active Pod Requests: 1,250m CPU (10%) \| 882 MiB Memory (11%) | `kubectl describe node minikube` |
| **Target Application** | `sample-web-app` (Flask Microservice, Python 3.11, Alpine Linux) | Deployment `autoscaling-demo/sample-web-app` |
| **Application Resource Quotas**| Requests: CPU 100m, Memory 128Mi \| Limits: CPU 500m, Memory 256Mi | Deployment Pod Template |
| **Baseline Scale Configuration**| Min: 2 Replicas \| Max: 10 Replicas \| Step Up: +2 \| Step Down: -1 | Deployment Spec & Policy YAML |
| **Telemetry Engine** | Prometheus v2.54.0 scraping cAdvisor and application metrics | Namespace `monitoring`, Service Port 9090 |
| **Prometheus Scrape Interval** | 5.0 seconds (Evaluation interval: 10.0 seconds) | Prometheus Configuration Manifest |
| **Native HPA Configuration** | HPA v2: CPU `averageUtilization: 75%`, Min: 2, Max: 10 | `k8s/baseline-hpa.yaml` |
| **KubePilot Configuration** | PRAH Policy `CPU_HIGH_LOAD`: CPU > 75.0%, Delta +1 (or Critical >= 90%, +2) | `policies/scaling-policies.yaml` |

---

## 2. Experimental Design & Fairness Controls

To ensure scientific defensibility and eliminate measurement bias, the following experimental controls were enforced across all trials:

### 2.1 Complete Controller Isolation (No Competing Writes)
A critical flaw in naive autoscaler comparisons is allowing two controllers to mutate the same deployment simultaneously. KubePilot and Native HPA were strictly isolated:
- When Native HPA was tested, KubePilot was set to **safe dry-run preview mode** (`enable_live_execution=False`), and the HPA manifest was applied.
- When KubePilot was tested, Native HPA was **deleted completely from the cluster** (`kubectl delete hpa sample-web-app`), and KubePilot live execution was enabled (`enable_live_execution=True`).
- `StrategyCoordinator.check_competing_hpa()` actively verified zero HPA collision before executing mutations.

### 2.2 Independent Trials with Alternating Execution Order
To prevent execution-order bias (such as the second system always benefiting from warm caches, hot JVM/Python runtimes, or conversely suffering from residual CPU spikes), trials were alternated:
- **Trial 1:** Native HPA $\to$ KubePilot
- **Trial 2:** KubePilot $\to$ Native HPA
- **Trial 3:** Native HPA $\to$ KubePilot
- **Trial 4:** KubePilot $\to$ Native HPA
- **Trial 5:** Native HPA $\to$ KubePilot

### 2.3 Verified Cluster & Telemetry Reset Protocol
Before every single trial, the cluster was subjected to a rigorous 5-step reset protocol:
1. **Load Cease:** All synthetic request generators and math burden threads were stopped.
2. **Controller Teardown:** HPA deleted (if present) and KubePilot dry-run restored.
3. **Scale Restoration:** Deployment patched to 2 replicas (`kubectl scale --replicas=2`).
4. **Pod Drainage Verification:** The controller polled the Kubernetes CoreV1 API until all terminating pods completely exited and exactly 2 `Ready` pods remained:
   $$\text{desiredReplicas} = \text{readyReplicas} = \text{currentReplicas} = 2 \quad \text{and} \quad \text{terminatingPods} = 0$$
5. **Telemetry Cooldown:** The controller queried Prometheus every 1.5s until CPU utilization dropped below 20%:
   $$\text{CPU}_{\text{utilization}} < 20.0\%$$
   This guaranteed that residual CPU burden from a previous run never triggered an artificial scale-out at $t=0$.
6. **State Resets:** KubePilot cooldown timers, hysteresis tracking, and Prometheus breach duration counters were reset.

---

## 3. Workload Scenarios & Configurations

| Scenario ID | Workload Pattern | Duration | Profile & Parameter Details | Evaluation Purpose |
|---|---|---|---|---|
| **E1** | **Stable Workload** | 20.0s | Steady 10 req/s nominal HTTP traffic against `/?format=json`. Zero math burden. | Verify stability, resource conservation, and zero unnecessary scaling (0 flapping). |
| **E2** | **Gradual Increase** | 35.0s | $t \in [0, 10\text{s}]$: 10 req/s nominal.<br>$t \in [10, 22\text{s}]$: 2 concurrent math workers (`/load?duration=0.4s`) + 20 req/s (CPU ~45-60%).<br>$t \in [22, 35\text{s}]$: 6 concurrent math workers (`/load?duration=0.5s`) + bursts (CPU > 75%). Trigger at $t=22.0\text{s}$. | Observe scaling response to progressive demand increase across thresholds. |
| **E3** | **Sudden Traffic Spike** | 35.0s | $t \in [0, 5\text{s}]$: 10 req/s baseline nominal.<br>$t \in [5, 25\text{s}]$: Sudden surge of 8 concurrent math workers (`/load?duration=0.5s`) + 25 req burst loops (`/generate-traffic?count=25`) pushing CPU to 85–95%.<br>$t \in [25, 35\text{s}]$: Stabilization observation. Trigger at $t=5.0\text{s}$. | Measure reaction to sharp demand surge; compare scale action latency, latency distribution, and pod readiness time. |
| **E4** | **Bursty Workload** | 35.0s | $t \in [0, 5\text{s}]$: Baseline nominal.<br>$t \in [5, 15\text{s}]$: Burst 1 (6 math workers).<br>$t \in [15, 25\text{s}]$: Quiet interval (10 req/s nominal).<br>$t \in [25, 35\text{s}]$: Burst 2 (6 math workers). | Evaluate repeated load changes, stability, and cooldown adherence preventing rapid oscillations. |
| **E5** | **Sudden Decrease** | 35.0s | $t \in [0, 10\text{s}]$: Pre-burst (8 math workers) to elevate scale.<br>$t \ge 10\text{s}$: Complete load cutoff (0 req/s). Trigger at $t=10.0\text{s}$. | Observe scale-in response, stabilization delay, and cooldown recovery. |
| **E6** | **Conflicting Policies** | 5.0s | Simultaneous multi-metric breach: CPU = 95.0% (priority 100, delta +2) and HTTP RPS = 200 req/s (priority 60, delta +1). | Evaluate priority arbitration determinism and decision consistency. |
| **E7** | **Guardrail Violation** | 5.0s | Proposed scale-out delta +2 when cluster capacity is synthetically restricted (`INSUFFICIENT_CPU`). | Verify operational guardrails block unsafe mutations and preserve cluster stability. |

---

## 4. Metric Definitions & Measurement Protocols

To ensure rigorous physical meaning, all metrics are defined as follows:

### 4.1 Scaling Timing Metrics
- **Trigger Start Time ($t_{\text{trigger}}$):** Exact wall-clock timestamp when the synthetic demand surge commences (e.g. $t=5.0\text{s}$ for E3).
- **Policy Detection Time ($t_{\text{detected}}$):** Timestamp when the controller's rule evaluation matches the threshold breach.
- **Scaling Request Time ($t_{\text{request}}$):** Timestamp when the controller issues the `patch_namespaced_deployment_scale` API call.
- **Desired Replicas Observed Time ($t_{\text{desired}}$):** Timestamp when the Kubernetes API first returns `spec.replicas == target`.
- **Pod Readiness Observed Time ($t_{\text{ready}}$):** Timestamp when the Kubernetes API confirms `readyReplicas == targetReplicas` and all new container probes report healthy.
- **Scaling Response Time:**
  $$T_{\text{response}} = t_{\text{desired}} - t_{\text{trigger}}$$
- **Pod Readiness Time:**
  $$T_{\text{readiness}} = t_{\text{ready}} - t_{\text{trigger}}$$
  *(Crucial distinction: Replica-count updates and pod readiness are never treated as the same event).*

### 4.2 Application Performance Metrics
- **Throughput ($RPS$):** Total HTTP requests successfully completed divided by duration.
- **Latency Percentiles ($p_{50}, p_{95}, p_{99}$):** Computed from individual client-side round-trip time measurements recorded during each trial:
  $$p_k = \text{percentile}(\{L_1, L_2, \dots, L_N\}, k)$$
- **Error Rate ($E$):**
  $$E = \frac{N_{\text{failed}}}{N_{\text{total}}} \times 100\%$$

### 4.3 Resource Utilization Metrics
- **CPU Utilization:** Queried directly from Prometheus via PromQL evaluating container cAdvisor rates against CPU quota:
  $$\text{CPU}_{\%} = \frac{\sum \text{rate}(container\_cpu\_usage\_seconds\_total[1m])}{\sum container\_spec\_cpu\_quota / \text{avg}(container\_spec\_cpu\_period)} \times 100$$
- **Memory Utilization:** Ratio of `container_memory_working_set_bytes` to limit bytes.

---

## 5. Statistical Methodology

For primary scenarios with 5 independent trials (E1 and E3), results are summarized using standard sample statistics:
- **Sample Mean ($\bar{x}$):** $\bar{x} = \frac{1}{n}\sum_{i=1}^n x_i$
- **Sample Median ($\tilde{x}$):** Value separating higher half from lower half.
- **Sample Standard Deviation ($s$):** $s = \sqrt{\frac{1}{n-1}\sum_{i=1}^n (x_i - \bar{x})^2}$
- **Range:** $[\min(x), \max(x)]$
- **Two-Sample Unpaired Comparison:** Evaluated using Welch's $t$-test (unequal variances) where appropriate.
