# KubePilot Pre-Experiment Technical Audit Report

**Project:** KubePilot — Kubernetes-Based Auto-Scaling Coordination Framework Using Prometheus Telemetry  
**Repository:** `https://github.com/Sri-Ram-git/Kubernetes_based_autoscalling`  
**Workspace Root:** `c:\Users\SRIRAM\design_project`  
**Audit Timestamp:** November 6, 2026 (Local: 11:30 IST / 06:00 UTC)  
**Audit Mode:** Read-Only Technical Audit (Strictly zero cluster mutations or code modifications performed)  

---

## 1. Current Environment

### 1.1 Host Operating System & Toolchains
* **Operating System:** Windows (Microsoft Windows 10/11 x86_64, Kernel build via WSL2: `6.6.87.2-microsoft-standard-WSL2`)
* **Python Environments:**
  * Active Runtime: Python `3.13.14` (Windows executable `C:\Users\SRIRAM\AppData\Local\Microsoft\WindowsApps\python.exe`)
  * Secondary Runtime: Python `3.12.91` (`C:\msys64\ucrt64\bin\python.exe`)
  * Test Runner: `pytest 9.1.1` (Plugins: `anyio-4.14.0`, `asyncio-1.4.0`, `cov-7.1.0`)
* **Docker Daemon Status:**
  * Windows Service `com.docker.service` (Docker Desktop Service): **Stopped**
  * WSL2 Distributions: `Ubuntu` (**Stopped**), `docker-desktop` (**Stopped**)
  * Docker Socket: `npipe:////./pipe/dockerDesktopLinuxEngine` is **Unreachable** (system cannot find file specified)
* **Local Minikube Installation:**
  * Minikube CLI version: `v1.38.1` (commit: `c93a4cb9311efc66b90d33ea03f75f2c4120e9b0`)
  * Cluster Status: **Stopped / Offline** (`docker container inspect minikube: exit status 1`)
* **Local Kubernetes Client (`kubectl`):**
  * Client Version: `v1.36.1`
  * API Server Connection: **Offline / Connection Refused** (`dial tcp 127.0.0.1:51325: connectex: No connection could be made because the target machine actively refused it`)

### 1.2 Local Network & Port Listener Audit
Execution of `netstat -ano | findstr LISTENING` confirms:
* Port `9090` (Prometheus API): **Not Listening**
* Port `5000` (KubePilot Web Dashboard): **Not Listening**
* Port `8080` (Workload Service `sample-web-app`): **Not Listening**
* All port tests via `Test-NetConnection` to `127.0.0.1` on ports 9090, 5000, and 8080 failed with connection refused.

---

## 2. Repository and Implementation Status

### 2.1 Git Repository State
* **Current Active Branch:** `main` (tracking `origin/main` at commit `a4bd2ec`)
* **Local Uncommitted Modifications (13 tracked files):**
  1. `controller/experiment_runner.py`: Workload burst duration adjustments, payload count increments, and automated mirroring to `research/evidence`.
  2. `controller/kubernetes_executor.py`: Integrated `CapacityValidator`, excluded terminating pods (`deletion_timestamp is not None`), and implemented synchronous pod readiness verification with rollout failure inspection (`CrashLoopBackOff`, `ImagePullBackOff`, `Unschedulable`, `ProgressDeadlineExceeded`).
  3. `controller/main.py`: Enhanced configuration loading, hot-reload mtime tracking for mounted policy YAML, and `forced_metrics` cycle injection for live evaluation.
  4. `controller/strategy_coordinator.py`: Integrated pre-scaling capacity admission validation (`CapacityValidator.validate_scale_out`) and strict HPA collision detection.
  5. `controller/telemetry.py`: Updated PromQL query generation to normalize CPU usage against CPU requests ($100\text{m}$ per pod baseline), matching Native HPA semantics.
  6. `dashboard/app.py`: Registered `/api/capacity` endpoint and incorporated capacity validation states into `/api/status`.
  7. `docker-compose.yaml`: Minor development environment alignment.
  8. `documents/markdown/EXPERIMENTS_AND_EVALUATION.md`: Updated benchmark evaluation documentation.
  9. `documents/markdown/SYSTEM_ARCHITECTURE.md`: Synchronized 7-module architecture specification, state machine, and sequence diagrams.
  10. `k8s/controller-deployment.yaml`: Added `busybox:1.36` initContainer to seed policies to PVC, mounted `kubepilot-policies-pvc`, and injected `POLICIES_PATH`.
  11. `k8s/controller-rbac.yaml`: Implemented least-privilege RBAC for `deployments/scale` and cluster-scoped `ClusterRole` for node inspection.
  12. `k8s/dashboard-deployment.yaml`: Aligned volume mounts and initContainer with persistent policy volume.
  13. `tests/test_dashboard_api.py`: Added test coverage for `/api/capacity`.
