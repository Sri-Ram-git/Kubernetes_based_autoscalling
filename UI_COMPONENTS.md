# UI Components Specification
**Project 357: Kubernetes-Based Auto-Scaling Framework**  
**Alliance University, Bengaluru &bull; Design Project-I**

This document catalogues every user-interface component implemented in the operator dashboard (`dashboard/templates/index.html`, `dashboard/static/js/dashboard.js`, `dashboard/static/css/style.css`), detailing its location, source of truth, data type, refresh behavior, user interactions, and relationship to the PRAH auto-scaling workflow.

---

## 1. Header & System Status Bar

### 1.1 Brand Logo & Project Title
- **Location:** Top left of the navigation header (`.app-header`).
- **Purpose:** Identifies the project, institution, and underlying algorithm (**PRAH**).
- **Source:** Static HTML / CSS in `index.html`.
- **Data Type:** Static content.
- **User Interactions:** None.
- **Workflow Role:** Contextual identity for faculty review.

### 1.2 Kubernetes Connectivity Status Pill (`#badge-k8s`)
- **Location:** Header center-right (`#badge-k8s`).
- **Purpose:** Informs operator whether the controller has an active, authenticated connection to the Kubernetes API server.
- **Source Files:** `index.html` line 23, `dashboard.js` lines 68-80.
- **Backend Endpoint:** `GET /api/status` &rarr; `connectivity.kubernetes.connected`.
- **Data Type:** Live runtime state.
- **Refresh Behavior:** Polled every 3 seconds via `fetchAllData()`.
- **Visual States:**
  - `Connected` (Green pill, `.pill-success`): Kubernetes API reachable.
  - `Offline` (Red pill, `.pill-danger`): Kubernetes cluster or kubeconfig unreachable.
- **Error Handling:** Handled gracefully; defaults to `Offline` without UI crashes.

### 1.3 Prometheus Telemetry Connectivity Status Pill (`#badge-prom`)
- **Location:** Header center-right (`#badge-prom`).
- **Purpose:** Displays connectivity to Prometheus `/api/v1/query` and `/-/ready`.
- **Source Files:** `index.html` line 26, `dashboard.js` lines 82-94.
- **Backend Endpoint:** `GET /api/status` &rarr; `connectivity.prometheus.connected`.
- **Data Type:** Live runtime state.
- **Refresh Behavior:** Polled every 3 seconds.
- **Visual States:**
  - `Connected` (Green pill, `.pill-success`): Prometheus HTTP reachable.
  - `Offline` (Red pill, `.pill-danger`): Prometheus down or unreachable.

### 1.4 Operational Safety Mode Pill (`#badge-mode`)
- **Location:** Header center-right (`#badge-mode`).
- **Purpose:** Clearly displays whether cluster mutations are permitted (`LIVE EXECUTION`) or simulated in preview (`DRY RUN`).
- **Source Files:** `index.html` line 29, `dashboard.js` lines 96-110.
- **Backend Endpoint:** `GET /api/status` &rarr; `enable_live_execution` and `dry_run`.
- **Data Type:** Configuration / runtime state.
- **Refresh Behavior:** Polled every 3 seconds; updates immediately upon mode toggle.
- **Visual States:**
  - `DRY RUN (Preview)` (Purple pill, `.pill-dry-run`): Live mutations prevented.
  - `LIVE EXECUTION` (Amber pill, `.pill-live`): Cluster mutation authorized.

### 1.5 Refresh Indicator & Manual Refresh Button (`#btn-manual-refresh`)
- **Location:** Header far-right (`.refresh-indicator`).
- **Purpose:** Displays last successful data sync timestamp and provides instant manual polling.
- **Source Files:** `index.html` line 33, `dashboard.js` lines 42-47.
- **Data Type:** Local client timestamp.
- **User Interactions:** Click button &rarr; triggers `triggerManualRefresh()`, adding a spinning animation while requests complete.

---

## 2. Global Status & Quarantine Banners

### 2.1 Simulation Active Banner (`#global-mode-banner`)
- **Location:** Directly below the navigation header.
- **Purpose:** Guarantees truth in demonstration: prevents simulated metrics from ever being mistaken for real cluster telemetry.
- **Source Files:** `index.html` lines 38-42, `dashboard.js` lines 112-121.
- **Backend Endpoint:** `GET /api/status` &rarr; `simulation_mode`.
- **Data Type:** Runtime mode flag.
- **Visual States:**
  - Hidden (`.hidden`) when in live Prometheus mode.
  - Visible (Pink bar, `.banner-sim`) when simulation mode is active.
- **User Interactions:** "Return to Live Mode" button invokes `POST /api/controls/clear-simulation`.

---

## 3. Workload State Card (`.workload-card`)

### 3.1 Replica Counters Meter (`.replicas-meter`)
- **Location:** Workload State Card top half.
- **Purpose:** Displays target deployment replica status.
- **Source Files:** `index.html` lines 50-70, `dashboard.js` lines 123-128.
- **Backend Endpoint:** `GET /api/status` &rarr; `target.desired_replicas`, `target.current_replicas`, `target.ready_replicas`.
- **Data Type:** Live Kubernetes Deployment state.
- **Sub-elements:**
  - `Desired Replicas`: `spec.replicas` requested on Deployment.
  - `Current Replicas`: `status.replicas` observed by Kubernetes.
  - `Ready Pods`: `status.ready_replicas` passing liveness & readiness probes.
  - `Unavailable Pods`: `status.unavailable_replicas` pending or crashing.

