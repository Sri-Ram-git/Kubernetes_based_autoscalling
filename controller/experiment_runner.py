"""
Automated Experimentation Engine for Kubernetes Auto-Scaling Framework (Project 357).
Alliance University, Bengaluru.

Implements exactly TWO experiments based on the Experimentation Specification:
1. Stable Workload: Steady, constant request rate comparing Baseline HPA vs Proposed KubePilot.
2. Sudden Traffic Spike: Rapid demand surge comparing scale-out responsiveness and stability.

Strict safety & reproducibility guarantees:
- Non-overlapping execution with mutual exclusion locks.
- Real observations from Prometheus and Kubernetes (no fabricated data).
- Clean teardown: baseline HPA deletion and dry-run safety restoration in all exit paths.
"""

import csv
import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests

logger = logging.getLogger("autoscaler.experiments")

RESULTS_DIR = Path(__file__).resolve().parent.parent / "experiments" / "results"
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "k8s" / "baseline-hpa.yaml"


@dataclass
class TimeSeriesSample:
    timestamp: float
    iso_timestamp: str
    elapsed_seconds: float
    system: str  # "baseline" or "proposed"
    cpu_utilization_percent: float
    memory_utilization_percent: float
    http_requests_per_second: float
    desired_replicas: int
    current_replicas: int
    ready_replicas: int
    scaling_action: str
    workload_rps_actual: float
    workload_latency_avg_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SystemRunResult:
    system: str  # "baseline" or "proposed"
    duration_seconds: float
    initial_replicas: int
    peak_replicas: int
    final_replicas: int
    scaling_events_count: int
    time_to_first_scale_seconds: Optional[float]
    max_cpu_percent: float
    avg_cpu_percent: float
    max_memory_percent: float
    total_requests_sent: int
    successful_requests: int
    failed_requests: int
    avg_request_latency_ms: float
    samples: List[TimeSeriesSample] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["samples"] = [s if isinstance(s, dict) else s.to_dict() for s in self.samples]
        return d


@dataclass
class ExperimentRun:
    run_id: str
    experiment_id: str  # "stable_workload" or "traffic_spike"
    experiment_name: str
    started_at: str
    finished_at: Optional[str] = None
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, CANCELED
    stage: str = "INITIALIZING"
    progress_percent: int = 0
    error_message: Optional[str] = None
    baseline_result: Optional[SystemRunResult] = None
    proposed_result: Optional[SystemRunResult] = None
    comparison_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "stage": self.stage,
            "progress_percent": self.progress_percent,
            "error_message": self.error_message,
            "baseline_result": self.baseline_result.to_dict() if self.baseline_result else None,
            "proposed_result": self.proposed_result.to_dict() if self.proposed_result else None,
            "comparison_summary": self.comparison_summary,
        }