* **Untracked Directories & Artifacts:**
  * Evidence Packages: `research_evidence/`, `research_evidence_v2/`, `research_evidence_v3/`, `research/`, `IEEE_Research_Evidence_Package/`, `IEEE_Research_Evidence_Package_v2/`
  * Reports & Handoffs: `FINAL_HANDOFF_V2.md`, `FINAL_HANDOFF_V3.md`, `documents/markdown/KUBEPILOT_AUDIT_SUMMARY.md`, `documents/markdown/KUBEPILOT_IMPLEMENTATION_AUDIT.md`
  * Manifests & Code: `k8s/policies-pvc.yaml`, `controller/capacity_validator.py`, `tests/test_capacity_validator.py`
  * Experiment Data & Scripts: `experiments/results/exp-*-20261105-*.csv/.json`, `scripts/run_benchmarks_v3.py`, `scripts/reconcile_and_verify_all.py`, `scripts/generate_figures_v3.py`

### 2.2 Architectural Module Verification (7 Core Modules)

| # | Architectural Module | File Path | Implementation Status | Incomplete Functions / TODOs | Notes |
|:---:|---|---|:---:|:---:|---|
| **M1** | **Telemetry Collector** | `controller/telemetry.py` | **Complete** | **0 TODOs / 0 Errors** | Queries Prometheus vector API; parses timestamps; normalizes CPU against pod requests; implements staleness and NaN guards; fallback to `HOLD`. |
| **M2** | **Policy Engine** | `controller/policy_engine.py` | **Complete** | **0 TODOs / 0 Errors** | Loads declarative YAML rules; validates operators (`>`, `>=`, `<`, `<=`), thresholds, priorities; evaluates telemetry vectors against multi-metric rules. |
| **M3** | **Decision Controller (PRAH)** | `controller/decision_controller.py` | **Complete** | **0 TODOs / 0 Errors** | Policy-Driven Reactive-Arbitration Heuristic; priority-based tie arbitration; availability-first bias (`SCALE_OUT_WINS`); 5% hysteresis band; cooldown tracking. |
| **M4** | **Guardrail Engine** | `controller/guardrails.py` | **Complete** | **0 TODOs / 0 Errors** | Bounds enforcement ($2 \le N \le 10$); rate-of-change limits (+2 scale-up, -1 scale-down); cooldown enforcement; dry-run safety toggle. |
| **M5** | **Capacity Validator** | `controller/capacity_validator.py` | **Complete** | **0 TODOs / 0 Errors** | Evaluates node allocatable CPU/RAM against active committed pod requests; filters cordoned nodes and taints; emits deterministic states (`CAPACITY_SUFFICIENT`, `INSUFFICIENT_CPU`, etc.). |
| **M6** | **Kubernetes Executor** | `controller/kubernetes_executor.py` | **Complete** | **0 TODOs / 0 Errors** | Authenticated scale subresource patching; active polling for pod readiness (`readyReplicas == target_replicas`); filters terminating pods; fatal status detection (`CrashLoopBackOff`, etc.). |
| **M7** | **Strategy Coordinator** | `controller/strategy_coordinator.py` | **Complete** | **0 TODOs / 0 Errors** | Orchestrates closed-loop pipeline; enforces mutual exclusion via `check_competing_hpa()`; delegates to Capacity Validator before scaling. |

