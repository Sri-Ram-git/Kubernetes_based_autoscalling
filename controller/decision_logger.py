"""
Structured Decision and Execution Audit Logger.
Project ID: 357 | Alliance University, Bengaluru

Strict requirement:
- Record timestamp, evaluation ID, target namespace/deployment, triggering policy,
  observed metric, proposed action, requested replicas, previous & resulting replicas,
  execution mode (DRY_RUN vs LIVE), status (PROPOSED, BLOCKED, DRY_RUN, EXECUTED, VERIFIED, FAILED),
  and truthful explanation.
- Never log secrets or credentials.
- Thread-safe JSON Lines structured persistence.
- Avoid duplicate records from dashboard refreshes or repeated nominal reads.
"""

import collections
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("autoscaler.decision_logger")


class DecisionLogger:
    """Thread-safe structured audit logger for scaling decisions and execution outcomes."""

    def __init__(self, log_file_path: str = "logs/decisions.jsonl", max_history_records: int = 200):
        self.log_file_path = log_file_path
        self.max_history_records = max_history_records
        self._lock = threading.Lock()
        self._history_buffer: collections.deque = collections.deque(maxlen=max_history_records)

        # Ensure directory exists
        log_dir = Path(log_file_path).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        # Load existing records if available
        self._preload_recent_records()

    @staticmethod
    def _normalize_record(raw: Dict[str, Any], default_ns: str = "autoscaling-demo", default_dep: str = "sample-web-app") -> Dict[str, Any]:
        """Normalizes a raw decision record to ensure all required fields are present and truthful."""
        if not isinstance(raw, dict):
            return raw

        record = dict(raw)
        d = record.get("decision") or {}
        g = record.get("guardrail") or {}
        e = record.get("execution") or {}
        m = record.get("metrics") or {}
        err = record.get("error") or e.get("error") or g.get("rejection_reason")

        # 1. ID
        if "id" not in record and "evaluation_id" not in record:
            eval_id = f"eval-{uuid.uuid4().hex[:8]}"
            record["id"] = eval_id
            record["evaluation_id"] = eval_id
        elif "id" not in record:
            record["id"] = record.get("evaluation_id")
        elif "evaluation_id" not in record:
            record["evaluation_id"] = record.get("id")

        # 2. Target workload
        record.setdefault("target_namespace", d.get("target_namespace") or default_ns)
        record.setdefault("target_deployment", d.get("target_deployment") or default_dep)

        # 3. Policy & Metric
        policy_id = d.get("selected_policy_id")
        policy_name = d.get("selected_policy_name")
        record.setdefault("policy_id", policy_id)
        record.setdefault("policy_name", policy_name)

        triggering_metric = None
        observed_val = None
        threshold_val = None
        proposals = d.get("competing_proposals") or []
        for p in proposals:
            if p.get("policy_id") == policy_id:
                triggering_metric = p.get("metric_name")
                observed_val = p.get("observed_value")
                threshold_val = p.get("threshold")
                break
        if not triggering_metric and m and isinstance(m, dict):
            for k, v in m.items():
                if isinstance(v, dict) and v.get("value") is not None:
                    triggering_metric = k
                    observed_val = v.get("value")
                    break

        record.setdefault("metric", triggering_metric)
        record.setdefault("observed_value", observed_val)
        record.setdefault("threshold", threshold_val)

        # 4. Action and Replicas
        proposed_action = d.get("action", "HOLD")
        current_rep = d.get("current_replicas", e.get("initial_replicas", 2))
        target_rep = g.get("authorized_target_replicas", d.get("target_replicas", current_rep))

        record.setdefault("proposed_action", proposed_action)
        record.setdefault("requested_replicas", target_rep)
        record.setdefault("previous_replicas", current_rep)

        # 5. Mode
        is_dry = bool(g.get("is_dry_run") or e.get("dry_run", True))
        mode = "DRY_RUN" if is_dry else "LIVE"
        record.setdefault("mode", mode)

        # 6. Status and Resulting Replicas
        cooldown_active = bool(d.get("cooldown_active"))
        guardrail_action = g.get("action", "HOLD")
        exec_success = bool(e.get("success", False))

        if err or guardrail_action == "REJECTED":
            status = "BLOCKED" if (cooldown_active or guardrail_action == "REJECTED") else "FAILED"
            resulting_rep = current_rep
            explanation = err or g.get("rejection_reason") or "Action rejected"
        elif cooldown_active:
            status = "BLOCKED"
            resulting_rep = current_rep
            rem = d.get("cooldown_remaining_seconds", 0.0)
            explanation = f"Blocked by cooldown ({rem:.1f}s remaining)."
        elif is_dry:
            if proposed_action in ("SCALE_OUT", "SCALE_IN"):
                status = "DRY_RUN"
                resulting_rep = None  # Dry-run never modifies cluster
                explanation = f"[DRY-RUN] Proposed {proposed_action} from {current_rep} to {target_rep}. Cluster unmodified."
            else:
                status = "PROPOSED" if policy_id else "HOLD"
                resulting_rep = current_rep
                explanation = d.get("explanation") or "Nominal parameters; holding replicas."
        else:
            # LIVE mode
            if exec_success:
                if e.get("confirmed_replicas") == target_rep and proposed_action in ("SCALE_OUT", "SCALE_IN"):
                    status = "VERIFIED"
                    resulting_rep = target_rep
                    explanation = f"Scaled to {target_rep} replicas (verified by Kubernetes API)."
                elif proposed_action == "HOLD":
                    status = "HOLD"
                    resulting_rep = current_rep
                    explanation = d.get("explanation") or "Holding current replica count."
                else:
                    status = "EXECUTED"
                    resulting_rep = e.get("confirmed_replicas", target_rep)
                    explanation = e.get("message") or "Executed change."
            else:
                status = "FAILED"
                resulting_rep = current_rep
                explanation = e.get("message") or err or "Live scaling execution failed."

        record.setdefault("status", status)
        record.setdefault("resulting_replicas", resulting_rep)
        record.setdefault("explanation", explanation)

        return record

    def _preload_recent_records(self) -> None:
        """Preloads recent entries from the JSONL log file into the in-memory ring buffer with normalization."""
        p = Path(self.log_file_path)
        if not p.exists():
            return

        try:
            with open(p, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[-self.max_history_records:]:
                    line = line.strip()
                    if line:
                        try:
                            raw = json.loads(line)
                            normalized = self._normalize_record(raw)
                            self._history_buffer.append(normalized)
                        except json.JSONDecodeError:
                            continue
            logger.info("Preloaded %d normalized decision records from %s", len(self._history_buffer), self.log_file_path)
        except Exception as e:
            logger.warning("Could not preload decision logs: %s", e)

    def log_cycle(
        self,
        decision: Dict[str, Any],
        guardrail_result: Optional[Dict[str, Any]] = None,
        execution_result: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        target_namespace: str = "autoscaling-demo",
        target_deployment: str = "sample-web-app",
    ) -> Dict[str, Any]:
        """
        Constructs and records an atomic, structured audit record for an evaluation cycle.
        Filters repetitive consecutive nominal HOLD entries.
        """
        eval_id = f"eval-{uuid.uuid4().hex[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        raw_record: Dict[str, Any] = {
            "id": eval_id,
            "evaluation_id": eval_id,
            "timestamp": now_iso,
            "target_namespace": target_namespace,
            "target_deployment": target_deployment,
            "decision": decision,
            "guardrail": guardrail_result,
            "execution": execution_result,
            "metrics": metrics or {},
            "error": error,
        }

        record = self._normalize_record(raw_record, default_ns=target_namespace, default_dep=target_deployment)

        with self._lock:
            # Deduplication: do not append identical consecutive nominal HOLDs
            is_nominal_hold = (
                record.get("status") in ("HOLD", "PROPOSED")
                and record.get("proposed_action") == "HOLD"
                and not record.get("policy_id")
                and not decision.get("cooldown_active")
                and not error
            )

            if is_nominal_hold and len(self._history_buffer) > 0:
                last = self._history_buffer[-1]
                last_is_nominal = (
                    last.get("proposed_action") == "HOLD"
                    and not last.get("policy_id")
                    and last.get("previous_replicas") == record.get("previous_replicas")
                    and not last.get("error")
                )
                if last_is_nominal:
                    # Update timestamp on existing record to show active evaluation without cluttering history
                    last["timestamp"] = now_iso
                    return last

            # Append to in-memory deque
            self._history_buffer.append(record)

            # Persist to JSON Lines file
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
            except Exception as e:
                logger.error("Failed to append decision record to %s: %s", self.log_file_path, e)

        return record

    def get_recent_decisions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns the most recent decisions in reverse chronological order (newest first)."""
        with self._lock:
            items = list(self._history_buffer)
        items.reverse()
        return items[:limit]

    def clear(self) -> None:
        """Clears in-memory buffer (primarily for test isolation)."""
        with self._lock:
            self._history_buffer.clear()
