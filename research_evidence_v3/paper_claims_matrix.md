# KubePilot vs. Native Kubernetes HPA: Paper Claims & Evidence Matrix (v3)

**Project Title:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications (Project 357)  
**Standard:** IEEE Conference Research Paper Empirical Evidence Standards  
**Evaluation Date:** November 5, 2026  
**Auditor / Researcher:** Senior Systems Researcher & Software Test Engineer  
**Dataset:** 52 Reconciled Live Cluster Trials ([`experiment_summary.csv`](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/experiment_summary.csv)) + 18 Live Functional Tests ([`functional_test_report.md`](file:///c:/Users/SRIRAM/design_project/research_evidence_v3/functional_test_report.md))

---

## 1. Paper Claims Verification Matrix

This matrix establishes the scientific validity of claims proposed for the IEEE conference paper based strictly on the third-pass empirical dataset collected on the live Minikube cluster under CPU metric equivalence.

| # | Proposed Conference Paper Claim | Required Evidence | Empirical Evidence Obtained (v3) | Maturity Classification | Critical Academic Limitations & Boundaries |
|:---:|---|---|---|:---:|---|
| **C1** | **Multi-Metric Conflict Resolution** | Multiple simultaneous metric breaches evaluated and resolved without race conditions. | FT-05, FT-06, FT-07, Scenario E6. Competing CPU (95%) and RPS (200) policies evaluated; highest priority rule chosen deterministically. | **Statistically Supported** | Priority integer arbitration ($0 \le P \le 100$). Does not compute continuous multi-objective Pareto frontiers. |
| **C2** | **Deterministic Priority Arbitration** | When multiple policies trigger, higher-priority policy takes precedence deterministically. | FT-06 (`CPU_CRITICAL_SPIKE` Priority 100 beats `RPS_HIGH_TRAFFIC` Priority 80); Scenario E6 live patch scaled from 2 to 4 pods on Kubernetes API. | **Statistically Supported** | Metric threshold must be sustained over any configured duration window before entering arbitration. |
| **C3** | **Anti-Flapping & Hysteresis Protection** | Marginal metric oscillations around threshold boundaries do not induce repeated rapid scaling. | FT-08 (5% hysteresis band suppresses reversal); Scenarios E1, E4, E5 (zero flapping across all nominal and burst runs). | **Statistically Supported** | Hysteresis depends on proper operator calibration (5% default); extreme noise requires cooldown timer support. |
| **C4** | **Pre-Scaling Capacity Guardrails** | Node allocatable resources checked against committed pod requests before scaling; insufficient capacity blocks scale-out. | FT-13 (Real node capacity queried; simulated exhaustion returns `REJECTED`); Scenario E7 (blocked scale-out with `INSUFFICIENT_CPU`, holding deployment at 2 pods). | **Functionally Verified** | Pre-admission heuristic check based on pod requests. Kubernetes `kube-scheduler` remains authoritative for physical placement. |
| **C5** | **Verified Pod Readiness Assurance** | Controller monitors container readiness probes before unlocking subsequent cycles; avoids routing traffic to unready pods. | FT-09, FT-10, FT-15, Scenario E6 ($T_{\text{ready}} = 10.72\text{s}$). Verified `ready_replicas == target_replicas` via Kubernetes CoreV1 API. | **Experimentally Observed** | Active polling verification introduces intentional hold time during pod container creation and startup probe validation. |
| **C6** | **Step-Up Demand Scaling Under Metric Equivalence** | Under identical CPU request thresholds (75m/pod), both controllers scale up appropriately during sustained demand increases. | Scenario E2 (Gradual Increase). Native HPA legitimately scaled in Trials 3 and 5 ($T_{\text{resp}} = 13.58 \pm 0.64\text{s}$). KubePilot held at 2 replicas under clean baselines. | **Experimentally Observed** | Telemetry residual coupling in KubePilot trials following HPA trials required explicit isolation. |
| **C7** | **Reactivity on Short Transient Spikes (<25s)** | KubePilot triggers faster scaling than native HPA on short transient spikes. | Scenario E3 (Sudden Spike). Native HPA triggered in $8.02\text{s}$ (metrics-server fast sample), while KubePilot did not scale (PromQL 1m rate smoothing damped the 20s spike). | **Not Demonstrated / Unsupported** | PromQL 1-minute rate smoothing intentionally dampens short transient spikes. PromQL rate smoothing prioritizes anti-flapping over sub-20s spike reaction. |
| **C8** | **Application Latency Under High Concurrency** | Autoscaling automatically protects microservice latency under high concurrency bursts. | Scenario E3. Both controllers experienced high tail latency ($p_{95} > 1000\text{ms}$) and connection pool saturation (error rates up to 31.4%) during a 12-thread burst against a single-process WSGI app. | **Partially Supported / Conditional** | Single-metric CPU autoscaling cannot prevent connection pool exhaustion during sudden concurrency surges; multi-metric RPS/concurrency policies are required. |
| **C9** | **Orderly Downscaling & Cooldown Enforcement** | Post-surge recovery follows configured cooldown windows without premature de-provisioning. | FT-11 (60s cooldown blocks immediate subsequent scaling); Scenario E5 (boundary verification at `minReplicas = 2`, held by stabilization windows). | **Experimentally Observed** | KubePilot cooldown is configurable per deployment (default 60s); native HPA uses a 300s scale-down stabilization window. |
| **C10** | **Fail-Safe Operation During Outages** | Controller safely falls back to `HOLD` without modifying replicas when telemetry or Kubernetes API is unreachable. | FT-14 (API error handling on invalid namespace); FT-18 (Prometheus connection outage returns `HOLD`; normal operation resumes on recovery). | **Functionally Verified** | During total API outage, no scaling can occur; system maintains last confirmed replica count. |

---

## 2. Explicit Non-Claims (Preserving Academic Integrity)

To comply with rigorous IEEE peer-review standards, the research paper **MUST EXPLICITLY REFRAIN** from asserting the following unsupported claims:

1. **NO Machine Learning / Predictive AI Claim:**  
   *Claim to avoid:* "KubePilot employs AI/ML to forecast traffic surges."  
   *Truth:* KubePilot is 100% deterministic, rule-based policy architecture (PRAH). No neural networks, time-series forecasting, or regression models are used.
2. **NO Replacement of Kubernetes Scheduler:**  
   *Claim to avoid:* "KubePilot replaces the Kubernetes scheduling subsystem."  
   *Truth:* KubePilot mutates `Deployment.spec.replicas`. Node binding and scheduling remain the sole responsibility of the Kubernetes `kube-scheduler`.
3. **NO Infinite Capacity Guarantee:**  
   *Claim to avoid:* "KubePilot guarantees pods will never enter `Pending` state."  
   *Truth:* KubePilot performs pre-admission heuristic checks against committed resource requests. Intervening external pod scheduling can still cause placement contention.
4. **NO Superiority Under Steady Nominal Load:**  
   *Claim to avoid:* "KubePilot outperforms native HPA under steady nominal traffic."  
   *Truth:* Under steady load (E1), both systems maintain 2 replicas, 0 flapping, ~31ms $p_{50}$ latency, and 100% success. KubePilot provides no benefit when scaling is unnecessary.
5. **NO Claim of VPA or KEDA Support:**  
   *Claim to avoid:* "KubePilot supports Vertical Pod Autoscaling or KEDA event sources."  
   *Truth:* Only Horizontal Pod Autoscaling on Kubernetes Deployments using Prometheus metrics is implemented and tested.