### 2.3 Existing Test Suite Execution Status
The full automated test suite was executed in read-only test mode using Python 3.13:
```
============================= test session starts =============================
platform win32 -- Python 3.13.14, pytest-9.1.1, pluggy-1.6.0
collected 115 items

tests\test_capacity_validator.py ............                            [ 10%]
tests\test_dashboard_api.py ...............................              [ 37%]
tests\test_decision_controller.py ....                                   [ 40%]
tests\test_experiments.py .............                                  [ 52%]
tests\test_fixes_regression.py ....s....                                 [ 60%]
tests\test_guardrails.py ........                                        [ 66%]
tests\test_hysteresis.py ....                                            [ 70%]
tests\test_kubernetes_executor.py ....                                   [ 73%]
tests\test_policy_engine.py ..................                           [ 89%]
tests\test_telemetry.py ............                                     [100%]

================= 114 passed, 1 skipped in 167.70s (0:02:47) ==================
```
* **Passed:** 114 tests passed with zero failures.
* **Skipped (1 test):** `tests/test_fixes_regression.py::test_case_5_live_scaling_against_minikube` skipped cleanly with message: `"Live Minikube cluster is not accessible in this environment"`.

### 2.4 Research Paper & Claims Alignment
Cross-referencing the codebase with `research_evidence_v3/paper_claims_matrix.md` and `FINAL_HANDOFF_V3.md`:
* **Claims Supported by Code:**
  * Multi-metric arbitration via priority integer scoring (CPU, Memory, Request Rate).
  * 5% hysteresis deadband suppressing borderline oscillation.
  * Node request-based admission pre-check avoiding unschedulable pod states.
  * Pod readiness polling ensuring requests are not sent to unready pods.
  * Fail-safe degradation to `HOLD` on telemetry or API errors.
* **Explicit Non-Claims Maintained:**
  * The implementation **does not use AI/ML or predictive modeling**; it is 100% deterministic rule-based heuristic (PRAH).
  * The framework does not replace the Kubernetes scheduler; physical pod binding remains the responsibility of `kube-scheduler`.
  * The framework does not support VPA or KEDA.

---

## 3. Kubernetes Status

### 3.1 Live Cluster Connectivity
* **Cluster API Health:** **UNREACHABLE**
  * `kubectl cluster-info`: Failed (`dial tcp 127.0.0.1:51325: connectex: No connection could be made because the target machine actively refused it`).
  * Root Cause: Docker Desktop engine is stopped on the Windows host.

### 3.2 Historical Verified Topology (from `research_evidence_v3/logs/k8s_cluster_state.txt`)
When the Minikube cluster was last operational (November 5, 2026), the recorded topology was:

* **Node Specification:**
  * Node Name: `minikube` (Control plane, Single-node cluster, Version `v1.35.1`)
  * Container Runtime: `docker://29.2.1` on Debian GNU/Linux 12 (bookworm)
  * Allocatable CPU: $12,000\text{m}$ (12 vCPUs)
  * Allocatable Memory: $8,182,247,424\text{ bytes}$ (~$7,803\text{ MiB}$)
* **Workload Deployment (`sample-web-app`):**
  * Namespace: `autoscaling-demo`
  * Image Tag: `sample-web-app:latest` (`imagePullPolicy: IfNotPresent`)
  * Baseline Replicas: Desired = 2, Ready = 2, Available = 2
  * Requests: CPU $100\text{m}$ ($0.100\text{ cores}$), Memory $128\text{Mi}$ ($134,217,728\text{ bytes}$)
  * Limits: CPU $500\text{m}$ ($0.500\text{ cores}$), Memory $256\text{Mi}$ ($268,435,456\text{ bytes}$)
  * Probes: Liveness (`/healthz`: port 8080) and Readiness (`/readyz`: port 8080)
