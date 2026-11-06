# Verified Testbed & Environment Specification (v2)

**Project:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications (Project 357)  
**Evaluation Standard:** IEEE Conference Research Paper Reproducibility Standard  
**Verification Date:** November 5, 2026  

---

## 1. Verified Software & Runtime Specification

All experiments and functional tests were executed against a single, verified Kubernetes testbed environment. Every version string was verified directly from the live cluster CLI tools and HTTP management endpoints:

| Component | Verified Specification | Verification Source / Command |
|---|---|---|
| **Minikube** | `v1.38.1` (commit: `c93a4cb9311efc66b90d33ea03f75f2c4120e9b0`) | `minikube version` |
| **Kubernetes Client** | `v1.36.1` (GitTreeState: clean) | `kubectl version --client` |
| **Kubernetes Server** | `v1.35.1` (GitCommit: `e06c7104b9015948f95c4323bc068b5774a005ee`) | `kubectl version` |
| **Node Container Runtime** | `docker://29.2.1` (Debian GNU/Linux 12 bookworm) | `kubectl get nodes -o wide` |
| **Host Docker Engine** | Docker Desktop Engine `29.4.3` (API version `1.54`) | `docker version` |
| **Host Kernel** | Linux `6.6.87.2-microsoft-standard-WSL2` x86_64 | `kubectl get nodes -o wide` |
| **Prometheus Server** | `v2.51.0` (commit: `c05c15512acb675e3f6cd662a6727854e93fc024`, Go: `go1.22.1`) | `GET http://localhost:9090/api/v1/status/buildinfo` |
| **Python Runtime** | Python `3.10.11` (tags/v3.10.11:7d4cc5a, AMD64) | `python --version` |

---

## 2. Cluster Architecture & Sizing

- **Node Name:** `minikube`
- **Node Allocatable Resources:**
  - CPU: `12000m` (12 vCPUs)
  - Memory: `8,182,247,424 bytes` (~7,803 MiB)
  - Pod Limit: 110 pods
- **Target Namespace:** `autoscaling-demo`
- **Target Deployment:** `sample-web-app`
- **Pod Container Resource Quotas:**
  - `requests.cpu`: `100m` ($0.100\text{ cores}$)
  - `requests.memory`: `128Mi` ($134,217,728\text{ bytes}$)
  - `limits.cpu`: `500m` ($0.500\text{ cores}$)
  - `limits.memory`: `256Mi` ($268,435,456\text{ bytes}$)
- **Baseline Replicas:** 2 pods (Committed baseline: $200\text{m}$ CPU request, $256\text{Mi}$ RAM request)

---

## 3. Raw System Output Verifications

### `minikube version`
```
minikube version: v1.38.1
commit: c93a4cb9311efc66b90d33ea03f75f2c4120e9b0
```

### `kubectl version`
```
Client Version: v1.36.1
Kustomize Version: v5.0.4-0.20230601165947-6ce0bf390ce3
Server Version: v1.35.1
```

### `kubectl get nodes -o wide`
```
NAME       STATUS   ROLES           AGE   VERSION   INTERNAL-IP    EXTERNAL-IP   OS-IMAGE                         KERNEL-VERSION                      CONTAINER-RUNTIME
minikube   Ready    control-plane   37d   v1.35.1   192.168.49.2   <none>        Debian GNU/Linux 12 (bookworm)   6.6.87.2-microsoft-standard-WSL2   docker://29.2.1
```

### `GET http://localhost:9090/api/v1/status/buildinfo`
```json
{
  "status": "success",
  "data": {
    "version": "2.51.0",
    "revision": "c05c15512acb675e3f6cd662a6727854e93fc024",
    "branch": "HEAD",
    "buildUser": "root@55bfb0aeef97",
    "buildDate": "20240327-09:47:33",
    "goVersion": "go1.22.1"
  }
}
```

---

## 4. Benchmark Execution Commands

To reproduce the benchmark suite and test execution exactly:

```powershell
# 1. Run full unit and integration test suite (115 tests)
python -m pytest

# 2. Run live functional test suite (18 tests, including FT-15 fix)
python scripts/run_functional_tests_v2.py

# 3. Run complete benchmark suite (52 trials: E1-E5 5 alternating trials + E6 + E7)
python scripts/run_benchmarks_v2.py

# 4. Generate IEEE publication figures (300 DPI PNG + vector PDF)
python scripts/generate_figures_v2.py
```
