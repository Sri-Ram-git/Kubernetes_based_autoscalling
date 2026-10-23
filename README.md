# Kubernetes-Based Auto-Scaling Framework for Cloud Applications

**Alliance University, Bengaluru &bull; Department of Computer Science & Engineering**  
**Design Project-I &bull; Project ID: 357**  
**Proposed Algorithm:** **PRAH** (*Priority-based Rule Arbitration with Hysteresis*)  
**Scope:** Milestone 1 (First 50% Functional Core)

---

## 1. Project Overview & Architectural Principles

Modern cloud microservices experience unpredictable traffic surges, load imbalances, and resource bottlenecks. While native Kubernetes provides the Horizontal Pod Autoscaler (HPA), native mechanisms rely solely on simple ratio calculations without supporting priority-based arbitration across competing metrics, multi-rule conflict resolution, or operational guardrails against telemetry degradation.

This project delivers a **centralized, policy-based scaling decision framework** for Kubernetes workloads.

### Strict Determinism Requirement
> **Strict Engineering Rule:** NO MACHINE LEARNING, NO FORECASTING, NO PREDICTIVE MODELS, AND NO AI-BASED DECISION-MAKING.  
> Every scaling decision is 100% deterministic, fully explainable, configurable via YAML policies, and auditable through structured logs.

---

## 2. System Architecture & The PRAH Pipeline

The framework executes an explainable, end-to-end control cycle:

```
+---------------------------+
| Prometheus Telemetry API   |
+-------------+-------------+
              | (Instant Vector Queries & Timestamps)
              v
+-------------+-------------+
| Telemetry Processor       | ---> [Validates Freshness / Detects Stale or Missing Data]
+-------------+-------------+      [Triggers Safe Fallback HOLD if Data Degraded]
              |
              v
+-------------+-------------+
| Policy Engine             | ---> [Evaluates Configurable Operators (>, <, >=, <=)]
+-------------+-------------+      [Tracks Persistence Window (Duration Seconds)]
              |
              v
+-------------+-------------+
| PRAH Decision Controller  | ---> 1. Sorts Competing Proposals by Priority Descending
+-------------+-------------+      2. Resolves Conflicts (Scale-Out Wins on Equal Priority)
              |                    3. Evaluates Hysteresis Band (Anti-Flapping Protection)
              |                    4. Enforces Directional Cooldown Timers
              v
+-------------+-------------+
| Guardrail Safety Engine   | ---> [Enforces [min_replicas, max_replicas] Bounds]
+-------------+-------------+      [Clamps Step Sizes / Rejects Redundant Actions]
              |                    [Enforces DRY-RUN vs LIVE EXECUTION Modes]
              v
+-------------+-------------+
| Strategy Coordinator      | ---> [Guards Single-Controller Ownership Model]
+-------------+-------------+      [Verifies Absence of Competing Native HPA]
              |
              v
+-------------+-------------+
| Kubernetes API Executor   | ---> [Patches Deployment Scale Subresource]
+-------------+-------------+      [Re-queries Kubernetes API to Confirm New State]
              |
              v
+-------------+-------------+
| Structured Audit Logger   | ---> [Appends JSON Lines to logs/decisions.jsonl]
+---------------------------+      [Feeds Real-Time Web Dashboard API]
```

---

## 3. Repository Structure

