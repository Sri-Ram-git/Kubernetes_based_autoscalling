"""
Final instrumented experiment runner: Native HPA vs KubePilot (PRAH).

- Load is generated INSIDE the cluster (pod `kp-loadgen`, same image as the app) and hits the
  Service, so kube-proxy balances connections across replicas (a host `kubectl port-forward`
  pins traffic to a single pod, which would invalidate scale-out comparisons).
- One scaling owner at a time: HPA trials delete nothing but run KubePilot in dry-run; KubePilot
  trials delete the HPA first. The in-cluster controller is DRY_RUN=true (verified).
- Raw per-trial evidence -> experiments/final/raw/<scenario>_<controller>_t<N>.json (resumable).
Usage: python scripts/run_final_experiments.py [--trials 5] [--scenarios S1,S2,...]
"""
import argparse, json, logging, subprocess, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from controller.main import AutoscalingController  # noqa: E402
from kubernetes import client  # noqa: E402

logging.basicConfig(level=logging.WARNING)
NS, DEP = "autoscaling-demo", "sample-web-app"
RAW = ROOT / "experiments" / "final" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
PROM = "http://localhost:9090"
CPU_REQ, MEM_REQ = 0.1, 128 * 1024 * 1024
BASE = f"http://{DEP}.{NS}.svc.cluster.local:8080"
LOADGEN_SRC = ROOT / "scripts" / "loadgen_incluster.py"
HPA_YAML = ROOT / "k8s" / "baseline-hpa.yaml"

# Q: identical for both controllers (request-based, pod-level cAdvisor series; no fallbacks).
Q_CPU = (f'sum(rate(container_cpu_usage_seconds_total{{namespace="{NS}",pod=~"{DEP}-.*"}}[1m]))'
         f'/(count(count by (pod)(container_cpu_usage_seconds_total{{namespace="{NS}",pod=~"{DEP}-.*"}}))*{CPU_REQ})*100')
Q_MEM = (f'sum(container_memory_working_set_bytes{{namespace="{NS}",pod=~"{DEP}-.*"}})'
         f'/(count(container_memory_working_set_bytes{{namespace="{NS}",pod=~"{DEP}-.*"}})*{MEM_REQ})*100')

NOM = lambda D: [dict(start=0, end=D, path="/?format=json", sleep=0.1)]
def heavy(s, e, n, load=0.25, sl=0.02):
    return [dict(start=s, end=e, path=f"/load?duration={load}", sleep=sl) for _ in range(n)]

SCEN = {  # id: (name, duration_s, phases)
    "S1": ("stable_workload", 60, NOM(60)),
    "S2": ("gradual_increase", 120, NOM(120) + heavy(10, 120, 1, .2) + heavy(30, 120, 1, .2)
            + heavy(50, 120, 2, .2) + heavy(70, 120, 2, .2)),
    "S3": ("sudden_cpu_spike", 100, NOM(100) + heavy(15, 85, 8)),
    "S4": ("bursty_workload", 110, NOM(110) + heavy(10, 25, 6, .2, .03) + heavy(50, 65, 6, .2, .03)
            + heavy(85, 100, 6, .2, .03)),
    "S5": ("sudden_decrease", 150, NOM(150) + heavy(0, 40, 8)),
}

def sh(cmd, check=False):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def prom(q):
    try:
        r = requests.get(f"{PROM}/api/v1/query", params={"query": q}, timeout=3).json()
        res = r["data"]["result"]
        if r["status"] == "success" and res:
            return float(res[0]["value"][1]), float(res[0]["value"][0])
    except Exception:
        pass
    return None, None  # missing -> None, never zero