### 3.2 Pod Instance Readiness Table (`#pod-table`)
- **Location:** Workload State Card bottom half (`.pod-readiness-panel`).
- **Purpose:** Displays live individual pod instances for `sample-web-app` with phase and restart counts.
- **Source Files:** `index.html` lines 72-96, `dashboard.js` lines 130-153.
- **Backend Endpoint:** `GET /api/status` &rarr; `target.pods`.
- **Data Type:** Live Kubernetes CoreV1 Pod list.
- **Refresh Behavior:** Polled every 3 seconds.
- **Empty State:** Honest label: `"No live pods detected (Cluster connection pending)"`.

---

## 4. Application Telemetry Card (`.telemetry-card`)

### 4.1 Telemetry Metric Boxes (`#box-cpu`, `#box-mem`, `#box-rps`)
- **Location:** Telemetry Card grid.
- **Purpose:** Visualizes real-time metrics with threshold markers and status badges.
- **Source Files:** `index.html` lines 105-155, `dashboard.js` lines 156-224.
- **Backend Endpoint:** `GET /api/metrics`.
- **Data Type:** Real Prometheus query result, or labeled `SIMULATED` sample.
- **Meters:**
  - **CPU Utilization (%)**: Gauge, meter fill, low/high/critical markers.
  - **Memory Utilization (%)**: Gauge, meter fill, low/high markers.
  - **Request Rate (req/s)**: Counter rate meter, surge threshold marker.
- **Honest Error Handling:** If Prometheus is offline and simulation is off, displays `"Unavailable"` in bold without inventing numbers.

### 4.2 Telemetry Degradation Warning Banner (`#telemetry-warning`)
- **Location:** Telemetry Card bottom.
- **Purpose:** Alerts operator when any metric is `MISSING`, `STALE` (>60s), or `ERROR`.
- **Source Files:** `index.html` lines 156-158, `dashboard.js` lines 180-192.
- **Workflow Role:** Explains why PRAH enters safe fallback `HOLD` mode.

---

## 5. PRAH Scaling Decision Engine Card (`.prah-card`)

### 5.1 Action & Cooldown Header Badges
- **Location:** Decision Card header right.
- **Sub-elements:**
  - `#decision-action-badge`: Large action tag (`SCALE_OUT` in blue, `SCALE_IN` in amber, `HOLD` in gray).
  - `#cooldown-indicator`: Real-time countdown timer showing remaining seconds or `Cooldown: Inactive`.

### 5.2 Deterministic Decision Summary
- **Location:** Left column of PRAH Card.
- **Displays:**
  - Selected Policy Name & ID.
  - Arbitration Priority integer.
  - Replica Delta (`+1`, `+2`, `-1`, `0`).
  - Target Replicas computed.
  - Guardrail verification outcome (Approved / Clamped / Rejected).
  - **PRAH Deterministic Rationale**: Plain English explanation generated by the engine.

### 5.3 Competing Proposals Arbitration Table (`#proposals-table`)
- **Location:** Right column of PRAH Card.
- **Purpose:** Displays all rules that evaluated to True in the cycle, illustrating priority arbitration and tie-breaking.
- **Columns:** Priority, Policy Name, Action, Delta, Observed Metric, Threshold, Condition Reason.

---

## 6. Scaling Policy Configuration Card (`.policies-card`)

### 6.1 Policy Rules Table (`#policies-table`)
- **Location:** Left of Row 3.
- **Purpose:** Read-only presentation of active rules loaded from `policies/scaling-policies.yaml`.
- **Source Files:** `index.html` lines 246-276, `dashboard.js` lines 275-306.
- **Backend Endpoint:** `GET /api/policies`.
- **Data Type:** YAML configuration-driven.

---

## 7. Operational Safety Controls (`.controls-card`)

### 7.1 Primary Control Buttons
- **`Trigger Evaluation Cycle`**: Calls `POST /api/evaluate` to execute an on-demand cycle.
- **`Toggle Live Execution`**: Opens confirmation modal (`#modal-confirm`) before toggling cluster mutation permissions.
- **`Reset Cooldown`**: Calls `POST /api/controls/reset-cooldown` to reset timers for demo testing.

### 7.2 Quarantined Simulation Test Harness (`.simulation-quarantine`)
- **Location:** Isolated box inside Controls Card with pink border and `ISOLATED DEMO ENVIRONMENT` tag.
- **Purpose:** Provides one-click scenarios for faculty demonstration:
  - Scenario 1: High CPU (85%) &rarr; Scale-Out (+1)
  - Scenario 2: Critical Spike (95%) &rarr; Urgent Scale-Out (+2)
  - Scenario 3: Tie-Breaking Conflict (Scale-Out vs Scale-In)
  - Scenario 4: Low CPU (15%) &rarr; Scale-In (-1)
  - Scenario 5: Missing Telemetry &rarr; Safe Fallback HOLD
  - Scenario 6: Nominal Workload (45%) &rarr; Nominal HOLD

---

## 8. Decision & Execution Audit History Card (`.history-card`)

### 8.1 Audit History Table (`#history-table`)
- **Location:** Bottom row (`full-width`).
- **Purpose:** Permanent, transparent record of all scaling decisions and execution results.
- **Source Files:** `index.html` lines 309-341, `dashboard.js` lines 308-348.
- **Backend Endpoint:** `GET /api/history?limit=30`.
- **Data Source:** In-memory ring buffer fed by `logs/decisions.jsonl`.
- **Columns:** Timestamp (UTC), Action, Replicas (Initial &rarr; Target), Operational Mode (DRY RUN / LIVE), Policy, Guardrail, Execution Outcome, Deterministic Rationale.
