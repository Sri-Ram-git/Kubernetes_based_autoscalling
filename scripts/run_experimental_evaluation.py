"""
KubePilot (PRAH) vs Native Kubernetes HPA - controlled experimental evaluation runner.

Design (reuses controller.* modules unchanged; no ML/forecasting, no simulated values):
  * Identical workload app (sample-web-app), initial replicas (2), limits (min 2 / max 10), CPU target 75%.
  * Load is generated INSIDE the cluster (pod 'kp-loadgen' -> ClusterIP service) so kube-proxy balances
    requests over all ready pods (a host port-forward would pin traffic to one pod).
  * Exactly one controller owns the Deployment per trial:
      HPA trial       : HPA applied, KubePilot never cycled, live execution disabled.
      KubePilot trial : HPA deleted + verified absent, KubePilot live execution enabled.
  * Between trials: HPA removed, scale to 2, wait ready, wait for Prometheus CPU < 20 %.
  * Every raw sample / request / event is written to experimental_evaluation/raw/.
Usage: python scripts/run_experimental_evaluation.py --scenarios spike --trials 1 [--systems HPA KubePilot]
"""
import argparse, csv, json, logging, subprocess, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from controller.main import AutoscalingController
from controller.telemetry import build_metric_queries

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("evalrun")
OUT = ROOT / "experimental_evaluation"
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)
NS, DEP = "autoscaling-demo", "sample-web-app"
POD = "kp-loadgen"
BASE = "http://sample-web-app.autoscaling-demo.svc:8080"
HPA_YAML = ROOT / "k8s" / "baseline-hpa.yaml"
CTRL_INTERVAL = 10.0       # KubePilot evaluation interval (same as deployed manifest)
EXEC_TIMEOUT = 120.0       # max seconds for ready==desired to count a scaling event as verified

LIGHT = {"path": "/?format=json", "sleep": 0.25, "kind": "light"}


def burn(start, end):
    return {"path": "/load?duration=0.05", "sleep": 0.45, "kind": "burn", "start": start, "end": end}


def make_profile(name, rng):
    """Randomised (seeded) piecewise workload. Level = number of burn workers (~0.1 core each)."""
    r = lambda lo, hi: int(rng.integers(lo, hi + 1))
    if name == "low":
        sched, dur = [(0, 240, r(1, 2))], 240
    elif name == "moderate":
        sched, dur = [(0, 240, r(3, 4))], 240
    elif name == "spike":
        t = r(20, 40); sched, dur = [(0, t, 1), (t, 240, r(6, 8))], 240
    elif name == "sustained_high":
        sched, dur = [(0, 240, r(6, 8))], 240
    elif name == "reduction_recovery":
        hi = r(6, 8); a_ = r(80, 100); b_ = a_ + r(100, 140)
        sched, dur = [(0, a_, hi), (a_, b_, 1), (b_, 360, hi)], 360
    elif name == "variable":
        sched, dur = [(i * 30, (i + 1) * 30, r(1, 8)) for i in range(8)], 240
    else:
        raise ValueError(name)
    lv0 = sched[0][2]
    onset = next((t0 for t0, t1, w in sched if w > lv0), None)
    drop = next((t0 for (t0, t1, w), (u0, u1, v) in zip(sched, sched[1:]) if v < w), None)
    return {"name": name, "dur": dur, "schedule": sched, "onset": onset, "drop_t": drop}


def build_phases(prof):
    dur, sched = prof["dur"], prof["schedule"]
    ph = [dict(LIGHT, start=0, end=dur)]
    for j in range(max(w for _, _, w in sched)):
        seg = [[t0, t1] for t0, t1, w in sched if w > j]
        merged = []
        for t0, t1 in seg:
            if merged and merged[-1][1] == t0: merged[-1][1] = t1
            else: merged.append([t0, t1])
        ph += [burn(t0, t1) for t0, t1 in merged]
    return ph


PROFILES = ["low", "moderate", "spike", "sustained_high", "reduction_recovery", "variable"]


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


