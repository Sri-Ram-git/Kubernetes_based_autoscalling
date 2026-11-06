"""Aggregate raw trials -> CSV/JSON datasets, figures and the Word report. Uses only measured data."""
import csv, json, platform, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / "experimental_evaluation"
RAW, FIG, DATA = EV / "raw", EV / "figures", EV / "datasets"
FIG.mkdir(exist_ok=True); DATA.mkdir(exist_ok=True)
SCS = ["low", "moderate", "spike", "sustained_high", "reduction_recovery", "variable"]
SYS = ["HPA", "KubePilot"]
COL = {"HPA": "#1f77b4", "KubePilot": "#d95f02"}
NM = "NOT MEASURED"
METRICS = [
    ("m1_decision_latency_ms_mean", "1. Scaling decision latency", "ms"),
    ("m2_exec_time_s_mean", "2. Scaling execution time", "s"),
    ("m3_resp_ms_mean", "3. Avg application response time", "ms"),
    ("m4_throughput_rps", "4. Throughput", "req/s"),
    ("m5_error_rate_pct", "5. Application error rate", "%"),
    ("m6_cpu_pct_mean", "6. CPU utilisation (of requests)", "%"),
    ("m7_mem_pct_mean", "7. Memory utilisation (of limits)", "%"),
    ("m8_reversals", "8. Scaling direction reversals", "count"),
    ("m9_verification_success_pct", "9. Execution verification success", "%"),
]
EXTRA = [("m2_exec_time_s_first_out", "First scale-out execution time", "s"),
         ("reaction_s_first_out", "Load-onset to first scale-out", "s"),
         ("m3_resp_ms_p95", "Response time p95", "ms"), ("m3_light_resp_ms_mean", "Light-probe response time", "ms"),
         ("peak_replicas", "Peak replicas", "pods"), ("n_events", "Scaling events", "count")]
LOWER = {"m1_decision_latency_ms_mean", "m2_exec_time_s_mean", "m3_resp_ms_mean", "m5_error_rate_pct", "m8_reversals"}
HIGHER = {"m4_throughput_rps", "m9_verification_success_pct"}
EVID = {"m1_decision_latency_ms_mean": "KubePilot: instrumented wrapper around fetch_current_telemetry + compute_decision (per cycle). HPA: decision is internal to kube-controller-manager, no timestamp exposed",
        "m2_exec_time_s_mean": "1 s Kubernetes-API replica poll (desired to ready), same observer for both", "m3_resp_ms_mean": "in-cluster client request log",
        "m4_throughput_rps": "in-cluster client request log", "m5_error_rate_pct": "in-cluster client request log (non-200 / timeout)",
        "m6_cpu_pct_mean": "Prometheus cAdvisor query, 1 s sampling", "m7_mem_pct_mean": "Prometheus cAdvisor query, 1 s sampling",
        "m8_reversals": "sign changes of desired-replica events (1 s poll)", "m9_verification_success_pct": "events reaching ready==desired within 120 s / events (1 s poll)"}


def load():
    out = []
    for f in sorted(RAW.glob("*_p[0-9]_*.json")):
        d = json.load(open(f, encoding="utf-8")); d["summary"]["_file"] = f.name
        out.append(d)
    return out


def stats(vals):
    v = np.array([x for x in vals if x is not None], float)
    if len(v) == 0:
        return None
    m = float(v.mean()); sd = float(v.std(ddof=1)) if len(v) > 1 else 0.0
    return {"n": int(len(v)), "mean": m, "median": float(np.median(v)), "std": sd,
            "cv_pct": (sd / m * 100) if m else None, "p95": float(np.percentile(v, 95)),
            "min": float(v.min()), "max": float(v.max())}


def fmt(s, d=2):
    return NM if s is None else f"{s['mean']:.{d}f} ± {s['std']:.{d}f}"