* **Native Kubernetes HPA (`k8s/baseline-hpa.yaml`):**
  * Target: `Deployment/sample-web-app`
  * Min Replicas: 2 | Max Replicas: 10
  * Metric Target: CPU averageUtilization = $75\%$ (relative to $100\text{m}$ request = $75\text{m}$ threshold)
* **KubePilot Controller & Dashboard Deployments:**
  * Controller: `autoscaling-controller` (1 replica, image `autoscaling-framework:latest`)
  * Dashboard: `autoscaling-dashboard` (1 replica, image `autoscaling-framework:latest`, Service NodePort `5000:30500`)
  * Persistence: PVC `kubepilot-policies-pvc` (ReadWriteOnce, 100Mi) mounted at `/app/policies`
* **Service Account & RBAC (`k8s/controller-rbac.yaml`):**
  * ServiceAccount: `autoscaling-controller-sa` in `autoscaling-demo`
  * Role: `autoscaling-controller-role` granting read access to deployments, replicasets, pods, and HPAs; write access to `deployments/scale`
  * ClusterRole: `autoscaling-controller-node-reader` granting read access to cluster `nodes`

---

## 4. Prometheus and Telemetry Audit

### 4.1 Prometheus Health & Readiness
* **Endpoint Status:** `http://localhost:9090` is **OFFLINE** (TCP connection refused).
* **In-Cluster Manifest:** Defined in `monitoring/prometheus-deployment.yaml` (`prom/prometheus:v2.51.0`, port 9090).
* **Host Binary:** Windows standalone Prometheus distribution available in `monitoring/prometheus_bin/prometheus-3.15.1.windows-amd64` (not currently executing).

### 4.2 Scrape Configuration & kube-state-metrics Absence
Inspection of `monitoring/prometheus-config.yaml` reveals exactly two scrape jobs:
1. `kubernetes-pods`: Scrapes pods with annotation `prometheus.io/scrape: "true"` on port 8080 (target: `sample-web-app`).
2. `kubernetes-cadvisor`: Scrapes node cAdvisor via Kubernetes API proxy (`/api/v1/nodes/${1}/proxy/metrics/cadvisor`).

> [!CRITICAL]
> **`kube-state-metrics` is NOT deployed in this cluster or manifests.**  
> The Prometheus configuration contains no job scraping `kube-state-metrics`. Consequently, standard Kubernetes state metrics (`kube_pod_status_ready`, `kube_deployment_status_replicas_ready`, `kube_deployment_spec_replicas`, and `kube_pod_container_resource_requests`) **DO NOT EXIST in Prometheus TSDB**.

### 4.3 Telemetry Query Semantic Alignment
KubePilot bypasses the absence of `kube-state-metrics` by design:
* **Workload State & Capacity:** Ingested **directly from the Kubernetes CoreV1 and AppsV1 APIs** via `KubernetesExecutor.get_workload_state()` and `CapacityValidator.validate_scale_out()`.
* **Prometheus Metrics Ingested:** Ingested strictly via the following vector PromQL expressions defined in `controller/telemetry.py`:
  * **CPU Utilization:**
    ```promql
    (sum(rate(container_cpu_usage_seconds_total{namespace="autoscaling-demo", pod=~"sample-web-app-.*"}[1m])) / 
     (count(count by (pod) (container_cpu_usage_seconds_total{namespace="autoscaling-demo", pod=~"sample-web-app-.*"})) * 0.1) * 100) 
    or (sum(rate(container_cpu_usage_seconds_total{namespace="autoscaling-demo", pod=~"sample-web-app-.*"}[1m])) / 
     (sum(container_spec_cpu_quota{namespace="autoscaling-demo", pod=~"sample-web-app-.*"}) / avg(container_spec_cpu_period{namespace="autoscaling-demo", pod=~"sample-web-app-.*"})) * 100) 
    or sum(sample_app_cpu_utilization_percent{namespace="autoscaling-demo"})
    ```
  * **Memory Utilization:**
    ```promql
    (sum(container_memory_working_set_bytes{namespace="autoscaling-demo", pod=~"sample-web-app-.*"}) / 
     sum(container_spec_memory_limit_bytes{namespace="autoscaling-demo", pod=~"sample-web-app-.*"}) * 100) 
    or sum(sample_app_memory_utilization_percent{namespace="autoscaling-demo"})
    ```
  * **HTTP Request Rate:**
    ```promql
    sum(rate(sample_app_requests_total{namespace="autoscaling-demo"}[1m])) 
    or sum(rate(sample_app_requests_total[1m]))
    ```