class Rig:
    def __init__(self):
        self.c = AutoscalingController()
        self.c.set_live_execution(False)
        self.q = build_metric_queries(NS, DEP, pod_cpu_request_cores=0.100)
        self.dec_ms, self.cycle_ms, self.execs = [], [], []
        dc = self.c.decision_controller
        orig_dec = dc.compute_decision
        orig_fetch = self.c.fetch_current_telemetry
        orig_exec = self.c.executor.execute_scaling
        self._tele = 0.0
        def fetch(*a, **k):
            t = time.perf_counter(); r = orig_fetch(*a, **k); self._tele = (time.perf_counter() - t) * 1000; return r
        def dec(*a, **k):
            t = time.perf_counter(); r = orig_dec(*a, **k)
            self.dec_ms.append(self._tele + (time.perf_counter() - t) * 1000); return r
        def ex(*a, **k):
            t = time.time(); r = orig_exec(*a, **k)
            if not r.dry_run and r.action_type != "HOLD":
                self.execs.append({"t_start": t, "t_end": time.time(), **r.to_dict()})
            return r
        dc.compute_decision = dec
        self.c.fetch_current_telemetry = fetch
        self.c.executor.execute_scaling = ex
        # strategy_coordinator holds its own executor reference to the same object -> wrapped attribute is shared

    def prom(self, name):
        s = self.c.prometheus_provider.query_instant(self.q[name], name)
        return s.value if (s.is_usable() and s.value is not None) else None

    def state(self):
        return self.c.executor.get_workload_state()

    def hpa_present(self):
        return bool(sh(f"kubectl get hpa -n {NS} -o name").stdout.strip())

    def reset(self):
        self.c.set_live_execution(False)
        sh(f"kubectl delete hpa {DEP} -n {NS} --ignore-not-found=true")
        sh(f"kubectl scale deployment {DEP} -n {NS} --replicas=2")
        t_end = time.time() + 180
        while time.time() < t_end:
            st = self.state()
            if st.desired_replicas == 2 and st.ready_replicas == 2 and len(st.pods) == 2:
                break
            time.sleep(1)
        t_end = time.time() + 240
        while time.time() < t_end:
            v = self.prom("cpu_utilization_percent")
            if v is not None and v < 20.0:
                break
            time.sleep(2)
        self.c.decision_controller.reset_cooldown()
        time.sleep(10)


