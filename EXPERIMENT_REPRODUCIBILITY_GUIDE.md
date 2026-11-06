# KubePilot vs Native HPA — Reproducibility Guide

## Prerequisites
- Docker Desktop running; existing Minikube cluster started (`minikube start`) — do **not** delete/recreate it or its PVCs.
- Namespace `autoscaling-demo` with `sample-web-app` (2 replicas, requests 100m/128Mi, limits 500m/256Mi), metrics-server enabled, Prometheus in `monitoring`.
- Prometheus reachable at `http://localhost:9090` (`kubectl port-forward svc/prometheus-server 9090:9090 -n monitoring`).
- The in-cluster `autoscaling-controller` must stay in dry-run (`DRY_RUN=true`, `ENABLE_LIVE_EXECUTION=false`) — it is by default.
- Python 3.13 with `requirements.txt`, plus `numpy matplotlib python-docx`.
- Image `sample-web-app:latest` available inside Minikube (used for the in-cluster load-generator pod `kp-loadgen`, created automatically).

## Run
```bash
python -u scripts/run_experimental_evaluation.py --scenarios stable spike gradual bursty --trials 5
python -u scripts/run_experimental_evaluation.py --scenarios decreasing --trials 3
python scripts/analyze_and_report.py
```
The runner is resumable (existing `raw/<scenario>_<system>_t<n>.json` are skipped) and stops if telemetry coverage < 80 % or HPA ownership is violated.

## Ownership protocol (per trial)
1. HPA deleted, Deployment scaled to 2, wait ready, wait Prometheus CPU < 20 %.
2. HPA trial: apply `k8s/baseline-hpa.yaml`; KubePilot never cycled, live execution off.
   KubePilot trial: assert no HPA exists, enable live execution, cycle every 10 s.
3. After the trial: HPA deleted, replicas reset to 2.

## Scenarios (see `SCENARIOS` / `build_phases` in the runner)
stable 90 s · gradual 240 s · spike 210 s · bursty 210 s · decreasing 480 s. One worker ≈ 0.1 CPU core.

## Outputs
- `experimental_evaluation/raw/` — per trial JSON (summary, 1 s samples, every request) + CSVs
- `experimental_evaluation/datasets/` — `per_trial_results.csv`, `aggregate_statistics.csv`, `results_summary.json`
- `experimental_evaluation/figures/` — PNG graphs
- `experimental_evaluation/calibration/` — 2 pilot spike trials (120 s version), excluded from results
- `KUBEPILOT_EXPERIMENTAL_EVALUATION_REPORT.docx`

## Notes
No ML/forecasting is used; all values come from the Kubernetes API, Prometheus and client request logs. Metrics not measurable for a system are written as NOT MEASURED.