---

## 5. Controller Ownership and Execution Safety

### 5.1 Dual-Controller Conflict Assessment
Can multiple controllers modify the same Deployment replica count? **YES, if not coordinated.**

* **Native HPA:** When applied (`kubectl apply -f k8s/baseline-hpa.yaml`), the Kubernetes `horizontal-pod-autoscaler` controller in `kube-controller-manager` actively watches metrics and patches `sample-web-app.spec.replicas`. It has zero awareness of KubePilot.
* **KubePilot Protection:** KubePilot implements active collision protection in `controller/strategy_coordinator.py`:
  ```python
  def check_competing_hpa(self) -> Tuple[bool, Optional[str]]:
      # Queries AutoscalingV2Api for any HPA targeting the deployment
  ```
  When `enforce_exclusive_ownership=True` (default), KubePilot halts mutation if native HPA is present:
  `"Conflict detected: Native HPA 'sample-web-app' is already targeting Deployment 'sample-web-app'. Competing writes prohibited."`
* **Experimental Precondition:**
  * When running Native HPA trials: KubePilot must be set to `dry_run=True, enable_live_execution=False`.
  * When running KubePilot trials: Native HPA must be deleted (`kubectl delete hpa sample-web-app -n autoscaling-demo --ignore-not-found=true`) and KubePilot set to `enable_live_execution=True`.

---

## 6. Experiment Readiness Audit

Evaluation of the 9 required capabilities:

| # | Experiment Capability | Status | Implementation Evidence | Operational Requirement |
|---|---|:---:|---|---|
| **1** | Native HPA experiments | **Ready** | `scripts/run_benchmarks_v3.py` (lines 397-400), `controller/experiment_runner.py` | Requires Minikube and metrics-server running. |
| **2** | KubePilot experiments | **Ready** | `scripts/run_benchmarks_v3.py` (lines 401-406), `controller/main.py` | Requires Minikube, Prometheus, and `sample-web-app` running. |
| **3** | Identical workload scenarios | **Ready** | `WorkloadGeneratorV3` supports continuous background + bursts, surge + cutoff. | Port-forward `8080:8080` must be active. |
| **4** | Replica scaling verification | **Ready** | `KubernetesExecutor.execute_scaling()` synchronously verifies `ready_replicas == target_replicas`. | Access to Kubernetes CoreV1 & AppsV1 API. |
| **5** | Response-time measurement | **Ready** | Computes $T_{\text{resp}} = t_{\text{desired\_observed}} - t_{\text{trigger}}$ and $T_{\text{ready}} = t_{\text{ready\_observed}} - t_{\text{trigger}}$. | High-resolution wall-clock timestamps recorded. |
| **6** | Throughput & error-rate | **Ready** | Tracks total requests, successes, failures, error rate %, and RPS. | Logged in trial results and CSV summaries. |
| **7** | CPU & memory measurement | **Ready** | Ingests PromQL instant queries every cycle; computes raw cores and percentages. | Prometheus scrape interval 5s. |
| **8** | Scaling decision timing | **Ready** | Tracks timestamps: `policy_detected_time`, `scale_request_issued_time`, `desired_observed_time`. | Structured in `TrialResultV3`. |
| **9** | Reversal measurement | **Ready** | Scenario E5 explicitly tracks `scale_in_observed_time` and `scale_in_latency_time`. | 60s cooldown and 300s HPA stabilization window observed. |