def start_loadgen(spec):
    p = subprocess.Popen(["kubectl", "exec", "-i", "-n", NS, POD, "--", "python", "-u", "/tmp/lg.py"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    p.stdin.write(json.dumps(spec) + "\n"); p.stdin.flush()
    line = p.stdout.readline()
    t0 = time.time()
    assert line.startswith("READY"), f"loadgen failed: {line!r}"
    return p, t0


def run_trial(rig, prof, system, n, seed):
    sc, dur, onset = prof['name'], prof['dur'], prof['onset']
    if not rig.c.executor.is_connected()[0]:
        rig.c.executor._initialize_client()
    assert rig.c.executor.is_connected()[0], 'STOP: Kubernetes executor not connected'
    rig.reset()
    ownership = {}
    if system == "HPA":
        sh(f"kubectl apply -f {HPA_YAML}")
        rig.c.set_live_execution(False)
        ownership = {"hpa_present": True, "kubepilot_live": False}
    else:
        assert not rig.hpa_present(), "HPA still present - aborting (ownership violation)"
        rig.c.set_live_execution(True)
        ownership = {"hpa_present": False, "kubepilot_live": True}
    rig.dec_ms.clear(); rig.cycle_ms.clear(); rig.execs.clear()
    init = rig.state().desired_replicas
    spec = {"base": BASE, "phases": build_phases(prof)}
    stop = threading.Event()

    def ctl_loop():
        nxt = time.time()
        while not stop.is_set():
            if time.time() >= nxt:
                t = time.perf_counter()
                try:
                    rig.c.run_single_cycle()
                except Exception as e:
                    log.error("cycle error %s", e)
                rig.cycle_ms.append((time.perf_counter() - t) * 1000)
                nxt += CTRL_INTERVAL
            time.sleep(0.2)

    proc, t0 = start_loadgen(spec)
    th = None
    if system == "KubePilot":
        th = threading.Thread(target=ctl_loop, daemon=True); th.start()
    samples = []
    while True:
        now = time.time()
        if now - t0 >= dur:
            break
        st = rig.state()
        samples.append({
            "t": round(now - t0, 2), "iso": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(), "connected": st.connected,
            "desired": st.desired_replicas, "current": st.current_replicas, "ready": st.ready_replicas,
            "cpu_pct": rig.prom("cpu_utilization_percent"), "mem_pct": rig.prom("memory_utilization_percent"),
            "rps_prom": rig.prom("http_requests_per_second"),
        })
        time.sleep(max(0.0, 1.0 - (time.time() - now)))
    stop.set()
    if th: th.join(timeout=30)
    out, _ = proc.communicate(timeout=60)
    res = json.loads([l for l in out.splitlines() if l.startswith("RESULT:")][0][7:])
    reqs = res["requests"]
    final = rig.state().desired_replicas
    hpa_end = rig.hpa_present()
    sh(f"kubectl delete hpa {DEP} -n {NS} --ignore-not-found=true"); rig.c.set_live_execution(False)
    rec = summarize(sc, system, n, dur, onset, init, final, samples, reqs, rig, t0, ownership, hpa_end)
    rec['profile'] = prof; rec['seed'] = seed
    rec['pod_connected_all_samples'] = all(x['connected'] for x in samples)
    rec['telemetry_valid'] = rec['telemetry_valid'] and rec['pod_connected_all_samples']
    save(rec, samples, reqs)
    return rec


def summarize(sc, system, n, dur, onset, init, final, samples, reqs, rig, t0, ownership, hpa_end):
    ok = [r for r in reqs if r[2] == 1]
    lat = np.array([r[1] for r in ok]) if ok else np.array([0.0])
    light = np.array([r[1] for r in ok if r[4] == "light"]) if ok else np.array([0.0])
    events, prev = [], init
    for s in samples:
        if s["desired"] != prev:
            events.append({"t": s["t"], "from": prev, "to": s["desired"], "dir": 1 if s["desired"] > prev else -1})
            prev = s["desired"]
    for e in events:
        tr = None
        for s in samples:
            if s["t"] >= e["t"] and ((e["dir"] > 0 and s["ready"] >= e["to"]) or (e["dir"] < 0 and s["ready"] <= e["to"])):
                tr = s["t"]; break
        e["exec_time_s"] = (tr - e["t"]) if (tr is not None and tr - e["t"] <= EXEC_TIMEOUT) else None
        e["verified"] = e["exec_time_s"] is not None
    dirs = [e["dir"] for e in events]
    reversals = sum(1 for a, b in zip(dirs, dirs[1:]) if a != b)
    exec_times = [e["exec_time_s"] for e in events if e["verified"]]
    cpu = [s["cpu_pct"] for s in samples if s["cpu_pct"] is not None]
    mem = [s["mem_pct"] for s in samples if s["mem_pct"] is not None]
    cov = len(cpu) / max(1, len(samples))
    first_out = next((e for e in events if e["dir"] > 0), None)
    first_in = next((e for e in events if e["dir"] < 0), None)
    ref = onset if onset is not None else 0
    return {
        "scenario": sc, "system": system, "trial": n, "duration_s": dur, "t0_epoch": t0,
        "initial_replicas": init, "final_replicas": final, "peak_replicas": max(s["desired"] for s in samples),
        "ownership": ownership, "hpa_present_at_end": hpa_end,
        "scaling_events": events, "n_events": len(events),
        "telemetry_coverage": round(cov, 3), "telemetry_valid": cov >= 0.8,
        "m1_decision_latency_ms_mean": float(np.mean(rig.dec_ms)) if (system == "KubePilot" and rig.dec_ms) else None,
        "m1_decision_latency_ms_median": float(np.median(rig.dec_ms)) if (system == "KubePilot" and rig.dec_ms) else None,
        "m1_decision_latency_ms_max": float(np.max(rig.dec_ms)) if (system == "KubePilot" and rig.dec_ms) else None,
        "controller_cycles": len(rig.dec_ms) if system == "KubePilot" else None,
        "m2_exec_time_s_mean": float(np.mean(exec_times)) if exec_times else None,
        "m2_exec_time_s_first_out": first_out["exec_time_s"] if first_out else None,
        "m3_resp_ms_mean": float(lat.mean()), "m3_resp_ms_p50": float(np.percentile(lat, 50)),
        "m3_resp_ms_p95": float(np.percentile(lat, 95)), "m3_resp_ms_p99": float(np.percentile(lat, 99)),
        "m3_light_resp_ms_mean": float(light.mean()), "m3_light_resp_ms_p95": float(np.percentile(light, 95)),
        "m4_throughput_rps": len(ok) / dur,
        "m5_error_rate_pct": (len(reqs) - len(ok)) / max(1, len(reqs)) * 100,
        "total_requests": len(reqs), "failed_requests": len(reqs) - len(ok),
        "m6_cpu_pct_mean": float(np.mean(cpu)) if cpu else None, "m6_cpu_pct_peak": float(np.max(cpu)) if cpu else None,
        "m7_mem_pct_mean": float(np.mean(mem)) if mem else None, "m7_mem_pct_peak": float(np.max(mem)) if mem else None,
        "m8_reversals": reversals,
        "m9_verified_events": sum(1 for e in events if e["verified"]), "m9_total_events": len(events),
        "m9_verification_success_pct": (sum(1 for e in events if e["verified"]) / len(events) * 100) if events else None,
        "kp_internal_executions": list(rig.execs) if system == "KubePilot" else None,
        "kp_internal_verified": (sum(1 for x in rig.execs if x["success"]), len(rig.execs)) if system == "KubePilot" else None,
        "reaction_s_first_out": (first_out["t"] - ref) if first_out else None,
        "scalein_s_first_in": None,
        "load_onset_s": onset,
    }


def save(rec, samples, reqs):
    base = f"{rec['scenario']}_p{rec['trial']}_{rec['system']}"
    with open(RAW / f"{base}.json", "w") as f:
        json.dump({"summary": rec, "samples": samples, "requests_fields": ["t_rel_s", "latency_ms", "ok", "status", "kind"], "requests": reqs}, f)
    with open(RAW / f"{base}_samples.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(samples[0].keys())); w.writeheader(); w.writerows(samples)
    with open(RAW / f"{base}_requests.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["t_rel_s", "latency_ms", "ok", "status", "kind"]); w.writerows(reqs)


def ensure_loadgen_pod():
    if "Running" not in sh(f"kubectl get pod {POD} -n {NS} -o jsonpath={{.status.phase}}").stdout:
        manifest = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": POD, "namespace": NS, "labels": {"app": "kp-loadgen"}},
                    "spec": {"restartPolicy": "Never", "containers": [{"name": "lg", "image": "sample-web-app:latest",
                             "imagePullPolicy": "Never", "command": ["sleep", "86400"]}]}}
        subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(manifest), text=True, capture_output=True)
        sh(f"kubectl wait --for=condition=Ready pod/{POD} -n {NS} --timeout=90s")
    src = (ROOT / "scripts" / "lg_pod.py").read_text(encoding="utf-8")
    r = subprocess.run(["kubectl", "exec", "-i", "-n", NS, POD, "--", "sh", "-c", "cat > /tmp/lg.py"],
                       input=src, text=True, capture_output=True)
    assert r.returncode == 0, r.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=357)
    ap.add_argument("--pairs", type=int, default=2)
    a = ap.parse_args()
    ensure_loadgen_pod()
    rig = Rig()
    ok, msg = rig.c.prometheus_provider.check_connection()
    if not ok:
        sys.exit(f"STOP: Prometheus not reachable: {msg}")
    master = np.random.default_rng(a.seed)
    plan = [(pn, p) for p in range(1, a.pairs + 1) for pn in PROFILES]
    order = list(master.permutation(len(plan)))
    plan = [plan[i] for i in order]
    items = []
    for pn, p in plan:
        prof = make_profile(pn, np.random.default_rng([a.seed, PROFILES.index(pn), p]))
        sysorder = ["HPA", "KubePilot"] if master.random() < 0.5 else ["KubePilot", "HPA"]
        items.append({"profile": prof, "pair": p, "system_order": sysorder})
    json.dump({"seed": a.seed, "pairs": a.pairs, "plan": items}, open(OUT / "run_plan.json", "w"), indent=1)
    for it in items:
        prof, n = it["profile"], it["pair"]
        for system in it["system_order"]:
            if (RAW / f"{prof['name']}_p{n}_{system}.json").exists():
                continue
            t = time.time()
            r = run_trial(rig, prof, system, n, a.seed)
            print(f"[{datetime.now():%H:%M:%S}] {prof['name']} {system} p{n} sched={prof['schedule']}: peak={r['peak_replicas']} final={r['final_replicas']} "
                  f"events={r['n_events']} rev={r['m8_reversals']} resp={r['m3_resp_ms_mean']:.0f}ms err={r['m5_error_rate_pct']:.1f}% "
                  f"cpu={r['m6_cpu_pct_mean']:.0f} cov={r['telemetry_coverage']} valid={r['telemetry_valid']} ({time.time()-t:.0f}s)", flush=True)
            if not r["telemetry_valid"]:
                # invalid trial: preserve raw data separately, never count it; abort only on repeated failure
                import shutil
                (OUT / "excluded_trials").mkdir(exist_ok=True)
                for f_ in RAW.glob(f"{prof['name']}_p{n}_{system}*"):
                    shutil.move(str(f_), str(OUT / "excluded_trials" / f_.name))
                bad = globals().get("_BAD", 0) + 1; globals()["_BAD"] = bad
                if bad >= 3:
                    sys.exit("STOP: 3 invalid trials - environment unstable")
            else:
                globals()["_BAD"] = 0
    rig.c.set_live_execution(False)
    sh(f"kubectl delete hpa {DEP} -n {NS} --ignore-not-found=true"); sh(f"kubectl scale deployment {DEP} -n {NS} --replicas=2")


if __name__ == "__main__":
    main()