def main():
    ALL = load()
    if not ALL:
        sys.exit("no trials")
    invalid = [t for t in ALL if not t["summary"]["telemetry_valid"]]
    T = [t for t in ALL if t["summary"]["telemetry_valid"]]
    S = [t["summary"] for t in T]
    by = {(sc, sy): [s for s in S if s["scenario"] == sc and s["system"] == sy] for sc in SCS for sy in SYS}
    present = [sc for sc in SCS if by[(sc, "HPA")] or by[(sc, "KubePilot")]]

    # ---- datasets ----
    flat_keys = [k for k in S[0].keys() if not isinstance(S[0][k], (list, dict, tuple))]
    with open(DATA / "per_trial_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=flat_keys, extrasaction="ignore"); w.writeheader(); w.writerows(S)
    agg = {}
    for sc in present:
        for sy in SYS:
            rows = by[(sc, sy)]
            if not rows:
                continue
            a = {k: stats([r.get(k) for r in rows]) for k, _, _ in METRICS + EXTRA}
            a["trials"] = len(rows)
            pool = [r[1] for t in T if t["summary"]["scenario"] == sc and t["summary"]["system"] == sy for r in t["requests"] if r[2] == 1]
            a["pooled_latency_ms"] = {"n": len(pool), **{f"p{p}": float(np.percentile(pool, p)) for p in (50, 90, 95, 99)}} if pool else None
            agg[f"{sc}|{sy}"] = a
    json.dump({"aggregate": agg, "valid_trials": S, "excluded_trials": [t["summary"] for t in invalid]},
              open(DATA / "results_summary.json", "w", encoding="utf-8"), indent=1, default=str)
    with open(DATA / "aggregate_statistics.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["profile", "system", "metric", "unit", "n", "mean", "median", "std", "cv_pct", "p95", "min", "max"])
        for key, a in agg.items():
            sc, sy = key.split("|")
            for k, lab, u in METRICS + EXTRA:
                s = a[k]
                w.writerow([sc, sy, lab, u] + ([s[x] for x in ("n", "mean", "median", "std", "cv_pct", "p95", "min", "max")] if s else [NM] * 8))

    # ---- figures ----
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    figs = {}
    for k, lab, u in METRICS:
        fig, ax = plt.subplots(figsize=(6.6, 3.3))
        wdt = 0.36
        for i, sy in enumerate(SYS):
            xs, ms, es = [], [], []
            for j, sc in enumerate(present):
                v = [r.get(k) for r in by[(sc, sy)] if r.get(k) is not None]
                x = j + (i - 0.5) * wdt
                if v:
                    xs.append(x); ms.append(np.mean(v)); es.append(np.std(v, ddof=1) if len(v) > 1 else 0)
                    ax.scatter([x] * len(v), v, color="k", s=8, zorder=3, alpha=.6)
                else:
                    ax.text(x, 0, "NM", ha="center", va="bottom", fontsize=7, color="gray")
            if xs:
                ax.bar(xs, ms, wdt, yerr=es, color=COL[sy], label=sy, capsize=2, alpha=.9)
            else:
                ax.bar([], [], color=COL[sy], label=sy + " (not measured)")
        ax.set_xticks(range(len(present))); ax.set_xticklabels([p.replace("_", "\n") for p in present])
        ax.set_ylabel(u); ax.set_title(lab + " (mean ± SD; dots = trials)")
        ax.legend(frameon=False); fig.tight_layout()
        p = FIG / f"metric_{k}.png"; fig.savefig(p, dpi=160); plt.close(fig); figs[k] = p
    for sc in present:
        fig, axs = plt.subplots(2, 1, figsize=(6.6, 4.6), sharex=True)
        for sy in SYS:
            t = next((t for t in T if t["summary"]["scenario"] == sc and t["summary"]["system"] == sy and t["summary"]["trial"] == 1), None)
            if not t:
                continue
            x = [s["t"] for s in t["samples"]]
            axs[0].step(x, [s["desired"] for s in t["samples"]], where="post", color=COL[sy], label=f"{sy} desired")
            axs[0].plot(x, [s["ready"] for s in t["samples"]], color=COL[sy], ls=":", label=f"{sy} ready")
            axs[1].plot(x, [s["cpu_pct"] if s["cpu_pct"] is not None else np.nan for s in t["samples"]], color=COL[sy], label=sy)
        axs[0].set_ylabel("replicas"); axs[0].legend(frameon=False, ncol=2, fontsize=7); axs[0].set_title(f"{sc}: pair 1 replica and CPU timeline")
        axs[1].axhline(75, color="gray", ls="--", lw=.8); axs[1].set_ylabel("CPU % of requests"); axs[1].set_xlabel("seconds since workload start")
        fig.tight_layout(); p = FIG / f"timeline_{sc}.png"; fig.savefig(p, dpi=160); plt.close(fig); figs["tl_" + sc] = p

    # ---- Word report ----
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10.5)
    H = lambda t, l=1: doc.add_heading(t, l)
    def P(t, b=False):
        p = doc.add_paragraph(); r = p.add_run(t); r.bold = b
    def table(head, rows):
        tb = doc.add_table(rows=1, cols=len(head)); tb.style = "Light Grid Accent 1"
        for i, h in enumerate(head):
            tb.rows[0].cells[i].text = h
        for row in rows:
            c = tb.add_row().cells
            for i, v in enumerate(row): c[i].text = str(v)
        for row in tb.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    for r_ in p.runs: r_.font.size = Pt(8)
        doc.add_paragraph()
    def pic(p, w=5.8):
        doc.add_picture(str(p), width=Inches(w)); doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_heading("KubePilot (PRAH) vs Native Kubernetes HPA — Experimental Evaluation Report", 0)
    P(f"Host: {platform.system()} {platform.release()}, Python {platform.python_version()}. All values are observations from live trials; none are estimated, simulated or forecast; no ML is used.")
    H("1. Executive summary")
    P(f"{len(S)} valid and {len(invalid)} excluded randomized trials ({', '.join(f'{sc}: HPA {len(by[(sc,'HPA')])}/KubePilot {len(by[(sc,'KubePilot')])}' for sc in present)}).")
    H("1.1 Nine-metric comparison (valid trials pooled; mean of per-trial values)")
    nrows = []
    for k, lab, u in METRICS:
        hv = [r[k] for r in S if r["system"] == "HPA" and r.get(k) is not None]
        kv = [r[k] for r in S if r["system"] == "KubePilot" and r.get(k) is not None]
        h, kp = (np.mean(hv) if hv else None), (np.mean(kv) if kv else None)
        if h is None or kp is None:
            diff = pct = NM + " (not calculated)"
            status = NM if (h is None and kp is None) else f"PARTIAL – {'HPA' if h is None else 'KubePilot'} {NM}"
        else:
            diff = f"{kp - h:+.2f} {u}"
            if h == 0:
                pct = "n/a (HPA = 0)"
            else:
                pc = (kp - h) / h * 100
                tag = "" if k not in LOWER | HIGHER else (" (improvement)" if ((kp < h) if k in LOWER else (kp > h)) else " (no improvement)")
                pct = f"{pc:+.1f} %{tag}"
            status = "MEASURED"
        nrows.append([lab, u, f"{h:.2f}" if h is not None else NM, f"{kp:.2f}" if kp is not None else NM, diff, pct,
                      f"HPA {len(hv)} / KP {len(kv)}", status, EVID[k]])
    table(["Metric", "Unit", "Native HPA", "KubePilot", "Difference (KP−HPA)", "% change", "Valid obs. (trials)", "Status", "Evidence"], nrows)
    P("Metric 1 (decision latency) is NOT MEASURED for Native HPA: the decision runs inside kube-controller-manager and exposes no decision timestamp; measuring it would need instrumentation or a patched controller manager. No improvement is calculated for it. The observable proxy (load onset to first scale-out) is in Section 4.1.")
    H("1.2 Trial accounting (valid / failed / excluded)")
    acc = [[t["summary"]["scenario"], t["summary"]["system"], t["summary"]["trial"], "VALID" if t["summary"]["telemetry_valid"] else "EXCLUDED (invalid telemetry/connection)"]
           for t in sorted(ALL, key=lambda x: (x["summary"]["scenario"], x["summary"]["trial"], x["summary"]["system"]))]
    table(["Profile", "System", "Pair", "Classification"], acc)
    P("A first execution (experimental_evaluation/invalid_run1_executor_disconnected) was excluded in full: the Kubernetes executor connection had failed, so replica observations were invalid. It is kept for transparency and used in no statistic. Trials stopped by the runner's safeguards are not reported as results.")
    H("1.3 Randomised workload design and reproducibility")
    pl = json.load(open(EV / "run_plan.json", encoding="utf-8"))
    P(f"Master seed {pl['seed']} (numpy default_rng). It determines the execution order of profile×pair items, which system runs first within each pair, and workload intensities (worker counts/change times drawn from rng([seed, profile_index, pair])). Both systems in a pair get the identical schedule. Random numbers choose the workload only; every reported value is an observation.")
    table(["Pair", "Profile", "Schedule (start s, end s, workers)", "System order"],
          [[i["pair"], i["profile"]["name"], str(i["profile"]["schedule"]), " → ".join(i["system_order"])] for i in pl["plan"]])
    H("1.4 Cloud cost and resources")
    cp = EV / "cost_summary.txt"
    P(cp.read_text(encoding="utf-8") if cp.exists() else "cost_summary.txt missing")
    H("2. Experimental setup and methodology")
    for t in [
        "Platform: existing single-node Minikube cluster (Docker driver, 12 vCPU / ~7.8 GiB allocatable), Kubernetes v1.35, Prometheus v2.51 (5 s scrape; cAdvisor + application metrics), metrics-server for the HPA.",
        "Application: sample-web-app (Flask), requests 100m CPU / 128Mi, limits 500m CPU / 256Mi; initial replicas 2; limits min 2 / max 10 for both systems; same node, image and configuration.",
        "Native HPA: autoscaling/v2, CPU averageUtilization 75 % (k8s/baseline-hpa.yaml), default Kubernetes behaviour (15 s sync, 300 s scale-down stabilisation).",
        "KubePilot (PRAH): deterministic policy-driven reactive arbitration (policies/scaling-policies.yaml): CPU>75 % (+1), CPU>=90 % (+2), scale-in CPU<25 % (-1); 10 s evaluation interval; guardrails 2..10, +2/-1 step, 60 s cooldown, 5 % hysteresis; live execution through the scale subresource with readiness verification. Telemetry is Prometheus rate()[1m] CPU relative to requests.",
        "Ownership: exactly one controller owns the Deployment per trial. HPA trial: HPA applied, KubePilot never cycled, live execution off. KubePilot trial: HPA deleted and verified absent, live execution on. The in-cluster KubePilot controller runs in dry-run and never mutates replicas. Presence/absence is stored per trial (ownership). The runner aborts on ownership violation, Prometheus unreachability, executor disconnection or telemetry coverage < 80 %.",
        "Load: an in-cluster pod (kp-loadgen) calls the ClusterIP service so requests balance across all ready pods. Workers issue CPU-burn requests (/load?duration=0.05, about 0.1 core per worker) and light probe requests. A request FAILS on timeout (5 s), exception or non-200.",
        "Profiles: low, moderate, sudden spike, sustained high, reduction and recovery, variable (30 s random levels). Durations 240 s (360 s for reduction/recovery). Same duration, monitoring interval (1 s) and workload for both systems.",
        "Trial hygiene: before each trial the HPA is removed, replicas reset to 2 and awaited ready, and Prometheus CPU must be below 20 %.",
    ]:
        doc.add_paragraph(t, style="List Bullet")
    H("3. Metric definitions and formulas")
    table(["Metric", "Definition / formula"], [
        ("1. Scaling decision latency (ms)", "KubePilot: wall time of telemetry collection plus PRAH decision per evaluation cycle, L = t_decision_out − t_cycle_start (instrumented by wrapping existing functions). Native HPA: NOT MEASURED."),
        ("2. Scaling execution time (s)", "For every change of desired replicas at t_e to N: T_exec = t_ready − t_e, t_ready = first 1 s sample with ready ≥ N (scale-out) or ≤ N (scale-in). Same observer for both (±1 s)."),
        ("3. Average response time (ms)", "R = (1/n) Σ (t_end − t_start) over successful client requests."),
        ("4. Throughput (req/s)", "X = N_success / D."),
        ("5. Application error rate (%)", "E = 100 · N_failed / N_total (timeout, exception or HTTP ≠ 200)."),
        ("6. CPU utilisation (%)", "Mean of Σ rate(container_cpu_usage_seconds_total[1m]) / (N_pods · 0.1 core) · 100 from Prometheus."),
        ("7. Memory utilisation (%)", "Mean of Σ container_memory_working_set_bytes / Σ container_spec_memory_limit_bytes · 100."),
        ("8. Direction reversals (count)", "Σ [d_i ≠ d_(i+1)] over signs of consecutive desired-replica changes."),
        ("9. Execution verification success (%)", "100 · events reaching ready == desired within 120 s / total events (external observer, both systems)."),
    ])
    P("The project's code base defines no separate numeric specification of these nine metrics beyond the existing runner fields (response time, readiness time, throughput, error rate, CPU/memory, scale-in latency); the definitions above follow the nine metrics requested for this evaluation.")
    H("4. Results per profile (mean ± SD over pairs)")
    table(["Profile", "Metric", "Unit", "Native HPA", "KubePilot"],
          [[sc, lab, u, fmt(agg.get(f"{sc}|HPA", {}).get(k)), fmt(agg.get(f"{sc}|KubePilot", {}).get(k))] for sc in present for k, lab, u in METRICS])
    H("4.1 Statistical summaries and consistency")
    srows = []
    for sc in present:
        for sy in SYS:
            a = agg.get(f"{sc}|{sy}")
            if not a: continue
            for k, lab, u in METRICS + EXTRA:
                s = a[k]
                srows.append([sc, sy, lab, "NOT MEASURED" if s is None else s["n"]] + (["–"] * 6 if s is None else
                              [f"{s['mean']:.2f}", f"{s['median']:.2f}", f"{s['std']:.2f}", f"{s['min']:.2f}", f"{s['max']:.2f}", "–" if s["cv_pct"] is None else f"{s['cv_pct']:.0f}%"]))
    table(["Profile", "System", "Metric", "n", "Mean", "Median", "SD", "Min", "Max", "CV"], srows)
    P("Pooled per-request latency percentiles (successful requests):", True)
    table(["Profile", "System", "Requests", "p50 ms", "p90 ms", "p95 ms", "p99 ms"],
          [[sc, sy, a["pooled_latency_ms"]["n"], *(f"{a['pooled_latency_ms'][p]:.1f}" for p in ("p50", "p90", "p95", "p99"))]
           for sc in present for sy in SYS if (a := agg.get(f"{sc}|{sy}")) and a["pooled_latency_ms"]])
    H("5. Graphs")
    for k, lab, u in METRICS:
        pic(figs[k])
    for sc in present:
        pic(figs["tl_" + sc])
    H("6. Interpretation and conclusion")
    ip = EV / "interpretation.txt"
    for para in (ip.read_text(encoding="utf-8").split("\n\n") if ip.exists() else ["(interpretation pending)"]):
        doc.add_paragraph(para.strip())
    H("7. Limitations and unmeasured metrics")
    for t in [
        "Metric 1 (decision latency) is NOT MEASURED for Native HPA (internal to kube-controller-manager; no timestamp is exposed). Missing: instrumentation of the controller manager.",
        "No cloud infrastructure was used (see 1.4): single-node local Minikube on a Windows/WSL2 host; absolute numbers are specific to it and to the synthetic CPU-burn workload.",
        "Only two pairs per profile were run to limit time; standard deviations are indicative and no significance claims are made.",
        "1 s observer resolution (±1 s) for execution and reaction times; load clock starts when the host receives the READY line (±0.2 s).",
        "The systems use different telemetry paths by design (HPA: metrics-server; KubePilot: Prometheus rate()[1m], 5 s scrape) and different control parameters (HPA proportional with 300 s scale-down stabilisation; KubePilot step rules with 60 s cooldown). The comparison is of the systems as configured, not tuned equivalents.",
        "The Flask development server and fixed-duration burn requests make response time weakly sensitive to replica count.",
        "Events completing after the trial window are not counted; scale-in is only observable if it occurs inside the window.",
    ]:
        doc.add_paragraph(t, style="List Bullet")
    H("8. Data")
    P("Raw per-trial JSON/CSV (1 s replica/CPU/memory samples, every request, scaling events, KubePilot execution logs, seeds): experimental_evaluation/raw. Plan and seed: experimental_evaluation/run_plan.json. Datasets: experimental_evaluation/datasets. Figures: experimental_evaluation/figures. See EXPERIMENT_REPRODUCIBILITY_GUIDE.md.")
    doc.save(ROOT / "KUBEPILOT_EXPERIMENTAL_EVALUATION_REPORT.docx")
    print("report written; valid:", len(S), "excluded:", len(invalid))


if __name__ == "__main__":
    main()
