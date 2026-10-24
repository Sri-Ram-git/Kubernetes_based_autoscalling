# KubePilot: Kubernetes-Based Auto-Scaling Framework for Cloud Applications

**Alliance University, Bengaluru &bull; Department of Computer Science & Engineering**  
**Design Project &bull; Project ID: 357**  
**Core Algorithm:** **PRAH** (*Policy-Driven Reactive-Arbitration Heuristic*)  
**Verified Environment:** Kubernetes (Minikube Docker Driver) &bull; Prometheus &bull; Python 3.13 / Flask / TailwindCSS

---

## 1. Executive Summary

**KubePilot (Project 357)** is an intelligent, policy-driven auto-scaling coordination framework designed for modern cloud-native workloads on Kubernetes. Standard Kubernetes Horizontal Pod Autoscaler (HPA) operates reactively against single metrics (e.g. CPU%), which frequently causes delayed scaling, container saturation, and flapping thrashing under bursty or multi-dimensional traffic loads.

KubePilot solves these limitations through:
* **Multi-Metric Telemetry Pipeline:** Simultaneous ingestion of Prometheus PromQL vectors (CPU, memory, request throughput, p95 latency, 5xx error rate) with resilient fallback.
* **Declarative Multi-Metric Policies:** Expressive YAML rules with priority scoring and mathematical target functions.
* **PRAH Decision Engine:** Priority-weighted arbitration resolving competing recommendations with an availability-first bias.
* **Resilient Guardrails:** Triple-layer enforcement of a mandatory 2-pod baseline floor (`min_replicas: 2`), ceiling caps (`max_replicas: 10`), asymmetric cooldowns (60s up / 180s down), and 5-sample hysteresis smoothing.
* **Integrated Web Dashboard & REST API:** Unified operator console for live telemetry, pod inspection, policy editing, decision auditing, and system health checks.
* **Automated Empirical Benchmarking:** Built-in experiment runner executing reproducible comparisons between Native HPA and KubePilot PRAH under identical workloads.

---

## 2. System Architecture

```
+--------------------------------------------------------------------------------+
|                             KUBEPILOT CONTROL PLANE                            |
|                                                                                |
|  +--------------------+     +----------------------+     +------------------+  |
|  | Telemetry Collector|---->| PRAH Decision Engine |---->| Guardrail Engine |  |
|  | (Prometheus :9090) |     | (Multi-Rule Arbiter) |     | (Bounds & Cool)  |  |
|  +--------------------+     +----------------------+     +------------------+  |
|           ^                            |                           |           |
|           |                            v                           v           |
|           |                 +----------------------+     +------------------+  |
|           |                 | Decision Audit Log   |     | K8s API Executor |  |
|           |                 | (logs/decisions.json)|     | (Scale Patch)    |  |
|           |                 +----------------------+     +------------------+  |
+-----------|--------------------------------------------------------|-----------+
            |                                                        |
            | PromQL HTTP                                            | HTTPS / API
            v                                                        v
+--------------------------+                              +----------------------+
|  Prometheus Monitoring   |                              |  Kubernetes Cluster  |
|  (autoscaling-demo)      |                              |  (sample-web-app)    |
+--------------------------+                              +----------------------+
```

---

## 3. Clean Repository Layout

The repository is strictly structured into source code, configurations, test suites, and documentation:

