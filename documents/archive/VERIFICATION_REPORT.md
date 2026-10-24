# Verification and Review-Readiness Report
**Project 357: Kubernetes-Based Auto-Scaling Framework**  
**Alliance University, Bengaluru &bull; Design Project-I**  
**Algorithm:** **PRAH** (*Priority-based Rule Arbitration with Hysteresis*)  
**Execution Date:** 2026-10-23

---

## 1. Commands Actually Executed

The following commands were directly executed in the workspace:

| Command | Working Directory | Exit Code | Purpose / Outcome |
| :--- | :--- | :--- | :--- |
| `python --version; docker --version; kubectl version --client; minikube version` | `C:\Users\SRIRAM\design_project` | `0` | Verified runtime tools: Python 3.13.14, Docker 29.4.3, kubectl v1.36.1, minikube v1.38.1. |
| `python -m pip install kubernetes` | `C:\Users\SRIRAM\design_project` | `0` | Installed official Kubernetes Python Client (`v37.0.1`). |
| `python controller/main.py --once --simulate` | `C:\Users\SRIRAM\design_project` | `0` | Verified single autonomous PRAH cycle execution and structured JSON logging. |
| `python -m pytest tests/ -v` | `C:\Users\SRIRAM\design_project` | `0` | Executed complete automated test suite (48 tests passed, 0 failures). |
| `python -m dashboard.app` | `C:\Users\SRIRAM\design_project` | `0` (daemon) | Verified Flask REST API server and web dashboard operational on port 5000. |
| `curl http://127.0.0.1:5000/api/status` | `C:\Users\SRIRAM\design_project` | `0` | Verified `/api/status` returns operational state, cluster connectivity, and guardrail limits. |
| `curl http://127.0.0.1:5000/healthz` | `C:\Users\SRIRAM\design_project` | `0` | Verified liveness probe endpoint returns HTTP 200 `{"status": "healthy"}`. |
| `curl http://127.0.0.1:5000/readyz` | `C:\Users\SRIRAM\design_project` | `0` | Verified readiness probe returns HTTP 200 `{"status": "ready", "policies_count": 6}`. |
| `Get-Service *docker*` | `C:\Users\SRIRAM\design_project` | `0` | Checked Docker daemon status on Windows host (`com.docker.service` is Stopped). |
| `minikube status` | `C:\Users\SRIRAM\design_project` | `1` | Verified Minikube status (blocked by inactive Docker Desktop daemon). |

---

## 2. Automated Test Totals and Results

The automated test suite in `tests/` contains **48 independent unit and integration tests**:

- **Total Tests Collected:** 48
- **Passed:** 48 (100%)
- **Failed:** 0
- **Execution Duration:** 34.90 seconds

### Detailed Breakdown by Test Module:
1. **`test_policy_engine.py` (9 tests - PASSED)**:
   - Valid YAML policy schema parsing.
   - Missing fields and invalid schema handling.
   - Unsupported comparison operators detection.
   - Invalid action strings rejection.
   - Negative delta on `SCALE_OUT` rejection.
   - Positive delta on `SCALE_IN` rejection.
   - Scale-out condition evaluation with persistence window verification.
   - Scale-in condition evaluation.
   - Normal threshold nominal HOLD behavior.
2. **`test_decision_controller.py` (4 tests - PASSED)**:
   - Priority arbitration selecting highest priority rule.
   - Equal-priority conflict resolution (PRAH tie-breaking: Scale-Out wins for availability).
   - Missing telemetry safe fallback to `HOLD`.
   - Stale telemetry safe fallback to `HOLD`.
3. **`test_guardrails.py` (8 tests - PASSED)**:
   - Bound initialization validation (`min_replicas >= 1`, `max >= min`).
   - Minimum boundary rejection (scale-in rejected when at minimum).
   - Minimum boundary clamping (clamped to minimum).
   - Maximum boundary rejection (scale-out rejected when at ceiling).
   - Maximum boundary clamping (clamped to maximum).
   - Step-size up clamping (`+4` clamped to `max_scale_step_up: 2`).
   - Step-size down clamping (`-3` clamped to `max_scale_step_down: 1`).
   - Redundant duplicate action filtering.
   - Dry-run vs Live execution mode gating.
4. **`test_hysteresis.py` (4 tests - PASSED)**:
   - Cooldown timer blocking subsequent scaling.
   - Cooldown timer expiration permitting subsequent scaling.
   - Anti-flapping hysteresis suppressing rapid direction reversals.
   - Reset cooldown method validation.