class WorkloadGenerator:
    """Generates controlled HTTP traffic patterns against the workload target."""

    def __init__(self, target_url: str = "http://localhost:8080"):
        self.target_url = target_url.rstrip("/")
        self._stop_event = threading.Event()
        self._active_threads: List[threading.Thread] = []
        self._lock = threading.Lock()
        self.requests_sent = 0
        self.requests_success = 0
        self.requests_failed = 0
        self.total_latency_seconds = 0.0

    def reset_stats(self):
        with self._lock:
            self.requests_sent = 0
            self.requests_success = 0
            self.requests_failed = 0
            self.total_latency_seconds = 0.0
            self._stop_event.clear()

    def stop(self):
        self._stop_event.set()
        for t in self._active_threads:
            t.join(timeout=1.0)
        self._active_threads.clear()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            avg_lat_ms = (
                round((self.total_latency_seconds / self.requests_sent) * 1000, 2)
                if self.requests_sent > 0
                else 0.0
            )
            return {
                "sent": self.requests_sent,
                "success": self.requests_success,
                "failed": self.requests_failed,
                "avg_latency_ms": avg_lat_ms,
            }

    def run_stable_traffic(self, duration_seconds: float = 20.0, target_rps: int = 10):
        """Runs a constant, steady request rate against the application index."""
        self.reset_stats()
        session = requests.Session()
        interval = 1.0 / max(1, target_rps)
        deadline = time.time() + duration_seconds

        def _worker():
            while time.time() < deadline and not self._stop_event.is_set():
                req_start = time.time()
                try:
                    r = session.get(f"{self.target_url}/?format=json", timeout=2.0)
                    lat = time.time() - req_start
                    with self._lock:
                        self.requests_sent += 1
                        if r.status_code == 200:
                            self.requests_success += 1
                        else:
                            self.requests_failed += 1
                        self.total_latency_seconds += lat
                except Exception:
                    with self._lock:
                        self.requests_sent += 1
                        self.requests_failed += 1

                elapsed_loop = time.time() - req_start
                sleep_time = interval - elapsed_loop
                if sleep_time > 0:
                    time.sleep(sleep_time)

        t = threading.Thread(target=_worker, daemon=True)
        self._active_threads.append(t)
        t.start()

    def run_spike_traffic(
        self,
        duration_seconds: float = 30.0,
        baseline_duration: float = 5.0,
        spike_duration: float = 15.0,
        concurrency: int = 6,
    ):
        """
        Runs a sudden surge workload:
        Phase 1: Baseline nominal requests (baseline_duration).
        Phase 2: Sudden Traffic Spike - high concurrency math computations via /load (spike_duration).
        Phase 3: Load cease / cooldown observation (remaining time).
        """
        self.reset_stats()
        session = requests.Session()
        start_time = time.time()
        spike_start = start_time + baseline_duration
        spike_end = spike_start + spike_duration
        test_end = start_time + duration_seconds

        def _nominal_worker():
            while time.time() < test_end and not self._stop_event.is_set():
                # Nominal background ping
                req_start = time.time()
                try:
                    r = session.get(f"{self.target_url}/?format=json", timeout=2.0)
                    lat = time.time() - req_start
                    with self._lock:
                        self.requests_sent += 1
                        if r.status_code == 200:
                            self.requests_success += 1
                        else:
                            self.requests_failed += 1
                        self.total_latency_seconds += lat
                except Exception:
                    with self._lock:
                        self.requests_sent += 1
                        self.requests_failed += 1
                time.sleep(0.2)

        def _spike_worker():
            # Wait until spike phase begins
            while time.time() < spike_start and not self._stop_event.is_set():
                time.sleep(0.1)

            # Heavy CPU math burden loop
            while time.time() < spike_end and not self._stop_event.is_set():
                req_start = time.time()
                try:
                    r = session.get(f"{self.target_url}/load?duration=2.5", timeout=5.0)
                    lat = time.time() - req_start
                    with self._lock:
                        self.requests_sent += 1
                        if r.status_code == 200:
                            self.requests_success += 1
                        else:
                            self.requests_failed += 1
                        self.total_latency_seconds += lat
                except Exception:
                    with self._lock:
                        self.requests_sent += 1
                        self.requests_failed += 1
                time.sleep(0.05)

        # Start nominal worker
        t_nom = threading.Thread(target=_nominal_worker, daemon=True)
        self._active_threads.append(t_nom)
        t_nom.start()

        # Start concurrent spike workers
        for _ in range(concurrency):
            t_spk = threading.Thread(target=_spike_worker, daemon=True)
            self._active_threads.append(t_spk)
            t_spk.start()