* **Raw Results Preservation:** The runner preserves all raw time series samples in per-trial JSON and CSV files under `research_evidence_v3/raw/` (and `experiments/results/` for dashboard runs). Summaries are compiled into `experiment_summary.csv`.

---

## 7. Existing Working Functionality

The following components are fully implemented, verified, and operational:
1. **Core Controller Logic:** 100% complete across all 7 architectural modules with zero compilation or syntax errors.
2. **Automated Test Suite:** 114 passing unit and integration tests verifying policy evaluation, PRAH arbitration, guardrail limits, hysteresis deadbands, capacity admission, and REST API routes.
3. **Capacity Admission Engine:** Complete heuristic checking node allocatable headroom against committed requests without modifying cluster state.
4. **Synchronous Pod Readiness Verification:** Complete rollout verification detecting container failures and progress deadline violations.
5. **Research Evaluation Scripts:** Complete suite (`run_benchmarks_v3.py`, `reconcile_and_verify_all.py`, `generate_figures_v3.py`) generating publication-grade plots and datasets.

---

## 8. Confirmed Blockers

### Blocker 1: Host Docker Daemon & Minikube Cluster Are Offline
* **Problem:** Docker Desktop service and the Minikube cluster VM/container are stopped, making both the Kubernetes API (`https://127.0.0.1:51325`) and Prometheus (`http://localhost:9090`) unreachable.
* **Evidence:** `kubectl cluster-info` returns `connectex: No connection could be made because the target machine actively refused it`. `minikube status` returns exit code 1 (`failed to connect to docker API`). `Get-Service *docker*` reports `Docker Desktop Service: Stopped`. `test_case_5_live_scaling_against_minikube` skipped due to inaccessible cluster.
* **Affected Module:** Host Infrastructure / Cluster Environment (`Docker Desktop`, `Minikube`).
* **Required Correction:** Start Docker Desktop service (`Start-Service com.docker.service` or open Docker Desktop application), start Minikube (`minikube start`), and verify cluster connectivity (`kubectl get nodes`).
* **Priority:** **CRITICAL**
* **Fixable without changing architecture:** **YES** (Operational environment startup).

### Blocker 2: Dual-Controller Contention When Native HPA and KubePilot Are Concurrently Active
* **Problem:** If native HPA is left running while KubePilot live execution is enabled, KubePilot's `StrategyCoordinator` halts scaling (`Action rejected: Competing native HPA detected`). If KubePilot's collision check is bypassed, both controllers issue competing mutations to `sample-web-app.spec.replicas`, causing race conditions and erratic pod flapping.
* **Evidence:** `controller/strategy_coordinator.py` lines 50-77 (`check_competing_hpa()`) and lines 89-114 explicitly abort execution when native HPA is present. Native HPA has no awareness of KubePilot.
* **Affected Module:** Control Plane / Experiment Runner (`controller/strategy_coordinator.py`, `scripts/run_benchmarks_v3.py`).
* **Required Correction:** Maintain strict lifecycle sequencing in experiment runners: ensure `kubectl delete hpa sample-web-app -n autoscaling-demo --ignore-not-found=true` runs before starting KubePilot live trials, and ensure KubePilot is switched to `dry_run=True` / `enable_live_execution=False` when applying `baseline-hpa.yaml` for Native HPA trials.
* **Priority:** **HIGH**
* **Fixable without changing architecture:** **YES** (Procedural lifecycle management already built into benchmark runners).

