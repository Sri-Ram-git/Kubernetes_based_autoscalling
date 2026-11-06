"""In-cluster load generator (stdlib only). Records every request: (t_rel_s, latency_ms, ok, status_code).
A request is FAILED if it raises/timeouts (5 s) or returns non-200."""
import json, sys, threading, time, urllib.request

spec = json.loads(sys.argv[1]); base = spec["base"]; T0 = spec["start_at"]
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
            recs.append((round(t0 - T0, 3), round(lat, 2), ok, code))
        time.sleep(ph["sleep"])

ths = [threading.Thread(target=worker, args=(p,), daemon=True) for p in spec["phases"]]
[t.start() for t in ths]; [t.join() for t in ths]
print("RESULT:" + json.dumps({"start_at": T0, "requests": recs}))