class Runner:
    def __init__(self):
        self.c = AutoscalingController()
        self.c.set_live_execution(False)
        self.core = self.c.executor._core_v1_api
        self.asc = client.AutoscalingV2Api(self.c.executor._apps_v1_api.api_client)
        self.ev = []          # instrumentation events
        self._wrap()

    def _wrap(self):
        c, ev = self.c, self.ev
        f_tel, f_dec, f_ex = c.fetch_current_telemetry, c.decision_controller.compute_decision, c.executor.execute_scaling
        def tel(*a, **k):
            ev.append(dict(k="eval_start", t=time.time())); return f_tel(*a, **k)
        def dec(*a, **k):
            r = f_dec(*a, **k)
            ev.append(dict(k="decision", t=time.time(), action=r.action, target=r.target_replicas,
                           policy=r.selected_policy_id)); return r
        def ex(action, target_replicas, dry_run=True):
            t0 = time.time(); r = f_ex(action, target_replicas, dry_run); t1 = time.time()
            ev.append(dict(k="exec", t_req=t0, t_end=t1, action=action, target=target_replicas, dry_run=dry_run,
                           success=r.success, initial=r.initial_replicas, confirmed=r.confirmed_replicas,
                           error=r.error, message=r.message, exec_ms=r.execution_duration_ms)); return r
        c.fetch_current_telemetry, c.decision_controller.compute_decision, c.executor.execute_scaling = tel, dec, ex

    def pods(self):
        out = {}
        for p in self.core.list_namespaced_pod(NS).items:
            if not p.metadata.name.startswith(DEP + "-"): continue
            ready = None
            for cd in (p.status.conditions or []):
                if cd.type == "Ready" and cd.status == "True": ready = cd.last_transition_time.timestamp()
            out[p.metadata.name] = dict(created=p.metadata.creation_timestamp.timestamp(), ready=ready,
                                        terminating=p.metadata.deletion_timestamp is not None)
        return out

    def reset(self):
        sh("kubectl delete pod kp-loadgen -n %s --ignore-not-found=true --wait=true" % NS)
        sh(f"kubectl delete hpa {DEP} -n {NS} --ignore-not-found=true")
        self.c.set_live_execution(False)
        self.c.decision_controller.reset_cooldown()
        sh(f"kubectl scale deployment {DEP} -n {NS} --replicas=2")
        for _ in range(90):
            s = self.c.executor.get_workload_state()
            pods = [p for p in self.pods().values() if not p["terminating"]]
            if s.desired_replicas == 2 and s.ready_replicas == 2 and len(pods) == 2: break
            time.sleep(2)
        else:
            raise RuntimeError("reset: replicas did not settle at 2")
        for _ in range(60):  # telemetry settle: CPU < 20 %
            v, _t = prom(Q_CPU)
            if v is not None and v < 20: break
            time.sleep(2)
        time.sleep(20)  # let the 1m rate window decay
        return dict(cpu_after_settle=prom(Q_CPU)[0], mem_after_settle=prom(Q_MEM)[0])

    def trial(self, sid, system, n, duration_override=None):
        name, D, phases = SCEN[sid]
        out = RAW / f"{sid}_{name}_{system}_t{n}.json"
        if out.exists():
            print("skip existing", out.name); return
        rec = dict(experiment_id=f"{sid}-{system}-t{n}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}", scenario=sid,
                   scenario_name=name, controller=system, trial=n, duration_s=D, status="RUNNING", errors=[])
        try:
            rec["settle"] = self.reset()
            if system == "HPA":
                sh(f"kubectl apply -f {HPA_YAML}")
            self.ev.clear()
            spec = dict(base=BASE, start_at=time.time() + 15, duration=D, phases=phases)
            rec["config"] = dict(min_replicas=2, max_replicas=10, initial_replicas=2, cpu_request_m=100,
                                 mem_request_Mi=128, hpa_target_cpu_pct=75 if system == "HPA" else None,
                                 kubepilot_interval_s=self.c.config.evaluation_interval_seconds,
                                 kubepilot_cooldown_s=self.c.config.cooldown_seconds, phases=phases)
            t_start = spec["start_at"]
            if system == "KubePilot":
                self.c.decision_controller.reset_cooldown(); self.c.set_live_execution(True)
            self._launch_loadgen(spec)
            polls, samples, pods_seen, hpa_log = [], [], {}, []
            stop = threading.Event()
            def kp_loop():
                nxt = t_start
                while not stop.is_set():
                    if time.time() >= nxt:
                        try: self.c.run_single_cycle()
                        except Exception as e: rec["errors"].append(f"cycle: {e!r}")
                        nxt += self.c.config.evaluation_interval_seconds
                    time.sleep(0.2)
            th = None
            if system == "KubePilot":
                th = threading.Thread(target=kp_loop, daemon=True); th.start()
            end = t_start + D + 25  # 25 s tail to observe readiness/last scaling
            lastp = 0
            while time.time() < end:
                now = time.time()
                try:
                    s = self.c.executor.get_workload_state()
                    for k, v in self.pods().items(): pods_seen.setdefault(k, {}).update(v)
                    rowp = dict(t=now, desired=s.desired_replicas, current=s.current_replicas, ready=s.ready_replicas)
                    if system == "HPA":
                        try:
                            h = self.asc.read_namespaced_horizontal_pod_autoscaler(DEP, NS)
                            rowp["hpa_last_scale"] = h.status.last_scale_time.timestamp() if h.status.last_scale_time else None
                            rowp["hpa_desired"] = h.status.desired_replicas
                        except Exception: pass
                    polls.append(rowp)
                except Exception as e:
                    rec["errors"].append(f"poll: {e!r}")
                if now - lastp >= 5:
                    lastp = now
                    cv, ct = prom(Q_CPU); mv, mt = prom(Q_MEM)
                    samples.append(dict(t=now, cpu_pct=cv, cpu_prom_ts=ct, mem_pct=mv, mem_prom_ts=mt))
                time.sleep(1)
            stop.set()
            if th: th.join(timeout=20)
            self.c.set_live_execution(False)
            rec["loadgen"] = self._collect_loadgen(t_start, D)
            rec.update(t_start=t_start, t_end=t_start + D, polls=polls, samples=samples, pods=pods_seen,
                       events=list(self.ev), final=dict(zip(("desired", "ready"), (polls[-1]["desired"], polls[-1]["ready"]))))
            rec["status"] = "COMPLETE"
        except Exception as e:
            rec["status"] = "FAILED"; rec["errors"].append(repr(e))
            self.c.set_live_execution(False)
        finally:
            sh("kubectl delete pod kp-loadgen -n %s --ignore-not-found=true --wait=false" % NS)
            out.write_text(json.dumps(rec, indent=1, default=str))
            print(rec["experiment_id"], rec["status"], rec["errors"][:2], flush=True)

    def _launch_loadgen(self, spec):
        sh(f'kubectl create configmap kp-loadgen-src -n {NS} --from-file=loadgen.py="{LOADGEN_SRC}" --dry-run=client -o yaml | kubectl apply -f -')
        pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "kp-loadgen", "namespace": NS, "labels": {"app": "kp-loadgen"}},
               "spec": {"restartPolicy": "Never", "containers": [{"name": "lg", "image": "sample-web-app:latest",
                        "imagePullPolicy": "Never", "command": ["python", "/src/loadgen.py", json.dumps(spec)],
                        "resources": {"requests": {"cpu": "50m", "memory": "64Mi"}},
                        "volumeMounts": [{"name": "src", "mountPath": "/src"}]}],
                        "volumes": [{"name": "src", "configMap": {"name": "kp-loadgen-src"}}]}}
        r = subprocess.run("kubectl apply -f -", shell=True, input=json.dumps(pod), capture_output=True, text=True)
        if r.returncode: raise RuntimeError("loadgen launch: " + r.stderr)

    def _collect_loadgen(self, t_start, D):
        for _ in range(120):
            lg = sh(f"kubectl logs kp-loadgen -n {NS}").stdout
            if "RESULT:" in lg:
                return json.loads(lg.split("RESULT:")[-1].strip().splitlines()[0])
            time.sleep(2)
        raise RuntimeError("loadgen produced no RESULT")

    # ---------- functional (injected-telemetry, dry-run) scenarios ----------
    def functional(self, n):
        out = RAW / f"S67_functional_KubePilot_t{n}.json"
        if out.exists(): return
        self.c.set_live_execution(False)
        cases = {
            "S6_conflict_cpu95_mem10": dict(cpu_utilization_percent=95.0, memory_utilization_percent=10.0, http_requests_per_second=1.0),
            "S6_conflict_cpu80_mem10": dict(cpu_utilization_percent=80.0, memory_utilization_percent=10.0, http_requests_per_second=1.0),
            "S7_step_limit_cpu95": dict(cpu_utilization_percent=95.0, memory_utilization_percent=50.0, http_requests_per_second=1.0),
            "S7_min_bound_cpu5": dict(cpu_utilization_percent=5.0, memory_utilization_percent=5.0, http_requests_per_second=0.0),
            "S7_missing_cpu_HOLD": dict(cpu_utilization_percent=dict(value=None, status="MISSING"), memory_utilization_percent=50.0, http_requests_per_second=1.0),
        }
        res = {}
        for k, fm in cases.items():
            self.c.decision_controller.reset_cooldown(); self.ev.clear()
            r1 = self.c.run_single_cycle(forced_metrics=fm)   # cycle 1 starts sustained-duration timers
            time.sleep(6.5)                                    # policies need duration_seconds=5 sustained
            self.c.decision_controller.reset_cooldown()
            r = self.c.run_single_cycle(forced_metrics=fm)
            res[k] = dict(forced_metrics=fm, log_cycle1=r1, log=r, events=list(self.ev))
        out.write_text(json.dumps(dict(kind="FUNCTIONAL_INJECTED_TELEMETRY_DRY_RUN", trial=n, cases=res), indent=1, default=str))
        print("functional", n, "done", flush=True)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--scenarios", default="S1,S2,S3,S4,S5")
    ap.add_argument("--functional", action="store_true")
    a = ap.parse_args()
    r = Runner()
    if a.functional:
        for n in range(1, a.trials + 1): r.functional(n)
        sys.exit(0)
    for n in range(1, a.trials + 1):          # trial-major so every scenario gets equal trials if stopped early
        for sid in a.scenarios.split(","):
            order = ["HPA", "KubePilot"] if n % 2 else ["KubePilot", "HPA"]  # alternate order
            for sysname in order: r.trial(sid, sysname, n)