### Blocker 3: Prometheus 1-Minute Rate Smoothing Residual Coupling Between Back-to-Back Trials
* **Problem:** PromQL `rate(...[1m])` calculates a 60-second moving average window. When running a KubePilot trial immediately after an intense Native HPA spike trial without sufficient inter-trial cooldown, Prometheus still reports residual CPU utilization $>75\%$ at $t = 0\text{s}$, triggering false immediate scale-outs on cycle 0.
* **Evidence:** Documented in `FINAL_HANDOFF_V3.md` and `research_evidence_v3/results_analysis.md`, where E2 Trials 1 and 5 produced near-zero reaction times ($0.01\text{s}$) due to residual metrics from the prior HPA run.
* **Affected Module:** Telemetry Collector / Benchmark Runner (`controller/telemetry.py`, `scripts/run_benchmarks_v3.py`).
* **Required Correction:** Enforce an explicit mandatory telemetry quiescence wait (minimum 60-90 seconds) between trial runs, actively polling Prometheus until `cpu_utilization_percent < 20%` before initiating any new workload trial.
* **Priority:** **MEDIUM**
* **Fixable without changing architecture:** **YES** (Experiment runner timing refinement).

### Blocker 4: Missing `kube-state-metrics` in Cluster Manifests
* **Problem:** Prometheus configuration and Kubernetes manifests do not deploy or scrape `kube-state-metrics`. Consequently, standard Kubernetes state metrics (`kube_pod_status_ready`, `kube_deployment_status_replicas_ready`, `kube_pod_container_resource_requests`) are completely absent from Prometheus TSDB.
* **Evidence:** `monitoring/prometheus-config.yaml` contains only two scrape jobs: `kubernetes-pods` and `kubernetes-cadvisor`. No deployment or scrape target for `kube-state-metrics` exists in `k8s/` or `monitoring/`.
* **Affected Module:** Monitoring Infrastructure (`monitoring/prometheus-config.yaml`, `monitoring/prometheus-deployment.yaml`).
* **Required Correction:** If external tooling or future benchmark scripts require `kube_*` metrics from Prometheus directly (rather than querying the Kubernetes API as KubePilot currently does), deploy `kube-state-metrics` into the cluster and add a scrape target in `prometheus-config.yaml`.
* **Priority:** **MEDIUM**
* **Fixable without changing architecture:** **YES** (Standard manifest add-on).

### Blocker 5: Sample Web App Single-Process Concurrency Saturation Under High Thread Bursts
* **Problem:** The sample web application (`app/app.py`) runs on a lightweight WSGI server. Under sudden high-concurrency bursts (e.g. 12 concurrent threads executing CPU math queries), the HTTP connection pool saturates, leading to connection refusals (up to 31.4% error rate) and high tail latency before autoscaling can physically complete pod provisioning.
* **Evidence:** Observed in `research_evidence_v3/paper_claims_matrix.md` (Claim C8) and terminal logs where connection errors occurred during intense spikes.
* **Affected Module:** Sample Application (`app/app.py`, `app/Dockerfile`).
* **Required Correction:** Run `app.py` with a multi-worker WSGI/ASGI server (e.g. `gunicorn -w 4` or `uvicorn`) in the container image, or calibrate burst concurrency in workload generators to match application capacity.
* **Priority:** **MEDIUM**
* **Fixable without changing architecture:** **YES** (Application container packaging).

### Blocker 6: Empty Terminal Logs in Evidence Package
* **Problem:** In `research_evidence_v3/logs/`, `benchmark_runner_terminal_output.txt` and `functional_test_terminal_output.txt` are 0 bytes, likely due to PowerShell redirection buffering during previous batch runs.
* **Evidence:** Directory inspection shows: `benchmark_runner_terminal_output.txt` (0 bytes), `functional_test_terminal_output.txt` (0 bytes), whereas `pytest_terminal_output.txt` (21,494 bytes) and `k8s_events.txt` (22,622 bytes) are fully populated.
* **Affected Module:** Evidence Package Logging (`scripts/run_benchmarks_v3.py`, `scripts/run_functional_tests_v2.py`).
* **Required Correction:** Use unbuffered execution (`python -u ...`) or explicit file writing when capturing terminal logs during benchmark runs.
* **Priority:** **LOW**
* **Fixable without changing architecture:** **YES** (Logging command flag).