```
kubernetes-autoscaling-framework/
├── app/
│   ├── app.py                      # Instrument flask app with /metrics and /load
│   ├── Dockerfile                  # Container definition for sample app
│   ├── requirements.txt            # App dependencies (Flask, prometheus-client)
│   └── sample-app.yaml             # K8s Deployment & Service with cAdvisor resource limits
├── controller/
│   ├── __init__.py                 # Controller package root
│   ├── main.py                     # Lifecycle coordinator & evaluation loop
│   ├── config.py                   # Environment & YAML configuration loader
│   ├── telemetry.py                # Prometheus API client with staleness & missing data checks
│   ├── policy_engine.py            # Rule condition evaluation and duration windowing
│   ├── decision_controller.py      # PRAH algorithm (priority, tie-breaking, hysteresis, cooldown)
│   ├── strategy_coordinator.py     # Ownership coordinator and HPA collision detection
│   ├── guardrails.py               # Operational boundaries, step clamping, dry-run safety
│   ├── kubernetes_executor.py      # K8s API client with scale patching and state verification
│   └── decision_logger.py          # Structured JSON Lines audit logger & memory ring buffer
├── dashboard/
│   ├── app.py                      # Flask REST API server for operator dashboard
│   ├── requirements.txt            # Dashboard dependencies
│   ├── templates/
│   │   └── index.html              # Dark-themed operator UI (responsive cards, audit tables)
│   └── static/
│       ├── css/style.css           # Typography, status pills, dark layout styling
│       └── js/dashboard.js         # Real-time polling, scenario injection, modal confirmation
├── policies/
│   └── scaling-policies.yaml       # Configurable multi-metric scaling rules and thresholds
├── monitoring/
│   ├── prometheus-config.yaml      # Standalone Prometheus ConfigMap for Minikube
│   ├── prometheus-deployment.yaml  # Standalone Prometheus Deployment, Service, & ClusterRole
│   └── prometheus-values.yaml      # Helm values for Prometheus chart
├── k8s/
│   ├── namespace.yaml              # Dedicated autoscaling-demo and monitoring namespaces
│   ├── policies-configmap.yaml     # Single-source-of-truth ConfigMap for scaling policies
│   ├── controller-rbac.yaml        # ServiceAccount, Role, and RoleBinding for Deployment scaling
│   ├── controller-deployment.yaml  # Controller in-cluster deployment manifest
│   └── dashboard-deployment.yaml   # Dashboard in-cluster NodePort deployment
├── tests/
│   ├── __init__.py
│   ├── test_policy_engine.py       # YAML parsing, operator validity, duration persistence
│   ├── test_decision_controller.py # Priority arbitration, tie-breaking, fallback HOLD
│   ├── test_hysteresis.py          # Cooldown enforcement, anti-flapping direction reversal
│   ├── test_guardrails.py          # Min/max boundaries, step clamping, redundant filtering
│   ├── test_telemetry.py           # Prometheus query parsing, stale metric detection
│   ├── test_kubernetes_executor.py # Dry-run preview, scaling verification, API error handling
│   └── test_dashboard_api.py       # REST API endpoint tests, health checks, & error states
├── logs/
│   └── .gitkeep                    # Retains logs directory in git
├── .env.example                    # Template environment variables
├── .gitignore                      # Git ignore patterns
├── Dockerfile                      # Root Dockerfile for Framework Controller & Dashboard
├── docker-compose.yaml             # Multi-container local demo compose file
├── Makefile                        # Convenience targets for test, run, deploy
├── UI_COMPONENTS.md                # Comprehensive component catalog & behavior manual
├── ARCHITECTURE_AND_UI_FLOW.md     # Verified data flow diagram & pipeline interaction spec
├── VERIFICATION_REPORT.md          # Real verification logs, executed commands, & criteria audit
└── README.md                       # Complete documentation & demonstration manual
```

---

## 4. Setup and Quick Start

### Prerequisites
- Python 3.11 or compatible Python version (e.g. Python 3.13)
- Docker Desktop (optional for local mock testing; required for Minikube)
- Minikube & kubectl (required for live cluster demonstration)

### Local Environment Setup

#### Windows PowerShell
```powershell
# 1. Clone or navigate to the repository
cd C:\Users\SRIRAM\design_project

# 2. Install Python dependencies
python -m pip install -r app/requirements.txt
python -m pip install -r dashboard/requirements.txt
python -m pip install pytest pytest-cov
```

#### Linux / macOS
```bash
cd ~/design_project
python3 -m pip install -r app/requirements.txt
python3 -m pip install -r dashboard/requirements.txt
python3 -m pip install pytest pytest-cov
```

---

