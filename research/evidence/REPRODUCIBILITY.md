# KubePilot: Experiment Reproducibility Guide

**Project Title:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications  
**Project ID:** 357 | Alliance University, Bengaluru  
**Authors:** KubePilot Engineering & Research Team  

---

## 1. Prerequisites & Environment Setup

### 1.1 Host Requirements
- **Operating System:** Windows 11 Enterprise (or Linux Ubuntu 22.04 LTS / macOS)
- **Virtualization:** Hyper-V / WSL2 enabled
- **Docker Desktop:** Installed and running (v4.30+)
- **Minikube:** v1.34+ (tested on v1.38.1)
- **Kubernetes CLI (`kubectl`):** v1.30+
- **Python:** 3.12 or 3.13 with `pip`

### 1.2 Python Dependencies
Install required Python packages:
```powershell
pip install -r requirements.txt
pip install matplotlib pytest requests pyyaml kubernetes
```

---

## 2. Infrastructure Setup & Verification

### 2.1 Start Minikube
```powershell
minikube start --driver=docker --cpus=4 --memory=8192
```

### 2.2 Deploy Kubernetes Manifests
Deploy namespace, RBAC permissions, policy storage PVC, Prometheus, and the sample microservice:
```powershell
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/policies-pvc.yaml
kubectl apply -f k8s/controller-rbac.yaml
kubectl apply -f k8s/controller-deployment.yaml
kubectl apply -f k8s/dashboard-deployment.yaml
```

Verify that all pods are Running:
```powershell
kubectl get pods -n autoscaling-demo
kubectl get pods -n monitoring
```

### 2.3 Establish Port-Forwarding (Local Host Access)
In two background PowerShell terminals, establish port-forwarding:
```powershell
# Terminal 1: Prometheus HTTP API
kubectl port-forward -n monitoring svc/prometheus-server 9090:9090

# Terminal 2: Sample Web App Microservice
kubectl port-forward -n autoscaling-demo svc/sample-web-app 8080:8080
```

Verify connectivity:
```powershell
curl http://localhost:9090/-/healthy
curl http://localhost:8080/
```

---

## 3. Running Unit and Regression Tests

Run the full automated test suite (112 tests across all modules):
```powershell
python -m pytest
```

Run live cluster regression tests:
```powershell
python -m pytest tests/test_fixes_regression.py
```

Expected output:
```
tests/test_fixes_regression.py ......... [100%]
============================== 9 passed in ~15-25s ==============================
```

---

## 4. Reproducing Empirical Research Experiments

### 4.1 Experiment 1: Stable Workload (Nominal Demand)
Executes a steady 10 req/s load test comparing Native HPA vs KubePilot PRAH stability:
```powershell
python -m controller.experiment_runner --experiment stable_workload --mode both
```
- Results are saved to `experiments/results/exp-stable_workload-*.json` and `.csv`.
- Output is also mirrored to `research/evidence/stable_workload_latest.json`.

### 4.2 Experiment 2: Sudden Traffic Spike (Computational Surge)
Executes a concurrent CPU math load + HTTP surge to evaluate scale-out reactivity:
```powershell
python -m controller.experiment_runner --experiment traffic_spike --mode both
```
- Results are saved to `experiments/results/exp-traffic_spike-*.json` and `.csv`.
- Output is also mirrored to `research/evidence/traffic_spike_latest.json`.

### 4.3 Generating Publication Figures
Generate 300 dpi PNG charts for the research paper:
```powershell
python research/evidence/generate_charts.py
```
Outputs:
- `research/evidence/exp1_stable_workload.png`
- `research/evidence/exp2_traffic_spike.png`
- `research/evidence/comparative_summary.png`

---

## 5. Clean Teardown

To reset the workload deployment scale back to nominal:
```powershell
kubectl scale deployment sample-web-app -n autoscaling-demo --replicas=2
kubectl delete hpa sample-web-app -n autoscaling-demo --ignore-not-found=true
```

To stop port-forward background tasks:
```powershell
Get-Process -Name kubectl | Stop-Process
```