```
c:\Users\SRIRAM\design_project\
├── controller/                 # Autoscaling Control Plane & Engine
│   ├── config.py               # Central configuration and environment settings
│   ├── decision_controller.py  # PRAH decision arbitration engine
│   ├── decision_logger.py      # Append-only JSONL decision audit logger
│   ├── experiment_runner.py    # Benchmark runner (Baseline HPA vs KubePilot)
│   ├── guardrails.py           # Safety limits, cooldown, and hysteresis engine
│   ├── kubernetes_executor.py  # Resilient Kubernetes API client and mutator
│   ├── main.py                 # Standalone controller entrypoint daemon
│   ├── policy_engine.py        # Declarative YAML policy parser and evaluator
│   ├── strategy_coordinator.py # Master reconciliation loop and scheduler
│   └── telemetry.py            # Multi-source metric collector (Prometheus / K8s)
├── dashboard/                  # Web Interface & Operational REST APIs
│   ├── app.py                  # Flask application server and route definitions
│   ├── requirements.txt        # Dashboard runtime dependencies
│   ├── static/                 # CSS styling, JavaScript graphs, and branding
│   └── templates/              # Jinja2 HTML templates for all views
├── policies/                   # Declarative Autoscaling Configuration
│   └── scaling-policies.yaml   # Canonical scaling rules and guardrail parameters
├── monitoring/                 # Telemetry & Observability Definitions
│   ├── prometheus.yml          # Local Prometheus scrape configuration
│   ├── prometheus-config.yaml  # In-cluster ConfigMap manifest
│   ├── prometheus-deployment.yaml # In-cluster Prometheus deployment & service
│   └── prometheus-values.yaml  # Helm values configuration
├── k8s/                        # Kubernetes Infrastructure Manifests
│   ├── namespace.yaml          # Definition for `autoscaling-demo` namespace
│   ├── baseline-hpa.yaml       # Native Kubernetes HorizontalPodAutoscaler
│   ├── controller-rbac.yaml    # ClusterRole and ServiceAccount for controller
│   ├── controller-deployment.yaml # In-cluster Deployment manifest for KubePilot
│   └── dashboard-deployment.yaml  # In-cluster Deployment manifest for Dashboard
├── app/                        # Benchmark Target Workload Application
│   ├── app.py                  # Flask mock workload with CPU burn endpoints
│   ├── Dockerfile              # Container image definition
│   └── sample-app.yaml         # Kubernetes Deployment & Service manifests
├── experiments/                # Experiment Benchmark Artifacts & Output
│   └── results/                # CSV and JSON empirical run data
├── tests/                      # Automated Regression & Unit Test Suite (102 Tests)
│   ├── test_telemetry.py       # Metrics collection & fallback tests
│   ├── test_policy_engine.py   # Policy parsing and evaluation tests
│   ├── test_decision_controller.py # PRAH arbitration unit tests
│   ├── test_guardrails.py      # Boundary and rate-limit safety tests
│   ├── test_hysteresis.py      # Window smoothing and flapping tests
│   ├── test_kubernetes_executor.py # K8s client and scale patch tests
│   ├── test_dashboard_api.py   # Web API endpoint validation tests
│   ├── test_experiments.py     # Workload generator & runner tests
│   └── test_fixes_regression.py # Live bug regression verification
├── scripts/                    # Maintenance & Documentation Generators
│   └── generate_docs_pdf.py    # ReportLab PDF publication generator
└── documents/                  # Comprehensive Documentation Library
    ├── README.md               # Documentation suite index and navigation guide
    ├── markdown/               # Authoritative technical Markdown documents
    │   ├── PROJECT_OVERVIEW.md
    │   ├── SYSTEM_ARCHITECTURE.md
    │   ├── IMPLEMENTATION_DETAILS.md
    │   ├── SETUP_AND_EXECUTION.md
    │   ├── TESTING_AND_VERIFICATION.md
    │   ├── EXPERIMENTS_AND_EVALUATION.md
    │   ├── API_REFERENCE.md
    │   └── TROUBLESHOOTING.md
    ├── pdf/                    # High-quality compiled reference PDFs
    │   ├── PROJECT_REFERENCE.pdf
    │   ├── SYSTEM_ARCHITECTURE.pdf
    │   ├── SETUP_AND_EXECUTION.pdf
    │   └── TESTING_AND_VERIFICATION.pdf
    └── archive/                # Historical review records and legacy reports
```

---

## 4. Quick Start & Execution

### 4.1 Prerequisites
* Windows 10/11, macOS, or Linux
* Docker Desktop & Minikube (`minikube start --driver=docker`)
* Python 3.11+ (Python 3.13 verified)

### 4.2 Start Target Workload and Prometheus
```powershell
# 1. Create namespace and deploy sample web application (target: 2/2 ready)
kubectl apply -f k8s/namespace.yaml
kubectl apply -f app/sample-app.yaml

# 2. Deploy Prometheus and port-forward to localhost:9090
kubectl apply -f monitoring/prometheus-config.yaml
kubectl apply -f monitoring/prometheus-deployment.yaml
kubectl -n autoscaling-demo port-forward svc/prometheus 9090:9090
```

### 4.3 Launch KubePilot Dashboard & Controller
```powershell
# Install dependencies
pip install -r dashboard/requirements.txt reportlab pytest

# Start web dashboard (embedded controller running in background)
python -m dashboard.app
```
* **Dashboard UI:** `http://localhost:5055`
* **Liveness:** `http://localhost:5055/healthz`
* **Readiness:** `http://localhost:5055/readyz`

