"""
Structured Decision and Execution Audit Logger.
Project ID: 357 | Alliance University, Bengaluru

Strict requirement:
- Record timestamp, observed metrics, evaluated policies, selected action,
  explanation, guardrail outcome, execution result, and errors.
- Never log secrets or credentials.
- Thread-safe JSON Lines structured persistence.
"""

import collections
import json
import logging
import os
import threading
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

    def _preload_recent_records(self) -> None:
        """Preloads recent entries from the JSONL log file into the in-memory ring buffer."""
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
                            self._history_buffer.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            logger.info("Preloaded %d decision records from %s", len(self._history_buffer), self.log_file_path)
        except Exception as e:
            logger.warning("Could not preload decision logs: %s", e)

    def log_cycle(
        self,
        decision: Dict[str, Any],
        guardrail_result: Optional[Dict[str, Any]] = None,
        execution_result: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Constructs and records an atomic, structured audit record for an evaluation cycle.
        """
        record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "guardrail": guardrail_result,
            "execution": execution_result,
            "metrics": metrics or {},
            "error": error,
        }

        with self._lock:
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