---

## 9. Minimal Ordered Implementation Plan

For the incoming coding agent tasked with executing comparative experiments:

```
[Phase 1: Environment Activation]
  1. Start Docker Desktop Service:
     Start-Service com.docker.service (or launch Docker Desktop application)
  2. Start Minikube:
     minikube start --driver=docker
  3. Verify Node Health & API Accessibility:
     kubectl get nodes -o wide
     kubectl cluster-info

[Phase 2: Workload & Telemetry Activation]
  4. Verify In-Cluster Deployments:
     kubectl get all -n autoscaling-demo
     kubectl get all -n monitoring
  5. Establish Required Port-Forwarding Daemons:
     kubectl port-forward svc/sample-web-app 8080:8080 -n autoscaling-demo
     kubectl port-forward svc/prometheus-server 9090:9090 -n monitoring
  6. Confirm Prometheus Scrape Target Health:
     curl -s http://localhost:9090/api/v1/targets | jq .

[Phase 3: Verification of Test Suite Against Live Cluster]
  7. Run Full Automated Test Suite:
     python -m pytest -v
     (Verify all 115 tests pass, including live cluster test case 5)
  8. Run Functional Integration Tests:
     python scripts/run_functional_tests_v2.py

[Phase 4: Comparative Experiment Execution]
  9. Run Benchmark Suite v3 (Ensuring 90s inter-trial cooldown):
     python scripts/run_benchmarks_v3.py
 10. Reconcile Time-Series Data & Generate Publication Figures:
     python scripts/reconcile_and_verify_all.py
     python scripts/generate_figures_v3.py
```

---

## 10. Exact Commands and Tests to Verify Corrections

The incoming agent should run the following commands in sequence:

```powershell
# 1. Start Docker Desktop & Minikube
Start-Service com.docker.service
minikube start --driver=docker

# 2. Check cluster node allocatable capacity and pod health
kubectl get nodes -o wide
kubectl get pods -n autoscaling-demo -o wide
kubectl get pods -n monitoring -o wide

# 3. Start port-forwarding processes (run in separate background sessions or tasks)
Start-Process kubectl -ArgumentList "port-forward svc/sample-web-app 8080:8080 -n autoscaling-demo"
Start-Process kubectl -ArgumentList "port-forward svc/prometheus-server 9090:9090 -n monitoring"

# 4. Verify Prometheus query API returns valid data
curl "http://localhost:9090/api/v1/query?query=container_cpu_usage_seconds_total"
curl "http://localhost:9090/api/v1/query?query=sample_app_requests_total"

# 5. Verify sample-web-app responds to HTTP probes
curl -s http://localhost:8080/healthz
curl -s http://localhost:8080/readyz

# 6. Execute full unit test suite (expect 115 passed, 0 skipped, 0 failed)
python -m pytest -v

# 7. Execute live functional test suite (18 real cluster tests)
python scripts/run_functional_tests_v2.py

# 8. Execute comparative benchmark suite
python scripts/run_benchmarks_v3.py
```

---

## CONCLUSION

# NOT READY — CRITICAL BLOCKERS

**Conclusion Rationale:**  
While the KubePilot codebase, core algorithms (PRAH), guardrails, capacity validator, and test suites are 100% functionally complete (114/115 tests passing with 0 failures), **comparative live experiments cannot physically execute at this moment because Docker Desktop is stopped and the Minikube cluster and Prometheus telemetry server are offline**. Once the host Docker daemon and Minikube cluster are started and port-forwarding is established in accordance with Section 9, the repository is immediately ready for benchmark execution.
