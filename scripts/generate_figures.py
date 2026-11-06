"""
Publication-Quality IEEE Figure Generator.
Generates 300 DPI PNG and Vector PDF figures from empirical benchmark measurements.
Data source: research_evidence/experiment_summary.csv and research_evidence/raw/*.csv
Strict Rule: Zero hardcoded or illustrative data. All plots derive strictly from genuine CSVs.
"""

from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = PROJECT_ROOT / "research_evidence"
RAW_DIR = EVIDENCE_DIR / "raw"
FIGURES_DIR = EVIDENCE_DIR / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_CSV = EVIDENCE_DIR / "experiment_summary.csv"

# Configure IEEE publication style
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 10,
    "axes.labelsize": 11,
    "axes.titlesize": 12,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "figure.titlesize": 13,
    "lines.linewidth": 1.75,
    "lines.markersize": 5,
    "grid.alpha": 0.4,
    "grid.linestyle": "--",
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})


def generate_all_figures():
    if not SUMMARY_CSV.exists():
        print(f"Summary CSV {SUMMARY_CSV} does not exist yet. Please run benchmarks first.")
        return

    df_summary = pd.read_csv(SUMMARY_CSV)
    print(f"Loaded {len(df_summary)} trials from {SUMMARY_CSV}")

    # -------------------------------------------------------------------------
    # Figure 1: Replica Dynamics & Traffic Surge (E3 Traffic Spike Time-Series)
    # -------------------------------------------------------------------------
    hpa_e3_files = sorted(RAW_DIR.glob("E3_sudden_spike_HPA_trial*.csv"))
    kp_e3_files = sorted(RAW_DIR.glob("E3_sudden_spike_KubePilot_trial*.csv"))

    if hpa_e3_files and kp_e3_files:
        df_hpa = pd.read_csv(hpa_e3_files[0])
        df_kp = pd.read_csv(kp_e3_files[0])

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(7, 6.5), sharex=True)

        # Plot A: Workload RPS & Latency
        ax1.plot(df_hpa["elapsed_seconds"], df_hpa["workload_rps_actual"], color="#2563eb", label="Synthetic Load (req/s)", linestyle="-")
        ax1.set_ylabel("Throughput (req/s)")
        ax1.set_title("(a) Workload Surge Profile (E3 Sudden Traffic Spike)")
        ax1.grid(True)
        ax1.axvspan(5.0, 25.0, color="#fef3c7", alpha=0.5, label="Surge Window (t=5-25s)")
        ax1.legend(loc="upper left")

        # Plot B: Replicas (HPA vs KubePilot)
        ax2.step(df_hpa["elapsed_seconds"], df_hpa["desired_replicas"], where="post", color="#dc2626", label="Native HPA Desired", linestyle="--")
        ax2.step(df_hpa["elapsed_seconds"], df_hpa["ready_replicas"], where="post", color="#f87171", label="Native HPA Ready", linestyle=":")
        ax2.step(df_kp["elapsed_seconds"], df_kp["desired_replicas"], where="post", color="#16a34a", label="KubePilot Desired", linestyle="-")
        ax2.step(df_kp["elapsed_seconds"], df_kp["ready_replicas"], where="post", color="#4ade80", label="KubePilot Ready", linestyle="-.")
        ax2.set_ylabel("Replica Count")
        ax2.set_title("(b) Pod Replicas over Time (Desired vs. Ready)")
        ax2.set_yticks(range(1, 7))
        ax2.grid(True)
        ax2.legend(loc="upper left")

        # Plot C: CPU Utilization
        ax3.plot(df_hpa["elapsed_seconds"], df_hpa["cpu_utilization_percent"], color="#dc2626", label="Native HPA Deployment CPU (%)", linestyle="--")
        ax3.plot(df_kp["elapsed_seconds"], df_kp["cpu_utilization_percent"], color="#16a34a", label="KubePilot Deployment CPU (%)", linestyle="-")
        ax3.axhline(75.0, color="#9333ea", linestyle=":", label="Scale-Out Threshold (75%)")
        ax3.set_xlabel("Elapsed Time (seconds)")
        ax3.set_ylabel("CPU Utilization (%)")
        ax3.set_title("(c) Deployment CPU Utilization (%)")
        ax3.grid(True)
        ax3.legend(loc="upper left")

        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "fig1_e3_scaling_dynamics.png")
        plt.savefig(FIGURES_DIR / "fig1_e3_scaling_dynamics.pdf")
        plt.close()
        print("Generated Fig 1: E3 Scaling Dynamics (PNG & PDF)")

    # -------------------------------------------------------------------------
    # Figure 2: Latency Distribution Comparison across Primary Scenarios
    # -------------------------------------------------------------------------
    scenarios_to_plot = [s for s in ["E1_stable_workload", "E3_sudden_spike"] if s in df_summary["scenario"].values]
    if scenarios_to_plot:
        fig, ax = plt.subplots(figsize=(6, 4))
        x = np.arange(len(scenarios_to_plot))
        width = 0.35

        hpa_means = [df_summary[(df_summary["scenario"] == s) & (df_summary["controller"] == "HPA")]["mean_latency_ms"].mean() for s in scenarios_to_plot]
        hpa_p95 = [df_summary[(df_summary["scenario"] == s) & (df_summary["controller"] == "HPA")]["p95_latency_ms"].mean() for s in scenarios_to_plot]
        kp_means = [df_summary[(df_summary["scenario"] == s) & (df_summary["controller"] == "KubePilot")]["mean_latency_ms"].mean() for s in scenarios_to_plot]
        kp_p95 = [df_summary[(df_summary["scenario"] == s) & (df_summary["controller"] == "KubePilot")]["p95_latency_ms"].mean() for s in scenarios_to_plot]

        rects1 = ax.bar(x - width/2, hpa_p95, width, label="Native HPA (p95)", color="#f87171", edgecolor="#dc2626")
        rects2 = ax.bar(x + width/2, kp_p95, width, label="KubePilot PRAH (p95)", color="#86efac", edgecolor="#16a34a")

        ax.plot(x - width/2, hpa_means, "o", color="#b91c1c", label="HPA Mean")
        ax.plot(x + width/2, kp_means, "s", color="#15803d", label="KubePilot Mean")

        ax.set_ylabel("Request Latency (ms)")
        ax.set_title("Request Latency Comparison (Mean and 95th Percentile)")
        ax.set_xticks(x)
        clean_scenarios = [s.replace("_", " ") for s in scenarios_to_plot]
        ax.set_xticklabels(clean_scenarios)
        ax.legend()
        ax.grid(True, axis="y")

        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "fig2_latency_comparison.png")
        plt.savefig(FIGURES_DIR / "fig2_latency_comparison.pdf")
        plt.close()
        print("Generated Fig 2: Latency Comparison (PNG & PDF)")

    # -------------------------------------------------------------------------
    # Figure 3: Scaling Response Time & Pod Readiness Comparison
    # -------------------------------------------------------------------------
    df_e3 = df_summary[df_summary["scenario"] == "E3_sudden_spike"]
    if not df_e3.empty:
        fig, ax = plt.subplots(figsize=(6, 4))
        controllers = ["HPA", "KubePilot"]
        resp_times = []
        ready_times = []
        resp_err = []
        ready_err = []

        for c in controllers:
            sub = df_e3[df_e3["controller"] == c]
            valid_resp = sub["first_scaling_response_time"].dropna()
            valid_ready = sub["pod_readiness_time"].dropna()
            resp_times.append(valid_resp.mean() if len(valid_resp) > 0 else 0.0)
            ready_times.append(valid_ready.mean() if len(valid_ready) > 0 else 0.0)
            resp_err.append(valid_resp.std() if len(valid_resp) > 1 else 0.0)
            ready_err.append(valid_ready.std() if len(valid_ready) > 1 else 0.0)

        x = np.arange(len(controllers))
        width = 0.35

        ax.bar(x - width/2, resp_times, width, yerr=resp_err, capsize=4, label="Scaling Response Time (s)", color="#60a5fa", edgecolor="#1d4ed8")
        ax.bar(x + width/2, ready_times, width, yerr=ready_err, capsize=4, label="Pod Readiness Time (s)", color="#fbbf24", edgecolor="#d97706")

        ax.set_ylabel("Time from Workload Trigger (seconds)")
        ax.set_title("Autoscaling Reactivity & Pod Readiness Latency (E3 Spike)")
        ax.set_xticks(x)
        ax.set_xticklabels(["Native Kubernetes HPA", "KubePilot PRAH"])
        ax.legend()
        ax.grid(True, axis="y")

        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "fig3_scaling_response_time.png")
        plt.savefig(FIGURES_DIR / "fig3_scaling_response_time.pdf")
        plt.close()
        print("Generated Fig 3: Scaling Response Time (PNG & PDF)")

    # -------------------------------------------------------------------------
    # Figure 4: Scaling Stability & Event Counts Across All Scenarios
    # -------------------------------------------------------------------------
    scenarios = df_summary["scenario"].unique()
    if len(scenarios) > 0:
        fig, ax = plt.subplots(figsize=(7, 4))
        hpa_events = []
        kp_events = []

        for s in scenarios:
            sub_hpa = df_summary[(df_summary["scenario"] == s) & (df_summary["controller"] == "HPA")]
            sub_kp = df_summary[(df_summary["scenario"] == s) & (df_summary["controller"] == "KubePilot")]
            hpa_events.append(sub_hpa["scaling_events"].mean() if not sub_hpa.empty else 0.0)
            kp_events.append(sub_kp["scaling_events"].mean() if not sub_kp.empty else 0.0)

        x = np.arange(len(scenarios))
        width = 0.35
        ax.bar(x - width/2, hpa_events, width, label="Native HPA Scaling Events", color="#f87171", edgecolor="#dc2626")
        ax.bar(x + width/2, kp_events, width, label="KubePilot PRAH Scaling Events", color="#86efac", edgecolor="#16a34a")

        clean_labels = [s.replace("E", "E").replace("_", " ") for s in scenarios]
        ax.set_xticks(x)
        ax.set_xticklabels(clean_labels, rotation=15, ha="right")
        ax.set_ylabel("Mean Scaling Actions per Run")
        ax.set_title("Scaling Actions & Stability Across Scenarios")
        ax.legend()
        ax.grid(True, axis="y")

        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "fig4_scaling_events_stability.png")
        plt.savefig(FIGURES_DIR / "fig4_scaling_events_stability.pdf")
        plt.close()
        print("Generated Fig 4: Scaling Events & Stability (PNG & PDF)")

    # -------------------------------------------------------------------------
    # Figure 5: Peak vs Mean CPU Utilization
    # -------------------------------------------------------------------------
    if len(scenarios) > 0:
        fig, ax = plt.subplots(figsize=(7, 4))
        hpa_peak_cpu = [df_summary[(df_summary["scenario"] == s) & (df_summary["controller"] == "HPA")]["peak_cpu_percent"].mean() for s in scenarios]
        kp_peak_cpu = [df_summary[(df_summary["scenario"] == s) & (df_summary["controller"] == "KubePilot")]["peak_cpu_percent"].mean() for s in scenarios]

        x = np.arange(len(scenarios))
        width = 0.35
        ax.bar(x - width/2, hpa_peak_cpu, width, label="Native HPA Peak CPU (%)", color="#fb923c", edgecolor="#ea580c")
        ax.bar(x + width/2, kp_peak_cpu, width, label="KubePilot Peak CPU (%)", color="#38bdf8", edgecolor="#0284c7")

        ax.axhline(75.0, color="#9333ea", linestyle="--", label="Target Scaling Threshold (75%)")
        clean_labels = [s.replace("E", "E").replace("_", " ") for s in scenarios]
        ax.set_xticks(x)
        ax.set_xticklabels(clean_labels, rotation=15, ha="right")
        ax.set_ylabel("Peak CPU Utilization (%)")
        ax.set_title("Peak CPU Utilization Across Workload Scenarios")
        ax.legend()
        ax.grid(True, axis="y")

        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "fig5_cpu_utilization.png")
        plt.savefig(FIGURES_DIR / "fig5_cpu_utilization.pdf")
        plt.close()
        print("Generated Fig 5: CPU Utilization (PNG & PDF)")

    print(f"All figures successfully generated in {FIGURES_DIR}")


if __name__ == "__main__":
    generate_all_figures()