5. **`test_telemetry.py` (6 tests - PASSED)**:
   - Valid Prometheus instant vector response parsing.
   - Stale telemetry detection (> 60s threshold).
   - Empty Prometheus result handling (`MISSING` status).
   - HTTP 500 error resilience.
   - Connection timeout resilience.
   - Explicit labeling of simulated telemetry providers.
6. **`test_kubernetes_executor.py` (4 tests - PASSED)**:
   - Dry-run preview execution without modifying cluster state.
   - Redundant no-op scaling when target matches current replicas.
   - Live scaling safe failure handling when cluster is disconnected.
   - Live scaling patch and API state confirmation verification.
7. **`test_dashboard_api.py` (13 tests - PASSED)**:
   - Index HTML route rendering.
   - `/healthz` liveness probe.
   - `/readyz` readiness probe.
   - `/api/status` schema and fields.
   - `/api/metrics` telemetry format.
   - `/api/decisions` latest decision state.
   - `/api/policies` active policy retrieval.
   - `/api/history` structured audit log retrieval.
   - `/api/evaluate` on-demand cycle execution.
   - `/api/controls/live-execution` mode toggling.
   - `/api/controls/simulate-metric` & `/api/controls/clear-simulation` lifecycle.
   - `/api/controls/reset-cooldown` timer reset.
   - `/api/policies/update-threshold` validation (missing, non-numeric, 404).

---

## 3. Cluster and Workload Verification

- **Current Context:** `minikube` (configured in `~/.kube/config`).
- **Cluster Reachability:** The local Minikube cluster was previously initialized on port 53336, but is currently offline because the host **Docker Desktop Service (`com.docker.service`)** is not started.
- **Fail-Safe Controller Behavior:** 
  - The controller handles offline cluster states gracefully.
  - When disconnected, `KubernetesExecutor.is_connected()` returns `False` without blocking or throwing unhandled exceptions.
  - The web dashboard honestly marks Kubernetes as **`Offline`** and displays simulated replica states with clear source indicators, strictly honoring the requirement to avoid fake status.

---

## 4. Telemetry Verification

- **Prometheus Scrape Endpoint:** Configured to `http://localhost:9090` (or `http://prometheus-server.monitoring.svc.cluster.local:9090` in-cluster).
- **Offline Resilience:** When Prometheus is offline, `telemetry.py` marks all metrics as `MISSING` or `ERROR`.
- **Safe Fallback Verification:** When telemetry is missing or stale, the PRAH Decision Controller successfully triggers safe fallback:
  ```json
  {
    "action": "HOLD",
    "selected_policy_id": "FALLBACK_TELEMETRY_INVALID",
    "explanation": "PRAH Fallback Triggered: Telemetry safety check failed for cpu_utilization_percent (MISSING). Holding replica count to prevent unsafe scaling during telemetry degradation."
  }
  ```
- **Simulated Test Harness:** Verified that simulated metrics injected via the dashboard are explicitly labeled `SIMULATED` across the UI, API, and audit logs.

---

## 5. Controller and Dashboard Health

- **Liveness Endpoint (`GET /healthz`):** Verified HTTP 200 `{"status": "healthy", "service": "autoscaling-dashboard"}`.
- **Readiness Endpoint (`GET /readyz`):** Verified HTTP 200 `{"status": "ready", "policies_count": 6}`.
- **Audit Logging:** Verified thread-safe atomic appending to `logs/decisions.jsonl` and in-memory ring buffer retrieval.

---

## 6. Live Scaling Outcome

- **Dry-Run Preview Scaling:** **Verified & Functional.** Correctly calculates delta (+1, +2, -1), enforces guardrails, simulates new replica count, and records structured audit trail.
- **Live In-Cluster Scaling:** Implemented in `kubernetes_executor.py` via `patch_namespaced_deployment_scale()` and confirmed with unit tests mocking the Kubernetes API. Live mutation against an active Minikube node is blocked on this host machine by the inactive Docker Desktop daemon.

---

## 7. Remaining Issues & Blockers for Faculty Review

1. **Host Blocker (Docker Desktop):**
   - **Root Cause:** Windows service `com.docker.service` is stopped. Starting it via PowerShell requires elevated administrator privileges.
   - **User Action Required:** Launch Docker Desktop from the Windows Start menu. Once the whale icon appears steady in the system tray, run `minikube start --driver=docker`.
2. **Review Readiness Without Docker:**
   - The framework is **100% review-ready** in local mode.
   - The dashboard, API, decision engine, safety guardrails, audit logging, and all 48 automated tests can be demonstrated live on `http://localhost:5000` with zero cloud or Docker dependencies.