## 5. Running Automated Unit & Safety Tests

The automated test suite runs completely independently of external services (external Prometheus and Kubernetes calls are cleanly mocked and isolated).

Run all 59 tests:
```powershell
python -m pytest tests/ -v
```

### Test Coverage Summary:
- **`test_telemetry.py` (9 tests)**: Prometheus instant vector parsing, staleness detection (> 60s), non-finite rejection (`NaN`, `+Inf`), empty result handling (`MISSING`), HTTP error resilience (`ERROR`, `UNAVAILABLE`), live scrape target status discovery (`get_targets_status`), and simulated labeling.
- **`test_policy_engine.py` (9 tests)**: Valid YAML schema parsing, rejection of invalid operators/actions/deltas, condition evaluation (`>`, `<`, `>=`, `<=`), duration window persistence.
- **`test_decision_controller.py` (4 tests)**: Highest priority rule arbitration, equal-priority conflict resolution (scale-out takes precedence over scale-in to preserve SLAs), missing metric safe fallback (HOLD), stale metric safe fallback (HOLD).
- **`test_guardrails.py` (8 tests)**: Enforcing `min_replicas` (cannot scale below 1), enforcing `max_replicas` (cannot scale above 10), clamping `max_scale_step_up` and `max_scale_step_down`, filtering redundant no-op requests, dry-run vs live authorization.
- **`test_hysteresis.py` (4 tests)**: Cooldown timers preventing rapid repeating actions, anti-flapping logic suppressing rapid direction flips, cooldown expiration.
- **`test_kubernetes_executor.py` (4 tests)**: Dry-run preview mode without cluster mutation, state verification after live scale patch, graceful handling of disconnected clusters.
- **`test_dashboard_api.py` (21 tests)**: Claude-style page routes (`/`, `/overview`, `/workloads`, `/telemetry`, `/policies`, `/decisions`, `/history`, `/system-health`), `/healthz` and `/readyz` probes, policy modification validation, simulation lifecycle, and error response states.

---

## 6. Launching the Framework and Services Locally

