"""In-pod load generator (stdlib only), executed inside the in-cluster 'kp-loadgen' pod.
Reads a JSON spec from stdin, prints 'READY <epoch>' when the workload clock starts and
'RESULT:<json>' with every request record (t_rel_s, latency_ms, ok, status_code, kind) at the end.
A request FAILS if it raises/times out (5 s) or returns a non-200 status."""
import json, sys, threading, time, urllib.request

spec = json.loads(sys.stdin.readline())
base = spec["base"]
T0 = time.time()
print("READY %.3f" % T0, flush=True)
recs, lock = [], threading.Lock()


def worker(ph):
    while time.time() < T0 + ph["start"]:
        time.sleep(0.01)
    end = T0 + ph["end"]
    while time.time() < end:
        t0 = time.time(); ok = 0; code = -1
        try:
            with urllib.request.urlopen(base + ph["path"], timeout=5) as r:
                r.read(); code = r.status; ok = 1 if code == 200 else 0
        except Exception:
            pass
        lat = (time.time() - t0) * 1000
        with lock:
            recs.append((round(t0 - T0, 3), round(lat, 2), ok, code, ph["kind"]))
        time.sleep(ph["sleep"])


ths = [threading.Thread(target=worker, args=(p,), daemon=True) for p in spec["phases"]]
[t.start() for t in ths]
[t.join() for t in ths]
print("RESULT:" + json.dumps({"t0_pod": T0, "requests": recs}), flush=True)
