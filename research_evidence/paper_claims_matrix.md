# KubePilot vs. Native Kubernetes HPA: Paper Claims & Evidence Matrix

**Project:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications (Project 357)  
**Standard:** IEEE Conference Research Paper Evidence Standards  
**Evaluation Date:** November 5, 2026  
**Auditor / Researcher:** Senior Systems Researcher & Software Test Engineer  

---

## 1. Executive Claims Matrix

This matrix establishes the scientific validity of potential conference paper claims based strictly on the empirical measurements, functional tests (FT-01 to FT-18), and comparative benchmark experiments (E1 to E7) collected on the live Minikube cluster.

| Proposed Paper Claim | Evidence Required | Evidence Obtained | Supported? | Critical Limitations & Academic Boundary |
|---|---|---|:---:|---|
| **Multi-Metric Policy Conflict Resolution** | Empirical demonstration that multiple simultaneous metric breaches (e.g. CPU + HTTP request rate) are evaluated and resolved deterministically without race conditions. | FT-05, FT-06, FT-07, Scenario E6. Verified that simultaneous breaches are resolved according to operator-defined priority rankings and tie-breaking policies. | **YES** | Evaluates static, operator-defined priority integers ($0 \le P \le 100$); does not compute non-linear multi-objective Pareto optimization. |
| **Deterministic Priority Arbitration** | When competing policies activate simultaneously, the higher-priority action deterministically takes precedence. | FT-06 (`CPU_CRITICAL_SPIKE` at Priority 100 wins over `RPS_HIGH_TRAFFIC` at Priority 60), FT-07 (`SCALE_OUT_WINS` on equal priority 90). | **YES** | Policies with duration thresholds must sustain the breach for the full interval before participating in arbitration. |
| **Anti-Flapping & Hysteresis Protection** | Verification that marginal metric oscillations around threshold boundaries do not induce repeated rapid scale-out/scale-in cycles. | FT-08 (5% hysteresis band suppresses direction reversal), Scenario E1 (0 scaling events across 5 independent trials for both systems). | **YES** | Hysteresis depends on proper operator calibration (5% default); extreme traffic oscillation may still require cooldown assistance. |
| **Pre-Scaling Capacity Guardrails** | Verification that node allocatable resources are checked against committed pod requests before mutation, and insufficient capacity blocks scale-out. | FT-13 (Real node capacity evaluated; simulated resource exhaustion returns `REJECTED` and `INSUFFICIENT_CPU`), Scenario E7. Issue A defect corrected and verified. | **YES** | Heuristic pre-admission check based on committed requests; the native Kubernetes `kube-scheduler` remains authoritative for physical placement. |
| **Reactivity Advantage During Rapid Surges** | Direct comparative latency measurement showing KubePilot detects and triggers scale-out faster than native HPA under sudden traffic spikes. | Scenario E3 (5 independent alternating trials). KubePilot reaction latency measured from trigger onset vs Native HPA metrics-server lag. | **YES** | Lower bound is constrained by Prometheus scrape interval (5.0s). HPA latency is primarily attributable to metrics-server 15s–60s windowing. |
| **Verified Pod Readiness Assurance** | Proof that KubePilot tracks and verifies container probe readiness before releasing execution locks, whereas native HPA operates asynchronously. | FT-09, FT-10, FT-15, `kubernetes_executor.py` live polling loop verifying `ready_replicas == target_replicas`. | **YES** | Verification loop blocks the control cycle for several seconds during pod initialization; requires proper cycle pacing. |
| **Application Latency Reduction Under Load** | Client-side round-trip time measurements ($p_{50}, p_{95}, p_{99}$) demonstrating latency benefits under surge traffic. | Scenario E3 individual request latency distributions. Quicker scale-out distributes incoming requests across more pods, mitigating queue saturation. | **YES** | Under steady nominal load (E1), latency is identical between HPA and KubePilot (~28–30ms), showing zero baseline penalty. |
| **Resource Utilization & Conservation** | Comparison of CPU and memory utilization relative to allocated quotas across steady and surge scenarios. | Scenarios E1, E2, E3, E5 telemetry samples. Under nominal load, both maintain identical minimum scale (2 pods). Under spike, earlier scale-out prevents CPU saturation. | **YES** | KubePilot requires running an external controller component (~50m CPU, 70MiB RAM footprint) which native in-tree HPA does not require. |
| **Orderly Downscaling & Cooldown Enforcement** | Verification that post-surge recovery follows configured cooldown windows without premature de-provisioning. | FT-11 (60s cooldown blocks immediate subsequent scaling), Scenario E4 (Bursty Workload), Scenario E5 (Sudden Decrease). | **YES** | Native HPA defaults to a 300s (5-minute) scale-down stabilization window; KubePilot's configurable 60s cooldown allows faster, controlled reclamation. |
| **Execution Fault Recovery & Safety** | Proof that the controller safely falls back to `HOLD` without mutation when Prometheus or Kubernetes API encounters temporary failure. | FT-14 (Graceful handling of 404/invalid namespace), FT-18 (Simulated Prometheus connection timeout yields `HOLD`; normal operation resumes upon recovery). | **YES** | During total API outage, no new scaling can occur; system holds last confirmed replica count. |

---

## 2. Explicit Non-Claims (Preserving Academic & Scientific Integrity)

The following claims **MUST NOT** be asserted in the IEEE conference paper, as they are either unsupported by the codebase or explicitly prohibited by the evaluation constraints:

1. **NO Machine Learning / AI Claim:**  
   *Claim to avoid:* "KubePilot uses AI, machine learning, deep learning, or neural networks to predict scaling demand."  
   *Reality:* KubePilot is strictly a deterministic, rule-based policy engine (PRAH). There are zero ML models, regression trees, or forecasting algorithms in the implementation.
2. **NO Replacement of Kubernetes Scheduler:**  
   *Claim to avoid:* "KubePilot replaces the native Kubernetes scheduler or container runtime."  
   *Reality:* KubePilot acts as a client controller adjusting `Deployment.spec.replicas`. The Kubernetes `kube-scheduler` remains solely responsible for pod placement, node affinity, and binding.
3. **NO Infinite Capacity Guarantee:**  
   *Claim to avoid:* "KubePilot guarantees that pods will never enter `Pending` state."  
   *Reality:* KubePilot performs pre-scaling heuristic validation using node allocatable requests. Intervening external pod scheduling can still cause placement contention.
4. **NO Superiority Under Steady Nominal Load:**  
   *Claim to avoid:* "KubePilot outperforms native HPA under steady, nominal workloads."  
   *Reality:* Under constant nominal traffic (E1), both systems maintain exactly 2 replicas, zero flapping, ~28–30ms mean latency, and 100% request success. KubePilot provides no latency or throughput advantage when scaling is not required.
5. **NO Claim for VPA or KEDA Support:**  
   *Claim to avoid:* "KubePilot supports Vertical Pod Autoscaling (VPA) or KEDA event-driven scaling."  
   *Reality:* Only Horizontal Pod Autoscaling on Deployments is implemented and tested.
