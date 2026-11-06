"""
Generates publication-quality figures for the KubePilot research paper.
Project ID: 357 | Alliance University, Bengaluru
Uses real empirical data from live Minikube benchmark runs.
"""

import csv
from pathlib import Path
import matplotlib.pyplot as plt

plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.labelsize": 11,
    "axes.titlesize": 12,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "figure.titlesize": 13,
})

EVIDENCE_DIR = Path(__file__).resolve().parent

def load_csv_data(filepath: Path):
    rows = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "elapsed": float(r["elapsed_seconds"]),
                "system": r["system"],
                "cpu": float(r["cpu_utilization_percent"]),
                "mem": float(r["memory_utilization_percent"]),
                "prom_rps": float(r["http_requests_per_second"]),
                "desired": int(r["desired_replicas"]),
                "current": int(r["current_replicas"]),
                "ready": int(r["ready_replicas"]),
                "action": r["scaling_action"],
                "rps_actual": float(r["workload_rps_actual"]),
                "latency_ms": float(r["workload_latency_avg_ms"]),
            })
    baseline = [r for r in rows if r["system"] == "baseline"]
    proposed = [r for r in rows if r["system"] == "proposed"]
    return baseline, proposed


def plot_experiment_1():
    csv_file = EVIDENCE_DIR / "stable_workload_latest.csv"
    if not csv_file.exists():
        print(f"File {csv_file} not found.")
        return

    baseline, proposed = load_csv_data(csv_file)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)

    # Replicas
    ax1.plot([r["elapsed"] for r in baseline], [r["ready"] for r in baseline], label="Native HPA Ready Replicas", color="#2563eb", linewidth=2)
    ax1.plot([r["elapsed"] for r in proposed], [r["ready"] for r in proposed], label="KubePilot PRAH Ready Replicas", color="#059669", linestyle="--", linewidth=2)
    ax1.set_ylabel("Pod Replicas")
    ax1.set_ylim(0, 5)
    ax1.set_title("Experiment 1: Stable Workload - Replicas over Time (Nominal 10 req/s)")
    ax1.legend(loc="upper right")
    ax1.grid(True, linestyle=":", alpha=0.6)

    # CPU Utilization
    ax2.plot([r["elapsed"] for r in baseline], [r["cpu"] for r in baseline], label="Baseline HPA CPU (%)", color="#3b82f6", alpha=0.8)
    ax2.plot([r["elapsed"] for r in proposed], [r["cpu"] for r in proposed], label="KubePilot PRAH CPU (%)", color="#10b981", alpha=0.8)
    ax2.set_xlabel("Elapsed Time (seconds)")
    ax2.set_ylabel("CPU Utilization (%)")
    ax2.set_ylim(0, 10)
    ax2.legend(loc="upper right")
    ax2.grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    out_file = EVIDENCE_DIR / "exp1_stable_workload.png"
    plt.savefig(out_file, dpi=300)
    plt.close()
    print(f"Generated: {out_file}")


def plot_experiment_2():
    csv_file = EVIDENCE_DIR / "traffic_spike_latest.csv"
    if not csv_file.exists():
        print(f"File {csv_file} not found.")
        return

    baseline, proposed = load_csv_data(csv_file)
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8), sharex=True)

    # 1. Replicas
    ax1.step([r["elapsed"] for r in baseline], [r["ready"] for r in baseline], label="Native HPA Ready Replicas", color="#dc2626", linewidth=2, where="post")
    ax1.step([r["elapsed"] for r in proposed], [r["ready"] for r in proposed], label="KubePilot PRAH Ready Replicas", color="#16a34a", linewidth=2, linestyle="-", where="post")
    ax1.set_ylabel("Ready Replicas")
    ax1.set_ylim(1, 6)
    ax1.set_title("Experiment 2: Sudden Traffic Spike - Scaling Dynamics & Replica Scaling")
    ax1.legend(loc="upper left")
    ax1.grid(True, linestyle=":", alpha=0.6)

    # 2. CPU Utilization
    ax2.plot([r["elapsed"] for r in baseline], [r["cpu"] for r in baseline], label="Native HPA Pod CPU (%)", color="#ea580c", linewidth=1.8)
    ax2.plot([r["elapsed"] for r in proposed], [r["cpu"] for r in proposed], label="KubePilot PRAH Pod CPU (%)", color="#059669", linewidth=1.8)
    ax2.axhline(y=20.0, color="#6b7280", linestyle=":", label="KubePilot Scale-Out Threshold (20%)")
    ax2.set_ylabel("CPU Utilization (%)")
    ax2.set_ylim(0, 35)
    ax2.legend(loc="upper right")
    ax2.grid(True, linestyle=":", alpha=0.6)

    # 3. Request Latency
    ax3.plot([r["elapsed"] for r in baseline], [r["latency_ms"] for r in baseline], label="Native HPA App Latency (ms)", color="#7c3aed", linewidth=1.5)
    ax3.plot([r["elapsed"] for r in proposed], [r["latency_ms"] for r in proposed], label="KubePilot App Latency (ms)", color="#0284c7", linewidth=1.5)
    ax3.set_xlabel("Elapsed Time (seconds)")
    ax3.set_ylabel("Avg Latency (ms)")
    ax3.set_ylim(0, 350)
    ax3.legend(loc="upper right")
    ax3.grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    out_file = EVIDENCE_DIR / "exp2_traffic_spike.png"
    plt.savefig(out_file, dpi=300)
    plt.close()
    print(f"Generated: {out_file}")


def plot_comparative_summary():
    """Generates an executive comparison bar chart for the paper."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))

    # Metrics
    categories = ["Stable (Exp 1)", "Traffic Spike (Exp 2)"]
    hpa_peaks = [2, 2] # in latest run
    prah_peaks = [2, 5]

    x = [0, 1]
    width = 0.35

    ax1.bar([p - width/2 for p in x], hpa_peaks, width, label="Native HPA", color="#ef4444")
    ax1.bar([p + width/2 for p in x], prah_peaks, width, label="KubePilot PRAH", color="#10b981")
    ax1.set_ylabel("Peak Replicas")
    ax1.set_title("Peak Replicas Reached")
    ax1.set_xticks(x)
    ax1.set_xticklabels(categories)
    ax1.set_ylim(0, 6)
    ax1.legend(loc="upper left")
    ax1.grid(True, linestyle=":", alpha=0.5)

    # Latency
    hpa_latencies = [29.44, 196.51]
    prah_latencies = [28.78, 205.34]

    ax2.bar([p - width/2 for p in x], hpa_latencies, width, label="Native HPA", color="#ef4444")
    ax2.bar([p + width/2 for p in x], prah_latencies, width, label="KubePilot PRAH", color="#10b981")
    ax2.set_ylabel("Average Request Latency (ms)")
    ax2.set_title("Application Service Latency")
    ax2.set_xticks(x)
    ax2.set_xticklabels(categories)
    ax2.legend(loc="upper left")
    ax2.grid(True, linestyle=":", alpha=0.5)

    plt.tight_layout()
    out_file = EVIDENCE_DIR / "comparative_summary.png"
    plt.savefig(out_file, dpi=300)
    plt.close()
    print(f"Generated: {out_file}")


if __name__ == "__main__":
    plot_experiment_1()
    plot_experiment_2()
    plot_comparative_summary()
    print("All publication figures successfully created in research/evidence/.")