### 4.4 Run Benchmark Experiments
```powershell
# Run Stable Workload and Sudden Traffic Spike experiments (Baseline vs KubePilot)
python -m controller.experiment_runner --experiment all --mode both
```

---

## 5. Automated Test Suite (102 Tests)

The framework includes 102 automated tests across 9 test modules with a 100% pass rate:

```powershell
python -m pytest tests/ -v
```

```text
============================= test session starts =============================
collected 102 items

tests/test_dashboard_api.py .............                                [ 12%]
tests/test_decision_controller.py ...............                        [ 27%]
tests/test_experiments.py ......                                        [ 33%]
tests/test_fixes_regression.py .......                                   [ 40%]
tests/test_guardrails.py ..............                                  [ 53%]
tests/test_hysteresis.py ..........                                      [ 63%]
tests/test_kubernetes_executor.py ...........                           [ 74%]
tests/test_policy_engine.py ..............                               [ 88%]
tests/test_telemetry.py ............                                     [100%]

============================= 102 passed in 1.48s =============================
```

---

## 6. Authoritative Documentation Library

Complete technical manuals and published reference documents are organized in [`documents/`](file:///c:/Users/SRIRAM/design_project/documents/README.md):

| Documentation Guide | Format | Highlights |
| :--- | :--- | :--- |
| [**Project Overview**](file:///c:/Users/SRIRAM/design_project/documents/markdown/PROJECT_OVERVIEW.md) | Markdown | Research problem, native HPA limits, PRAH algorithm motivation, system scope. |
| [**System Architecture**](file:///c:/Users/SRIRAM/design_project/documents/markdown/SYSTEM_ARCHITECTURE.md) | Markdown | Control plane topology, sequence diagrams, reconciliation loop, guardrail state machine. |
| [**Implementation Details**](file:///c:/Users/SRIRAM/design_project/documents/markdown/IMPLEMENTATION_DETAILS.md) | Markdown | Codebase walkthrough, module reference, classes, methods, and configurations. |
| [**Setup and Execution**](file:///c:/Users/SRIRAM/design_project/documents/markdown/SETUP_AND_EXECUTION.md) | Markdown | Prerequisites, cluster provisioning, commands, verification, and teardown. |
| [**Testing and Verification**](file:///c:/Users/SRIRAM/design_project/documents/markdown/TESTING_AND_VERIFICATION.md) | Markdown | 102 automated tests inventory, live cluster acceptance checks, and coverage. |
| [**Experiments & Evaluation**](file:///c:/Users/SRIRAM/design_project/documents/markdown/EXPERIMENTS_AND_EVALUATION.md) | Markdown | Benchmark analysis: Stable Workload and Sudden Traffic Spike empirical data. |
| [**API Reference**](file:///c:/Users/SRIRAM/design_project/documents/markdown/API_REFERENCE.md) | Markdown | Complete REST API specification with JSON request/response contracts and probes. |
| [**Troubleshooting**](file:///c:/Users/SRIRAM/design_project/documents/markdown/TROUBLESHOOTING.md) | Markdown | Step-by-step resolution of Minikube drops, Prometheus errors, cooldowns, and port conflicts. |
| [**Project Reference PDF**](file:///c:/Users/SRIRAM/design_project/documents/pdf/PROJECT_REFERENCE.pdf) | PDF | Published technical overview & empirical benchmark evaluation manual. |
| [**System Architecture PDF**](file:///c:/Users/SRIRAM/design_project/documents/pdf/SYSTEM_ARCHITECTURE.pdf) | PDF | Published system architecture specification and module contracts. |
| [**Setup & Execution PDF**](file:///c:/Users/SRIRAM/design_project/documents/pdf/SETUP_AND_EXECUTION.pdf) | PDF | Published operational deployment and cluster administration guide. |
| [**Testing & Verification PDF**](file:///c:/Users/SRIRAM/design_project/documents/pdf/TESTING_AND_VERIFICATION.pdf) | PDF | Published QA validation report and API contract reference. |

---

## 7. License & Credits

Developed for **Project 357: Kubernetes-Based Auto-Scaling Framework for Cloud Applications**, Department of Computer Science & Engineering, Alliance University, Bengaluru.
