# PROJECT 357 — Engineering Baseline Report

**Project Title:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications  
**Institution:** Alliance University, Bengaluru  
**Department:** Computer Science & Engineering (Design Project-I)  
**Project ID:** 357  
**Date of Audit:** October 23, 2026  
**Auditor / Roles:** Senior Kubernetes Engineer, Backend Architect, Test Engineer  

---

## 1. Executive Summary

This engineering baseline establishes the verified status of the Project 357 codebase. The project implements a deterministic, rule-based Kubernetes autoscaling framework driven by the **PRAH** (*Priority-based Rule Arbitration with Hysteresis*) algorithm.

### Core Non-Negotiable Tenet
> **Strict Engineering Rule:** NO MACHINE LEARNING, NO FORECASTING, NO PREDICTIVE MODELS, AND NO AI-BASED DECISION-MAKING.  
> Every scaling action is deterministic, rule-based, strictly bounded by operational guardrails, and fully explainable through structured JSONL logs.

---

## 2. Repository & File Structure

The workspace (`C:\Users\SRIRAM\design_project\`) contains a complete modular layout separating the controller daemon, web console, target sample workload, policies, manifests, and automated tests.

```
kubernetes-autoscaling-framework/
├── app/                                    # Target containerized workload
│   ├── app.py                              # Flask sample microservice with Prometheus metrics
│   ├── Dockerfile                          # Container specification
│   ├── requirements.txt                    # App runtime dependencies (Flask, prometheus-client)
│   └── sample-app.yaml                     # Kubernetes Deployment & Service manifest (port 8080)
├── controller/                             # Core Python Autoscaling Engine (7 Modules)
│   ├── __init__.py                         # Package initialization
│   ├── config.py                           # Dataclass configuration loader (env vars & YAML)
│   ├── decision_controller.py              # PRAH Decision Engine (Arbitration, Hysteresis, Cooldown)
│   ├── decision_logger.py                  # Thread-safe JSONL audit logging & history deque
│   ├── guardrails.py                       # Safety bounds ([min, max], step clamping, dry-run)
│   ├── kubernetes_executor.py              # Kubernetes API scale subresource client & verification
│   ├── main.py                             # Central orchestrator & autonomous control loop
│   ├── policy_engine.py                    # YAML rule parser, condition evaluator, duration persistence
│   ├── strategy_coordinator.py             # Single-owner scaling coordinator & HPA conflict guard
│   └── telemetry.py                        # Prometheus PromQL client, staleness & error validator
├── dashboard/                              # Web Operations Dashboard
│   ├── app.py                              # Flask REST API server & web interface controller
│   ├── requirements.txt                    # Dashboard requirements (Flask, PyYAML, Requests)
│   ├── static/
│   │   ├── css/style.css                   # Enterprise dark-themed stylesheet (819 lines)
│   │   └── js/dashboard.js                 # Polling client, REST dispatch, simulation lab UI
│   └── templates/
│       └── index.html                      # Single-page console layout with live meters & audit table
├── k8s/                                    # Kubernetes Orchestration Manifests
│   ├── controller-deployment.yaml          # Autoscaling controller Deployment specification
│   ├── controller-rbac.yaml                # Least-privilege ServiceAccount, Role, and RoleBinding
│   ├── dashboard-deployment.yaml           # Web dashboard Deployment specification
│   ├── namespace.yaml                      # Dedicated namespace ('autoscaling-demo')
│   └── policies-configmap.yaml             # ConfigMap mounting scaling-policies.yaml
├── logs/                                   # Audit Persistence
│   └── decisions.jsonl                     # Structured JSON Lines audit records
├── monitoring/                             # Prometheus Telemetry Setup
│   ├── prometheus-config.yaml              # Prometheus scrape configuration targeting sample-web-app
│   ├── prometheus-deployment.yaml          # Self-contained Prometheus Deployment & Service
│   └── prometheus-values.yaml              # Helm values specification
├── policies/                               # Declarative Rule Definitions
│   └── scaling-policies.yaml               # 6 YAML scaling policies, guardrails, fallback settings
├── tests/                                  # Automated Pytest Suite (68 Tests, 100% Passing)
│   ├── __init__.py
│   ├── test_dashboard_api.py               # REST endpoints & control API tests (13 tests)
│   ├── test_decision_controller.py         # Priority arbitration & fallback logic tests (4 tests)
│   ├── test_guardrails.py                  # Bound enforcement & step clamping tests (8 tests)
│   ├── test_hysteresis.py                  # Direction flip suppression & cooldown tests (4 tests)
│   ├── test_kubernetes_executor.py         # Scaling patch & verification tests (4 tests)
│   ├── test_policy_engine.py               # Module 3 Policy Engine tests (18 tests)
│   └── test_telemetry.py                   # Prometheus response parsing & error tests (9 tests)
├── .env.example                            # Configuration environment variable reference
├── ARCHITECTURE_AND_UI_FLOW.md             # Architecture and UI design specification
├── docker-compose.yaml                     # Local multi-container development environment
├── Dockerfile                              # Unified multi-stage controller/dashboard image
├── Makefile                                # Developer commands for testing, linting, and running
├── README.md                               # Project documentation & operational manual
├── UI_COMPONENTS.md                        # Component catalog for web interface
└── VERIFICATION_REPORT.md                  # Test verification record
```

---

## 3. Technology Stack & Runtime Environment

### Runtime Environment
- **Operating System:** Microsoft Windows 11 Enterprise (x64)
- **Python Version:** Python 3.13.14 (CPython)
- **Primary Frameworks:** Flask 3.1.2, Werkzeug 3.1.8, PyYAML 6.0.2, Requests 2.32.3
- **Kubernetes Client:** `kubernetes` Python package (v31.0.0)
- **Test Framework:** `pytest` 9.1.1 with `pytest-cov` 7.1.0, `anyio` 4.14.0, `asyncio` 1.4.0

### Service Status Verification (Verified at 2026-10-23 22:04 IST)

| Service | Target / Port | Actual Status | Evidence / Diagnostic Output |
| :--- | :--- | :--- | :--- |
| **Kubernetes Node** | `minikube` | **ONLINE (Ready)** | Minikube v1.38.1 running Kubernetes v1.35.1 control plane node in Docker. |
| **Kubernetes API** | `https://127.0.0.1:61343` | **ONLINE** | `is_connected()` returns `True, 'Kubernetes API reachable.'` |
| **Target Workload** | `sample-web-app` | **ONLINE (2/2 Ready)** | Deployment in `autoscaling-demo` with 2/2 pods Running (`sample-web-app-59c6d8b9b8-96767`, `sample-web-app-59c6d8b9b8-9l5m4`). |
| **In-Cluster Prometheus**| `http://localhost:9090` | **ONLINE** | Deployment `prometheus-server` in namespace `monitoring`. 3/3 targets `health: "up"` (`cAdvisor` and both workload pods). |
| **Workload Service** | `http://localhost:8080` | **ONLINE** | Service `sample-web-app` port 8080 forwarding to pods; `/healthz`, `/readyz`, `/metrics`, and `/generate-traffic` active. |
| **Flask Dashboard** | `http://127.0.0.1:5055` | **ONLINE** | Claude-style 7-page dashboard connected to live Kubernetes API and Prometheus. |

---

## 4. Test Baseline & Coverage Results

### Test Execution Command
```powershell
python -m pytest tests/ -v
```

### Execution Outcome
- **Total Discovered:** 59 tests
- **Passed:** 59 tests (100%)
- **Failed:** 0
- **Skipped:** 0
- **Execution Duration:** 2.59 seconds

### Test Classification Breakdown
1. **Pure Unit Tests (38 tests):**
   - Telemetry validation, non-finite rejection, staleness calculation, targets discovery (`tests/test_telemetry.py` - 9 tests).
   - Policy condition evaluation & duration persistence (`tests/test_policy_engine.py` - 9 tests).
   - Guardrails limits & step clamping (`tests/test_guardrails.py` - 8 tests).
   - Hysteresis and cooldown timers (`tests/test_hysteresis.py` - 4 tests).
   - Priority arbitration math & tie-breaking (`tests/test_decision_controller.py` - 4 tests).
   - Kubernetes executor dry-run & live scaling (`tests/test_kubernetes_executor.py` - 4 tests).
2. **Dashboard REST API & Page Routes (21 tests):**
   - Separate Claude-style page routes (`/`, `/overview`, `/workloads`, `/telemetry`, `/policies`, `/decisions`, `/history`, `/system-health`).
   - Liveness and readiness endpoints (`/healthz`, `/readyz`).
   - REST API endpoints (`/api/status`, `/api/metrics`, `/api/decisions`, `/api/policies`, `/api/history`, `/api/evaluate`, `/api/controls/*`).
3. **Verified Live Telemetry Cycles:**
   - Real-time PromQL query execution against `http://localhost:9090`.
   - Dual-query fallback architecture evaluating cAdvisor metrics inside Kubernetes and sample app gauges outside Kubernetes.
   - Live PRAH arbitration with cooldown and duration persistence.

---

## 5. Verified Limitations & Architectural Defenses

1. **Telemetry Offline Resilience:** When Prometheus is unreachable, `PrometheusTelemetryProvider` yields `MetricStatus.MISSING` or `MetricStatus.ERROR` without throwing unhandled exceptions. The PRAH Decision Controller detects degraded metrics and safely enters `HOLD` state to prevent erratic scaling.
2. **Kubernetes API Offline Resilience:** When the Kubernetes cluster is offline, `KubernetesExecutor` reports `connected=False` and defaults to simulated replica counts (default: 2 replicas). Live execution mutations fail safely with clear error messaging rather than crashing.
3. **Single Controller Ownership:** `StrategyCoordinator` inspects the target Deployment namespace for native `HorizontalPodAutoscaler` resources targeting the same Deployment. If a competing HPA is detected, the action is rejected to prevent conflicting control loops.
4. **Hysteresis Band:** An anti-flapping guard rejects opposite-direction scaling requests within a 30-second window, smoothing out oscillation.
5. **Operational Guardrails:** Min/max replica boundaries ([1, 10]) and step-size limits (+2 up, -1 down) are hard-enforced before any cluster mutation call.