class ExperimentManager:
    """Orchestrates baseline HPA and proposed KubePilot experiments."""

    EXPERIMENT_SPECS = {
        "stable_workload": {
            "id": "stable_workload",
            "name": "Experiment 1: Stable Workload",
            "description": "Applies a steady, nominal request stream (10 req/s) against sample-web-app. Compares baseline Kubernetes HPA vs KubePilot PRAH framework stability under nominal demand.",
            "duration_seconds": 20.0,
            "target_rps": 10,
        },
        "traffic_spike": {
            "id": "traffic_spike",
            "name": "Experiment 2: Sudden Traffic Spike",
            "description": "Applies a rapid traffic and computational surge to drive CPU >80%. Compares baseline HPA latency vs KubePilot PRAH priority arbitration, scale-out response, and cooldown recovery.",
            "duration_seconds": 30.0,
            "baseline_seconds": 5.0,
            "spike_seconds": 15.0,
            "concurrency": 6,
        },
    }

    def __init__(self, controller):
        self.controller = controller
        self.workload_generator = WorkloadGenerator()
        self._run_lock = threading.Lock()
        self._current_run: Optional[ExperimentRun] = None
        self._abort_event = threading.Event()
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def current_run(self) -> Optional[ExperimentRun]:
        return self._current_run

    def list_experiments(self) -> List[Dict[str, Any]]:
        return list(self.EXPERIMENT_SPECS.values())

    def get_run_history(self) -> List[Dict[str, Any]]:
        """Returns indexed summaries of past runs sorted by newest first."""
        history = []
        if not RESULTS_DIR.exists():
            return history

        for p in sorted(RESULTS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
            if p.name == "index.json":
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    history.append({
                        "run_id": data.get("run_id"),
                        "experiment_id": data.get("experiment_id"),
                        "experiment_name": data.get("experiment_name"),
                        "started_at": data.get("started_at"),
                        "finished_at": data.get("finished_at"),
                        "status": data.get("status"),
                        "comparison_summary": data.get("comparison_summary", {}),
                    })
            except Exception as e:
                logger.debug("Failed to read experiment log %s: %s", p, e)
        return history

    def get_run_details(self, run_id: str) -> Optional[Dict[str, Any]]:
        file_path = RESULTS_DIR / f"{run_id}.json"
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error reading experiment result %s: %s", run_id, e)
            return None

    def start_experiment(self, experiment_id: str, mode: str = "both") -> Tuple[bool, str, Optional[str]]:
        """
        Starts an experiment asynchronously.
        mode can be 'both', 'baseline', or 'proposed'.
        """
        if experiment_id not in self.EXPERIMENT_SPECS:
            return False, f"Unknown experiment ID '{experiment_id}'. Available: {list(self.EXPERIMENT_SPECS.keys())}", None

        if not self._run_lock.acquire(blocking=False):
            return False, "Another experiment is currently running. Please wait for it to complete.", None

        spec = self.EXPERIMENT_SPECS[experiment_id]
        run_id = f"exp-{experiment_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        self._abort_event.clear()
        self._current_run = ExperimentRun(
            run_id=run_id,
            experiment_id=experiment_id,
            experiment_name=spec["name"],
            started_at=datetime.now(timezone.utc).isoformat(),
            status="RUNNING",
            stage="INITIALIZING",
            progress_percent=0,
        )

        # Launch background runner thread
        thread = threading.Thread(
            target=self._execute_experiment_lifecycle,
            args=(experiment_id, mode),
            daemon=True,
        )
        thread.start()
        return True, f"Experiment '{spec['name']}' started successfully.", run_id

    def stop_current_experiment(self) -> Tuple[bool, str]:
        """Requests graceful abort of the currently executing experiment."""
        if not self._current_run or self._current_run.status != "RUNNING":
            return False, "No experiment is currently running."

        self._abort_event.set()
        self.workload_generator.stop()
        self._current_run.stage = "ABORTING"
        self._current_run.status = "CANCELED"
        return True, "Experiment cancellation requested."

    def _execute_experiment_lifecycle(self, experiment_id: str, mode: str):
        """Lifecycle runner with mandatory cleanup guarantees."""
        run = self._current_run
        spec = self.EXPERIMENT_SPECS[experiment_id]

        try:
            logger.info("Starting experiment %s (mode=%s)...", run.run_id, mode)

            # Ensure baseline workload is at nominal replica count (2)
            self._ensure_cluster_ready()
            run.progress_percent = 5

            run_baseline = mode in ("both", "baseline")
            run_proposed = mode in ("both", "proposed")

            # 1. Run Baseline HPA
            if run_baseline and not self._abort_event.is_set():
                run.stage = "RUNNING_BASELINE_HPA"
                run.baseline_result = self._run_system_test(
                    system_type="baseline",
                    experiment_id=experiment_id,
                    spec=spec,
                    progress_range=(5, 50 if run_proposed else 95),
                )

            # 2. Transition & Run Proposed KubePilot
            if run_proposed and not self._abort_event.is_set():
                run.stage = "TRANSITIONING_TO_PROPOSED"
                # Always remove native HPA so KubePilot StrategyCoordinator does not flag collision
                self._delete_baseline_hpa()
                self._set_replicas(2)
                time.sleep(3.0)  # Brief stabilization

                run.stage = "RUNNING_PROPOSED_KUBEPILOT"
                run.proposed_result = self._run_system_test(
                    system_type="proposed",
                    experiment_id=experiment_id,
                    spec=spec,
                    progress_range=(50 if run_baseline else 5, 95),
                )

            # 3. Analyze and compute comparative metrics
            run.stage = "ANALYZING_RESULTS"
            run.comparison_summary = self._compute_comparison(run.baseline_result, run.proposed_result)
            run.progress_percent = 100
            run.status = "COMPLETED"
            run.finished_at = datetime.now(timezone.utc).isoformat()
            logger.info("Experiment %s completed successfully.", run.run_id)

            # 4. Save results to disk
            self._persist_run(run)

        except Exception as e:
            logger.exception("Experiment %s failed with exception: %s", run.run_id, e)
            run.status = "FAILED"
            run.stage = "FAILED"
            run.error_message = str(e)
            run.finished_at = datetime.now(timezone.utc).isoformat()
            self._persist_run(run)

        finally:
            # Absolute safety cleanup
            self._cleanup_teardown()
            self._run_lock.release()

    def _ensure_cluster_ready(self):
        """Verifies reachability and sets initial workload state to 2 replicas."""
        self._delete_baseline_hpa()
        self._set_replicas(2)
        # Verify Prometheus reachability
        prom_ok, msg = self.controller.prometheus_provider.check_connection()
        if not prom_ok:
            logger.warning("Prometheus check warning: %s", msg)

    def _apply_baseline_hpa(self):
        """Creates native HorizontalPodAutoscaler targeting sample-web-app."""
        if MANIFEST_PATH.exists():
            cmd = f'kubectl apply -f "{MANIFEST_PATH}"'
        else:
            cmd = (
                "kubectl autoscale deployment sample-web-app "
                "--namespace=autoscaling-demo --cpu-percent=75 --min=2 --max=10"
            )
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning("HPA creation output: %s %s", res.stdout, res.stderr)
        time.sleep(2.0)

    def _delete_baseline_hpa(self):
        """Safely removes native HPA to avoid collision."""
        cmd = "kubectl delete hpa sample-web-app -n autoscaling-demo --ignore-not-found=true"
        subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def _set_replicas(self, count: int):
        """Sets deployment scale to target replica count."""
        cmd = f"kubectl scale deployment sample-web-app -n autoscaling-demo --replicas={count}"
        subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def _cleanup_teardown(self):
        """Teardown handler to guarantee no lingering mutation mode or competing HPA."""
        try:
            self.workload_generator.stop()
            self._delete_baseline_hpa()
            # Ensure KubePilot controller returns safely to dry-run preview mode
            self.controller.config.enable_live_execution = False
            self.controller.config.dry_run = True
            logger.info("Experiment teardown complete; returned to safe dry-run mode.")
        except Exception as e:
            logger.error("Teardown error: %s", e)

    def _run_system_test(
        self,
        system_type: str,
        experiment_id: str,
        spec: Dict[str, Any],
        progress_range: Tuple[int, int],
    ) -> SystemRunResult:
        """Runs the workload for either Baseline HPA or Proposed KubePilot."""
        duration = spec.get("duration_seconds", 20.0)
        p_start, p_end = progress_range

        # Configure system mode
        if system_type == "baseline":
            # Enable HPA, disable KubePilot live execution
            self.controller.config.enable_live_execution = False
            self.controller.config.dry_run = True
            self._apply_baseline_hpa()
        else:
            # Remove HPA, enable KubePilot live execution
            self._delete_baseline_hpa()
            self.controller.config.enable_live_execution = True
            self.controller.config.dry_run = False

        # Ensure workload starts at 2 replicas
        self._set_replicas(2)
        initial_replicas = 2

        # Start workload pattern
        if experiment_id == "stable_workload":
            self.workload_generator.run_stable_traffic(
                duration_seconds=duration,
                target_rps=spec.get("target_rps", 10),
            )
        elif experiment_id == "traffic_spike":
            self.workload_generator.run_spike_traffic(
                duration_seconds=duration,
                baseline_duration=spec.get("baseline_seconds", 5.0),
                spike_duration=spec.get("spike_seconds", 15.0),
                concurrency=spec.get("concurrency", 6),
            )

        # Sampling loop
        samples: List[TimeSeriesSample] = []
        start_time = time.time()
        time_to_first_scale = None
        peak_replicas = initial_replicas
        scaling_events = 0
        last_replicas = initial_replicas
        interval = 1.0

        while (time.time() - start_time) < duration and not self._abort_event.is_set():
            loop_start = time.time()
            elapsed = round(loop_start - start_time, 1)

            # If proposed system, trigger an evaluation cycle
            action_name = "HOLD"
            if system_type == "proposed":
                try:
                    cycle_res = self.controller.run_single_cycle(now=loop_start)
                    dec = cycle_res.get("decision", {})
                    action_name = dec.get("action", "HOLD")
                except Exception as e:
                    logger.debug("Cycle error: %s", e)

            # Collect live telemetry from Prometheus
            metrics = self.controller.fetch_current_telemetry()
            cpu_val = metrics.get("cpu_utilization_percent")
            cpu_pct = round(cpu_val.value if (cpu_val and cpu_val.value is not None) else 0.0, 2)

            mem_val = metrics.get("memory_utilization_percent")
            mem_pct = round(mem_val.value if (mem_val and mem_val.value is not None) else 0.0, 2)

            rps_val = metrics.get("http_requests_per_second")
            rps_num = round(rps_val.value if (rps_val and rps_val.value is not None) else 0.0, 2)

            # Query real workload state from Kubernetes
            ws = self.controller.executor.get_workload_state()
            desired = ws.desired_replicas
            current = ws.current_replicas
            ready = ws.ready_replicas

            if desired > peak_replicas:
                peak_replicas = desired

            if desired != last_replicas:
                scaling_events += 1
                if time_to_first_scale is None:
                    time_to_first_scale = elapsed
                last_replicas = desired

            # Generator stats
            gen_stats = self.workload_generator.get_stats()
            workload_rps = round(gen_stats["sent"] / max(1.0, elapsed), 2)

            sample = TimeSeriesSample(
                timestamp=loop_start,
                iso_timestamp=datetime.fromtimestamp(loop_start, timezone.utc).isoformat(),
                elapsed_seconds=elapsed,
                system=system_type,
                cpu_utilization_percent=cpu_pct,
                memory_utilization_percent=mem_pct,
                http_requests_per_second=rps_num,
                desired_replicas=desired,
                current_replicas=current,
                ready_replicas=ready,
                scaling_action=action_name,
                workload_rps_actual=workload_rps,
                workload_latency_avg_ms=gen_stats["avg_latency_ms"],
            )
            samples.append(sample)

            # Update progress percent
            fraction = min(1.0, (time.time() - start_time) / duration)
            self._current_run.progress_percent = int(p_start + fraction * (p_end - p_start))

            # Pacing
            sleep_needed = interval - (time.time() - loop_start)
            if sleep_needed > 0:
                time.sleep(sleep_needed)

        # Stop workload
        self.workload_generator.stop()
        final_stats = self.workload_generator.get_stats()

        cpu_values = [s.cpu_utilization_percent for s in samples] or [0.0]
        mem_values = [s.memory_utilization_percent for s in samples] or [0.0]

        return SystemRunResult(
            system=system_type,
            duration_seconds=round(time.time() - start_time, 1),
            initial_replicas=initial_replicas,
            peak_replicas=peak_replicas,
            final_replicas=last_replicas,
            scaling_events_count=scaling_events,
            time_to_first_scale_seconds=time_to_first_scale,
            max_cpu_percent=round(max(cpu_values), 2),
            avg_cpu_percent=round(sum(cpu_values) / len(cpu_values), 2),
            max_memory_percent=round(max(mem_values), 2),
            total_requests_sent=final_stats["sent"],
            successful_requests=final_stats["success"],
            failed_requests=final_stats["failed"],
            avg_request_latency_ms=final_stats["avg_latency_ms"],
            samples=samples,
        )

    def _compute_comparison(
        self,
        baseline: Optional[SystemRunResult],
        proposed: Optional[SystemRunResult],
    ) -> Dict[str, Any]:
        """Calculates side-by-side performance indicators."""
        if not baseline or not proposed:
            return {"note": "Single system run completed. Full comparison requires running both systems."}

        # Response time improvement
        scale_lat_b = baseline.time_to_first_scale_seconds
        scale_lat_p = proposed.time_to_first_scale_seconds

        latency_diff_seconds = None
        if scale_lat_b is not None and scale_lat_p is not None:
            latency_diff_seconds = round(scale_lat_b - scale_lat_p, 2)

        return {
            "baseline_peak_replicas": baseline.peak_replicas,
            "proposed_peak_replicas": proposed.peak_replicas,
            "baseline_scale_latency_seconds": scale_lat_b,
            "proposed_scale_latency_seconds": scale_lat_p,
            "scale_latency_improvement_seconds": latency_diff_seconds,
            "baseline_scaling_events": baseline.scaling_events_count,
            "proposed_scaling_events": proposed.scaling_events_count,
            "baseline_avg_cpu_percent": baseline.avg_cpu_percent,
            "proposed_avg_cpu_percent": proposed.avg_cpu_percent,
            "baseline_max_cpu_percent": baseline.max_cpu_percent,
            "proposed_max_cpu_percent": proposed.max_cpu_percent,
            "baseline_avg_latency_ms": baseline.avg_request_latency_ms,
            "proposed_avg_latency_ms": proposed.avg_request_latency_ms,
            "scaling_stability": (
                "STABLE (No Flapping)"
                if proposed.scaling_events_count <= 2
                else f"OSCILLATIONS DETECTED ({proposed.scaling_events_count} events)"
            ),
        }

    def _persist_run(self, run: ExperimentRun):
        """Saves run output to both JSON and CSV files."""
        run_dict = run.to_dict()
        json_file = RESULTS_DIR / f"{run.run_id}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(run_dict, f, indent=2)

        # Write time series CSV
        csv_file = RESULTS_DIR / f"{run.run_id}.csv"
        all_samples: List[Dict[str, Any]] = []

        if run.baseline_result:
            for s in run.baseline_result.samples:
                all_samples.append(s if isinstance(s, dict) else s.to_dict())
        if run.proposed_result:
            for s in run.proposed_result.samples:
                all_samples.append(s if isinstance(s, dict) else s.to_dict())

        if all_samples:
            fieldnames = list(all_samples[0].keys())
            with open(csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_samples)

        logger.info("Saved experiment run %s to %s and %s", run.run_id, json_file, csv_file)