### 1. Launch Prometheus Daemon (Port 9090)
```powershell
& "monitoring\prometheus_bin\prometheus-3.15.1.windows-amd64\prometheus.exe" --config.file=monitoring/prometheus.yml --storage.tsdb.path=monitoring/data --web.listen-address="0.0.0.0:9090"
```
Verify Prometheus at **[http://localhost:9090/targets](http://localhost:9090/targets)** (shows both `prometheus` and `sample-web-app` UP).

### 2. Launch Sample Web Application (Port 8080)
```powershell
python app/app.py
```
Provides `/metrics` with real CPU, Memory, and HTTP traffic metrics scraped by Prometheus.

### 3. Launch the Claude-Style Web Dashboard (Port 5055)
```powershell
python -m dashboard.app
```
Open **[http://localhost:5055](http://localhost:5055)** in your browser to view the 7-page operator console:
- `/overview`: High-level system state, cluster metrics, and live PRAH decision cards.
- `/workloads`: Observed replica counts, pod readiness, and workload health.
- `/telemetry`: Live Prometheus queries, sample freshness, units, and active scrape targets table.
- `/policies`: Configured PRAH scaling rules with live threshold editing.
- `/decisions`: Detailed breakdown of latest arbitration, competing proposals, and guardrail validation.
- `/history`: Chronological audit log of all scaling evaluations and clamp reasons.
- `/system-health`: End-to-end component diagnostics for Python app, Prometheus, Scrape Targets, and Kubernetes.

---

## 7. Faculty Demonstration Script (Repeatable Step-by-Step)

The dashboard provides a dedicated **Interactive Demonstration Bar** with one-click test scenarios designed for faculty evaluation.

### Step 1: Baseline Workload & Nominal Equilibrium
- **Action**: Open [http://localhost:5000](http://localhost:5000). Click **Scenario 6: Nominal Workload (45%)**.
- **Observed Behavior**:
  - CPU is 45.0%, Memory is 50.0%. Both are within nominal boundaries [25% - 75%].
  - **PRAH Decision**: `HOLD`. Explanation: *"No policy thresholds breached. Workload operating within nominal parameters; holding current replicas."*
  - Replicas remain at 2.

### Step 2: High CPU Load & Standard Scale-Out
- **Action**: Click **Scenario 1: High CPU Load (85%)**.
- **Observed Behavior**:
  - Policy `CPU_HIGH_LOAD` (Threshold > 75%, Priority 80) breaches.
  - **PRAH Decision**: `SCALE_OUT (+1)`. Target replicas: `3`.
  - Guardrail checks: `3 <= max_replicas (10)`. Status: `Approved`.
  - Cooldown timer activates (60s remaining).

### Step 3: Cooldown & Hysteresis Suppression
- **Action**: Immediately click **Scenario 1** again or click **Trigger Evaluation Cycle**.
- **Observed Behavior**:
  - CPU is still 85%, but the cooldown timer is active.
  - **PRAH Decision**: `HOLD`.
  - Explanation: *"PRAH Cooldown Active: Policy 'High CPU Load Scale-Out' triggered SCALE_OUT, but cooldown is active (XX.Xs remaining). Action held."*
  - **Faculty Takeaway**: Demonstrates that the framework prevents oscillation and rapid flapping.

### Step 4: Equal-Priority Conflict Resolution (Tie-Breaking)
- **Action**: Click **Reset Cooldown**, then click **Scenario 3: Tie-Breaking Conflict**.
- **Observed Behavior**:
  - Telemetry sets CPU to 88% (triggers `SCALE_OUT`) and Memory to 20% (triggers `SCALE_IN`).
  - Both policies operate at competing directions.
  - **PRAH Arbitration**: Scale-Out takes precedence over Scale-In.
  - Explanation: *"Tie-breaking: Equal priority conflict between SCALE_OUT and SCALE_IN policies. SCALE_OUT chosen for service availability."*

### Step 5: Guardrail Boundary Enforcement
- **Action**: Click **Reset Cooldown**, then click **Scenario 4: Low CPU Load (15%)**.
- **Observed Behavior**:
  - Policy `CPU_LOW_LOAD` triggers `SCALE_IN (-1)`. Target drops towards 1.
  - If already at 1: Guardrail intervenes with `REJECTED`: *"Workload already at minimum replica boundary (1). Scale-in rejected."*

### Step 6: Safe Telemetry Degradation Fallback
- **Action**: Click **Scenario 5: Missing / Stale Telemetry**.
- **Observed Behavior**:
  - Metric status changes to `MISSING`.
  - Yellow warning banner appears: *"Metrics degraded: cpu_utilization_percent (MISSING). Safe fallback active."*
  - **PRAH Decision**: `HOLD`.
  - Explanation: *"PRAH Fallback Triggered: Telemetry safety check failed for cpu_utilization_percent (MISSING). Holding replica count to prevent unsafe scaling during telemetry degradation."*
  - **Faculty Takeaway**: Proves the framework never fabricates metric values or triggers erratic scaling during Prometheus network drops.

### Step 7: Live Cluster Mutation (Confirmation Step)
- **Action**: Click **Toggle Live Execution**.
- **Observed Behavior**:
  - Modal prompt appears asking for explicit confirmation: *"Are you sure you want to enable LIVE EXECUTION? This will allow the framework to directly modify Kubernetes Deployment replicas via the cluster API."*
  - Upon confirmation, mode pill switches from `DRY RUN (Preview)` to `LIVE EXECUTION`.

---

## 8. Minikube Cluster Deployment Guide

When Docker Desktop and Minikube are active on the host machine:

### 1. Start Minikube
```powershell
minikube start --cpus=2 --memory=4096 --driver=docker
```

### 2. Point Docker CLI to Minikube's Docker Daemon
```powershell
# Windows PowerShell:
& minikube -p minikube docker-env --shell powershell | Invoke-Expression

# Linux/macOS:
eval $(minikube docker-env)
```

### 3. Build Container Images Inside Minikube
```powershell
# Build sample web application image
docker build -t sample-web-app:latest ./app

# Build framework controller & dashboard image
docker build -t autoscaling-framework:latest -f app/Dockerfile .
```

### 4. Deploy Kubernetes Manifests
```powershell
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/controller-rbac.yaml
kubectl apply -f app/sample-app.yaml
kubectl apply -f k8s/controller-deployment.yaml
kubectl apply -f k8s/dashboard-deployment.yaml
```

### 5. Deploy Prometheus Monitoring Stack
```powershell
kubectl apply -f monitoring/prometheus-config.yaml
# Or install via helm:
# helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
# helm install prometheus prometheus-community/prometheus -n monitoring -f monitoring/prometheus-values.yaml
```

### 6. Access Services via Port-Forwarding
```powershell
# Access Sample App
kubectl port-forward -n autoscaling-demo svc/sample-web-app 8080:8080

# Access Dashboard
kubectl port-forward -n autoscaling-demo svc/autoscaling-dashboard 5000:5000
```

### 7. Trigger Live Workload via CPU Load Endpoint
```powershell
# Generates 15 seconds of CPU load on the sample app pods
curl http://localhost:8080/load?duration=15
```

### 8. Cleanup
```powershell
kubectl delete -f k8s/dashboard-deployment.yaml
kubectl delete -f k8s/controller-deployment.yaml
kubectl delete -f app/sample-app.yaml
kubectl delete -f k8s/controller-rbac.yaml
kubectl delete -f k8s/namespace.yaml
minikube stop
```

---

## 9. Diagnostic and Troubleshooting Guide

| Problem | Root Cause | Resolution |
| :--- | :--- | :--- |
| **`failed to connect to docker API`** | Docker Desktop is not started on the Windows host. | Launch Docker Desktop from the Start menu before running `minikube start`. |
| **`Telemetry status: MISSING`** | Prometheus cannot scrape pod metrics or Prometheus is offline. | Verify Prometheus is running via `http://localhost:9090/-/ready` and check pod scrape annotations in `sample-app.yaml`. |
| **`Live scaling shows: Not connected`** | No active Kubernetes cluster reachable via kubeconfig. | The framework automatically falls back to simulated/dry-run mode without crashing. Start Minikube to enable live cluster mutations. |
| **`HPA conflict detected`** | Native HorizontalPodAutoscaler exists in the namespace. | StrategyCoordinator prevents competing writes to the same replica field. Remove the native HPA (`kubectl delete hpa <name> -n autoscaling-demo`) to allow framework ownership. |

---

## 10. Current Status vs Deferred Milestone Scope

### Implemented in Milestone 1 (First 50% Scope)
- [x] Deterministic YAML policy engine with configurable thresholds, operators, and durations.
- [x] PRAH (Priority-based Rule Arbitration with Hysteresis) implementation.
- [x] Priority arbitration and explicit tie-breaking (scale-out takes precedence).
- [x] Hysteresis anti-flapping suppression and cooldown timers.
- [x] Operational guardrails (`min_replicas`, `max_replicas`, `max_scale_step` clamping).
- [x] Safe telemetry fallback for missing and stale metrics.
- [x] Real Prometheus HTTP client integration.
- [x] Sample containerized web application with `/metrics` and `/load` generator.
- [x] Polished dark-themed operator dashboard with real-time REST API back-end.
- [x] Structured JSON Lines decision and execution audit logger.
- [x] Kubernetes executor with scale subresource patching and state confirmation.
- [x] Full automated test suite (35 unit/safety tests, 100% pass rate).

### Deferred to Milestone 2 (Second 50% Scope)
- Extended empirical benchmarking comparing PRAH vs native HPA response times.
- Automated multi-node fault injection and cluster partition recovery.
- Integration with external metrics providers (KEDA / Custom Metrics API).
- Optional Vertical Pod Autoscaler (VPA) recommendation coordination.
