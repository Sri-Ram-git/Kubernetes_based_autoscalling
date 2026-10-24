# Project 357: Kubernetes-Based Auto-Scaling Framework for Cloud Applications (KubePilot)

## Executive Summary

**Project 357 (KubePilot)** is an intelligent, policy-driven auto-scaling coordination framework designed for modern cloud-native applications deployed on Kubernetes. Modern containerized microservices face volatile, dynamic traffic patterns ranging from predictable diurnal cycles to abrupt, high-volume traffic spikes and bursty oscillations.

While standard Kubernetes provides the native Horizontal Pod Autoscaler (HPA), native autoscaling exhibits critical operational limitations in production environments:
1. **Single-Metric Tunnel Vision:** Native HPA typically couples scaling decisions to a single resource metric (e.g., target CPU utilization percentage) without holistically arbitrating across composite metrics (CPU, memory, request throughput, latency p95, and error rates).
2. **Reactive Lag & Slow Response:** Reactive threshold evaluation inherently delays scaling actions until resource pressure has already saturated running containers, leading to transient request dropping, elevated latencies, and SLA breaches.
3. **Flapping and Oscillation Thrashing:** Naive scale-up and scale-down thresholds often induce rapid pod creation and termination cycles ("flapping"), which destabilize cluster scheduling and waste computing resources.
4. **Lack of Multi-Strategy Arbitration:** Organizations often need to balance aggressive scale-up policies for mission-critical spikes against conservative, cost-optimized scale-down schedules. Native HPA cannot reconcile competing, prioritized business rules.

**KubePilot** solves these challenges by introducing a **Policy-Driven Reactive-Arbitration Heuristic (PRAH)** engine, comprehensive multi-metric telemetry ingestion, intelligent hysteresis windows, and rigorous safety guardrails. KubePilot operates alongside or above Kubernetes clusters to deliver rapid, stable, and cost-effective workload elasticity.

---

## Problem Statement & Research Motivation

### Limitations of Native Kubernetes HPA
In standard Kubernetes deployments, the Horizontal Pod Autoscaler periodically polls the metrics API (e.g., `metrics.k8s.io` via `metrics-server` or custom metrics adapters) every 15 seconds by default. The standard algorithm computes desired replicas as:

$$\text{desiredReplicas} = \left\lceil \text{currentReplicas} \times \left( \frac{\text{currentMetricValue}}{\text{desiredMetricValue}} \right) \right\rceil$$

While mathematically straightforward, this model exhibits severe shortcomings under real-world cloud conditions:
* **Metric Skew & Cold Starts:** New pods take time to initialize and warm their runtimes. During initialization, existing pods remain overloaded, prompting HPA to trigger redundant, compounding scale-up events (overshoot).
* **Latency Insensitivity:** Applications can experience critical request latency degradation (due to database contention, external service calls, or thread pool exhaustion) while CPU utilization remains well below scaling thresholds.
* **Aggressive Scale-Down Risk:** Brief lulls in traffic can trigger premature scale-down actions, leaving the application vulnerable to immediate subsequent traffic surges.

### The KubePilot Solution
KubePilot bridges the gap between infrastructure metrics and application-level business intent by implementing:
1. **Multi-Metric Telemetry Pipeline:** Aggregates Prometheus metrics, Kubernetes API metrics, and cAdvisor container performance statistics into a unified telemetry stream.
2. **Configurable Declarative Policies:** Expressive YAML-based policy definitions specifying multi-attribute conditions (CPU, memory, RPS, p95 latency, error rates, queue depths) with explicit priority weighting.
3. **PRAH Decision Engine:** Evaluates all active policies, arbitrates conflicting recommendations, calculates composite confidence scores, and determines the mathematically optimal replica target.
4. **Resilient Safety Guardrails:** Enforces hard boundary floors (`min_replicas = 2`), ceiling caps (`max_replicas = 10`), maximum step rates (`max_scale_up_step = 3`, `max_scale_down_step = 1`), asymmetric cooldown timers (60s scale-up, 180s scale-down), and flapping prevention windows.
5. **Observability & Experimentation:** Real-time web-based operational dashboard, structured JSONL audit trail, and automated benchmarking against native HPA under identical synthetic workloads.

---

## Core Objectives

| Objective | Target Requirement | KubePilot Implementation |
| :--- | :--- | :--- |
| **High Availability Baseline** | Maintain steady baseline replica count to prevent single-pod cold failures. | Enforces `min_replicas: 2` in guardrails, controller configuration, and policy specs. |
| **Multi-Metric Arbitration** | Simultaneously evaluate CPU, Memory, Latency, and Throughput. | Multi-rule `PolicyEngine` with weighted priority scoring and conflict resolution. |
| **Oscillation Prevention** | Prevent rapid pod thrashing within short sliding windows. | Hysteresis sliding window (5 samples) and minimum cooldown enforcement. |
| **Auditability & Traceability** | Every scaling action, rejected proposal, and reason recorded. | Append-only `DecisionLogger` writing structured JSONL entries with full telemetry context. |
| **Zero Disruptive Overhead** | Work transparently on standard Kubernetes clusters without custom CRD dependencies. | Uses standard Kubernetes Python client to patch deployment `spec.replicas` directly. |
| **Observable Web Interface** | Unified operator UI for metrics, decisions, workloads, and cluster state. | Lightweight Flask/Tailwind dashboard with REST APIs and live telemetry graphs. |

---

## System Boundaries & Operational Scope

```
+--------------------------------------------------------------------------------+
|                               KUBEPILOT SYSTEM                                 |
|                                                                                |
|  +--------------------+    +----------------------+    +--------------------+  |
|  | Telemetry Collector|--->| PRAH Decision Engine |--->| Guardrail Engine   |  |
|  +--------------------+    +----------------------+    +--------------------+  |
|           ^                           |                           |            |
|           |                           v                           v            |
|           |                +----------------------+    +--------------------+  |
|           |                | Audit Decision Log   |    | Kubernetes Executor|  |
|           |                +----------------------+    +--------------------+  |
+-----------|-------------------------------------------------------|------------+
            |                                                       |
            | HTTP / PromQL                                         | HTTPS / API
            v                                                       v
+--------------------------+                             +-----------------------+
|  Monitoring Pipeline     |                             |  Kubernetes Cluster   |
|  (Prometheus / cAdvisor) |                             |  (Minikube / EKS/GKE) |
+--------------------------+                             +-----------------------+
```

### In-Scope Capabilities
* Integration with Minikube, Docker desktop, and standard production Kubernetes clusters.
* Metric scraping from Prometheus (`http://localhost:9090` or in-cluster service).
* Direct scaling actuation on target deployments (e.g., `sample-web-app` in `autoscaling-demo`).
* Execution of reproducible benchmark experiments: Stable Workload and Sudden Traffic Spike.
* Interactive web dashboard serving real-time telemetry, active policies, decisions, and system health.

### Out-of-Scope Capabilities
* Vertical Pod Autoscaling (VPA) modifying in-place CPU/Memory container requests and limits.
* Cluster node autoscaling (Cluster Autoscaler / Karpenter node provisioning).
* Custom Kubernetes Custom Resource Definitions (CRDs) requiring cluster-admin admission webhooks.
