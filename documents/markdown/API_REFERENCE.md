# API Reference: KubePilot REST APIs

## 1. Overview & Base URL

KubePilot exposes a comprehensive RESTful API for cluster state inspection, telemetry retrieval, policy management, scaling trigger execution, and experiment execution.

* **Base URL:** `http://localhost:5055`
* **Content-Type:** `application/json`
* **Authentication:** Unauthenticated (designed for internal cluster / operator access)

---

## 2. Cluster & Telemetry Endpoints

### 2.1 Get System Status
Returns the operational health of the control plane, Kubernetes connectivity, target deployment replica status, and Prometheus integration state.

* **Method:** `GET`
* **Path:** `/api/status`
* **Response `200 OK`:**
```json
{
  "kubernetes": {
    "status": "connected",
    "context": "minikube",
    "namespace": "autoscaling-demo",
    "deployment": "sample-web-app",
    "desired_replicas": 2,
    "ready_replicas": 2,
    "available_replicas": 2,
    "updated_at": "2026-10-24T08:00:00Z"
  },
  "prometheus": {
    "status": "connected",
    "url": "http://localhost:9090",
    "reachable": true
  },
  "controller": {
    "status": "running",
    "mode": "embedded",
    "reconciliation_interval_seconds": 10,
    "active_policies_count": 6
  }
}
```

---

### 2.2 Get Current Telemetry Metrics
Returns the latest instantaneous metric snapshot aggregated from Prometheus and the cluster API.

* **Method:** `GET`
* **Path:** `/api/metrics`
* **Response `200 OK`:**
```json
{
  "timestamp": "2026-10-24T08:00:10Z",
  "cpu_utilization_percent": 0.43,
  "memory_utilization_percent": 10.77,
  "requests_per_second": 0.62,
  "latency_p95_ms": 2020.25,
  "error_rate_5xx_percent": 0.0,
  "telemetry_source": "prometheus",
  "is_stale": false
}
```

---

## 3. Decision & Policy Endpoints

### 3.1 Get Latest Scaling Decisions
Returns the most recent scaling evaluation result produced by the PRAH engine, including triggered rules and guardrail validation status.

* **Method:** `GET`
* **Path:** `/api/decisions`
* **Response `200 OK`:**
```json
{
  "decision_id": "dec-20261024-080010",
  "timestamp": "2026-10-24T08:00:10Z",
  "current_replicas": 2,
  "recommended_replicas": 2,
  "approved_replicas": 2,
  "action": "HOLD",
  "confidence_score": 1.0,
  "reason": "Current metrics within normal operating bounds",
  "triggered_rules": [],
  "guardrail_status": {
    "approved": true,
    "min_replicas_enforced": 2,
    "max_replicas_enforced": 10,
    "cooldown_active": false
  }
}
```

---

### 3.2 Get Active Scaling Policies
Returns the full set of declarative scaling policies loaded into memory from `policies/scaling-policies.yaml`.

* **Method:** `GET`
* **Path:** `/api/policies`
* **Response `200 OK`:**
```json
{
  "policies": [
    {
      "name": "HighCPUUtilization",
      "metric": "cpu_utilization_percent",
      "operator": ">",
      "threshold": 80.0,
      "priority": 90,
      "target_replicas_calc": "proportional",
      "action": "scale_up"
    },
    {
      "name": "HighLatencySpike",
      "metric": "latency_p95_ms",
      "operator": ">",
      "threshold": 500.0,
      "priority": 85,
      "target_replicas_calc": "offset_+2",
      "action": "scale_up"
    },
    {
      "name": "LowResourceDrain",
      "metric": "cpu_utilization_percent",
      "operator": "<",
      "threshold": 20.0,
      "priority": 30,
      "target_replicas_calc": "offset_-1",
      "action": "scale_down"
    }
  ],
  "count": 3
}
```

---

### 3.3 Get Scaling Execution History
Returns historical scaling decisions loaded from the append-only `logs/decisions.jsonl` audit file.

* **Method:** `GET`
* **Path:** `/api/history`
* **Query Parameters:**
  * `limit` (integer, optional): Maximum records to return (default: `50`).
* **Response `200 OK`:**
```json
{
  "history": [
    {
      "timestamp": "2026-10-24T07:44:33Z",
      "from_replicas": 2,
      "to_replicas": 2,
      "action": "HOLD",
      "reason": "Scale down rejected: minimum floor 2 enforced",
      "applied": false
    }
  ],
  "total_records": 1
}
```

---

### 3.4 Force Single Decision Evaluation Tick
Triggers an immediate, synchronous evaluation tick across the telemetry, policy engine, and guardrails without waiting for the next periodic cycle.

* **Method:** `POST`
* **Path:** `/api/evaluate`
* **Response `200 OK`:**
```json
{
  "status": "evaluated",
  "decision": {
    "target_replicas": 2,
    "action": "HOLD",
    "applied": false
  }
}
```

---

## 4. Workloads & Pod Inspection Endpoints

### 4.1 Get Workload Pod Information
Returns real-time container states, pod phase, restarts, and IP distribution for pods in the target deployment.

* **Method:** `GET`
* **Path:** `/api/workloads`
* **Response `200 OK`:**
```json
{
  "deployment": "sample-web-app",
  "namespace": "autoscaling-demo",
  "pod_count": 2,
  "pods": [
    {
      "name": "sample-web-app-7984f8846c-k5zpw",
      "phase": "Running",
      "ready": true,
      "restart_count": 0,
      "pod_ip": "10.244.0.12",
      "node": "minikube"
    },
    {
      "name": "sample-web-app-7984f8846c-m9xqr",
      "phase": "Running",
      "ready": true,
      "restart_count": 0,
      "pod_ip": "10.244.0.13",
      "node": "minikube"
    }
  ]
}
```

---

## 5. Experiment Execution Endpoints

### 5.1 Run Benchmark Experiment
Launches an asynchronous benchmark run comparing Baseline HPA against KubePilot.

* **Method:** `POST`
* **Path:** `/api/experiments/run`
* **Request Body:**
```json
{
  "experiment": "stable_workload",
  "mode": "both",
  "duration_seconds": 60
}
```
* **Response `202 Accepted`:**
```json
{
  "status": "started",
  "run_id": "exp-stable_workload-20261024-080500",
  "message": "Benchmark experiment initiated"
}
```

---

### 5.2 Get Benchmark Experiment Results
Retrieves the completed benchmark comparison data and time-series metrics.

* **Method:** `GET`
* **Path:** `/api/experiments/results`
* **Query Parameters:**
  * `run_id` (string, optional): Specific run ID. Defaults to latest completed run.
* **Response `200 OK`:**
```json
{
  "run_id": "exp-stable_workload-20261024-074249",
  "status": "COMPLETED",
  "baseline_result": { "avg_cpu_percent": 0.38, "successful_requests": 10 },
  "proposed_result": { "avg_cpu_percent": 0.40, "successful_requests": 10 }
}
```

---

## 6. Kubernetes Health & Liveness Probes

### 6.1 Liveness Probe
* **Method:** `GET`
* **Path:** `/healthz`
* **Response `200 OK`:**
```json
{
  "status": "healthy",
  "uptime_seconds": 3600
}
```

---

### 6.2 Readiness Probe
* **Method:** `GET`
* **Path:** `/readyz`
* **Response `200 OK`:**
```json
{
  "status": "ready",
  "policies_count": 6
}
```
* **Response `503 Service Unavailable`:** Returned if policies have not been loaded or the cluster connection is uninitialized.
