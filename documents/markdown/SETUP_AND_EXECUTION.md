# Setup and Execution Guide: KubePilot

## 1. Prerequisites & Environment

Before deploying or running KubePilot, verify that your host environment meets the following specifications:

| Component | Minimum Version | Verified Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Operating System** | Windows 10/11, macOS, or Linux | Windows 11 Pro 64-bit | Host environment |
| **Docker Engine** | Docker 24.0+ | Docker Desktop 28.0+ | Minikube container runtime |
| **Minikube** | v1.32.0+ | v1.34.0+ | Local Kubernetes cluster |
| **Kubectl** | v1.28.0+ | v1.31.0+ | Kubernetes CLI |
| **Python** | 3.11+ | Python 3.13.2 | Controller & Dashboard runtime |
| **Pip** | 24.0+ | 26.1.2 | Package manager |

---

## 2. Cluster Provisioning

### Step 2.1: Start Minikube with Docker Driver
Open PowerShell (or Bash) as Administrator and initialize Minikube:

```powershell
# Start Minikube with Docker driver and dedicated resources
minikube start --driver=docker --cpus=4 --memory=6144 --disk-size=20g

# Enable Kubernetes Metrics Server addon
minikube addons enable metrics-server

# Verify cluster connectivity
kubectl cluster-info
kubectl get nodes -o wide
```

### Step 2.2: Create Namespace and Deploy Sample Application
Deploy the target namespace and the containerized sample web application:

```powershell
# Create autoscaling demo namespace
kubectl apply -f k8s/namespace.yaml

# Deploy sample web application (Deployment and Service)
kubectl apply -f app/sample-app.yaml

# Verify deployment readiness (Target: 2/2 pods Running and Ready)
kubectl -n autoscaling-demo rollout status deployment/sample-web-app
kubectl -n autoscaling-demo get pods -l app=sample-web-app
```

> [!IMPORTANT]
> The target deployment `sample-web-app` must have at least **2 ready replicas** as mandated by the baseline high availability guardrails.

---

## 3. Prometheus Monitoring Setup

KubePilot ingests metrics via standard PromQL queries against Prometheus at `http://localhost:9090` (or `http://prometheus:9090` in-cluster).

### Option A: In-Cluster Prometheus Deployment (Recommended)
Deploy the Prometheus instance into the cluster:

```powershell
# Deploy Prometheus ConfigMap, Deployment, and Service
kubectl apply -f monitoring/prometheus-config.yaml
kubectl apply -f monitoring/prometheus-deployment.yaml

# Wait for Prometheus pod readiness
kubectl -n autoscaling-demo rollout status deployment/prometheus

# Forward Prometheus port to localhost:9090
kubectl -n autoscaling-demo port-forward svc/prometheus 9090:9090
```

### Option B: Verification of Prometheus Scraping
In a separate terminal, verify that Prometheus is actively collecting metrics:

```powershell
# Check Prometheus health endpoint
curl -s http://localhost:9090/-/healthy

# Query target deployment container CPU usage
curl -G "http://localhost:9090/api/v1/query" --data-urlencode "query=sum(rate(container_cpu_usage_seconds_total{namespace=\"autoscaling-demo\"}[1m]))"
```

---

## 4. Running the KubePilot Framework

### Step 4.1: Install Python Dependencies
Install runtime requirements into your Python environment:

```powershell
# Navigate to project root
cd c:\Users\SRIRAM\design_project

# Install controller and dashboard requirements
pip install -r dashboard/requirements.txt
pip install reportlab pytest pytest-asyncio
```

### Step 4.2: Start the KubePilot Web Dashboard & Embedded Controller
The Web Dashboard includes the embedded `StrategyCoordinator` daemon which executes the autoscaling reconciliation loop in the background:

```powershell
# Start dashboard on port 5055
python -m dashboard.app
```

* Dashboard UI: **`http://localhost:5055`**
* Health probe: **`http://localhost:5055/healthz`**
* Readiness probe: **`http://localhost:5055/readyz`**

### Step 4.3: Running Standalone Controller Daemon (Alternative)
If running in headless or containerized environments without the web interface:

```powershell
# Start standalone reconciliation loop
python -m controller.main
```

---

## 5. Executing Benchmark Experiments

KubePilot includes an automated experiment runner that generates synthetic traffic patterns and compares native Kubernetes HPA against the KubePilot PRAH framework.

### Running Experiment 1: Stable Workload
Generates a steady 30 requests/second load for 60 seconds across both Baseline HPA and KubePilot:

```powershell
python -m controller.experiment_runner --experiment stable_workload --mode both --duration 60
```

### Running Experiment 2: Sudden Traffic Spike
Generates a sudden 120 requests/second load spike for 60 seconds across both Baseline HPA and KubePilot:

```powershell
python -m controller.experiment_runner --experiment traffic_spike --mode both --duration 60
```

### Running Both Experiments Consecutively
```powershell
python -m controller.experiment_runner --experiment all --mode both
```

All benchmark measurements are exported to:
* `experiments/results/exp-<experiment_type>-<timestamp>.csv`
* `experiments/results/exp-<experiment_type>-<timestamp>.json`

---

## 6. Verification and Health Checks

Run the following checks to confirm end-to-end operational health:

```powershell
# 1. Verify Kubernetes deployment status
kubectl -n autoscaling-demo get deployment sample-web-app -o jsonpath='{"Desired: "}{.spec.replicas}{" | Ready: "}{.status.readyReplicas}{"\n"}'

# 2. Check Dashboard status API
curl -s http://localhost:5055/api/status

# 3. Check live telemetry API
curl -s http://localhost:5055/api/metrics

# 4. Inspect latest autoscaling decisions
curl -s http://localhost:5055/api/decisions

# 5. Verify decision audit trail log file
Get-Content -Tail 5 logs\decisions.jsonl
```

---

## 7. Clean Teardown Procedures

To stop KubePilot and teardown the test cluster:

```powershell
# Stop background Python processes
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*dashboard.app*" } | Stop-Process -Force

# Delete deployed Kubernetes resources
kubectl delete -f app/sample-app.yaml
kubectl delete -f monitoring/prometheus-deployment.yaml
kubectl delete -f monitoring/prometheus-config.yaml
kubectl delete -f k8s/namespace.yaml

# Stop Minikube cluster
minikube stop
```
