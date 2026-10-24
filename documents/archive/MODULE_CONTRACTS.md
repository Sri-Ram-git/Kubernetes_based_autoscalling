# PROJECT 357 — Module Contracts & Architecture Specification

**Project Title:** Kubernetes-Based Auto-Scaling Framework for Cloud Applications  
**Module Specification Version:** 1.0  
**Project ID:** 357 | Alliance University, Bengaluru  

---

## 1. Architectural Overview & Component Mapping

The framework consists of seven distinct modules operating in an explainable, deterministic pipeline. Each module owns a specific responsibility, preventing circular dependencies and separating policy decisions from operational execution.

```
                      +-----------------------------------+
                      |   Module 1: Telemetry Collector   |
                      |    (controller/telemetry.py)      |
                      +-----------------+-----------------+
                                        | Dict[str, MetricSample]
                                        v
                      +-----------------------------------+
                      |     Module 2: Policy Engine       |
                      |   (controller/policy_engine.py)   |
                      +-----------------+-----------------+
                                        | List[PolicyEvaluationResult]
                                        v
                      +-----------------------------------+
                      | Module 3: PRAH Decision Controller|
                      | (controller/decision_controller.py|
                      +-----------------+-----------------+
                                        | Decision
                                        v
                      +-----------------------------------+
                      |  Module 4: Strategy Coordinator   |
                      | (controller/strategy_coordinator) |
                      +--------+-----------------+--------+
                               |                 |
            Guardrail Contract |                 | Execution Contract
                               v                 v
            +----------------------+     +----------------------+
            |  Module 5: Guardrails|     |  Module 6: K8s Exec  |
            | (controller/guard)   |     | (controller/k8s_exec)|
            +----------------------+     +----------------------+
                               \                 /
                                \               / GuardrailResult & ExecutionResult
                                 v             v
                      +-----------------------------------+
                      |     Module 7: Decision Logger     |
                      |  (controller/decision_logger.py)  |
                      +-----------------------------------+
```

---

## 2. Common Data Structures & Contracts

| Data Structure | Source Module | Consuming Modules | Description |
| :--- | :--- | :--- | :--- |
| `MetricSample` | Module 1 | Module 2, Module 3, Module 7, Dashboard | Encapsulates a metric reading, its timestamp, staleness/health status, and origin. |
| `MetricStatus` | Module 1 | Module 1, Module 2, Module 3, Dashboard | Enum: `VALID`, `MISSING`, `STALE`, `ERROR`, `SIMULATED`. |
| `PolicyRule` | Module 2 | Module 2 | Parsed rule configuration (priority, operator, threshold, delta, cooldown). |
| `PolicyEvaluationResult` | Module 2 | Module 3 | Evaluation result per rule against current telemetry. |
| `Proposal` | Module 3 | Module 3, Module 7, Dashboard | A matched rule proposing an action (`SCALE_OUT`, `SCALE_IN`, `HOLD`). |
| `Decision` | Module 3 | Module 4, Module 7, Dashboard | Final arbitrated decision output from PRAH with reason and competing candidates. |
| `GuardrailResult` | Module 5 | Module 4, Module 7, Dashboard | Approval status, clamped target replicas, and safety authorization note. |
| `WorkloadState` | Module 6 | Module 4, Module 5, Main, Dashboard | Current observed deployment replicas, pod readiness list, and cluster health. |
| `ExecutionResult` | Module 6 | Module 4, Module 7, Dashboard | Execution status, confirmed replicas, duration, and API error message if any. |

---

## 3. Module Specifications

### Module 1 / 2: Telemetry Processing & Live Prometheus Integration
* **File Location:** [`controller/telemetry.py`](file:///C:/Users/SRIRAM/design_project/controller/telemetry.py)
* **Purpose:** Queries instant vector telemetry from Prometheus, validates timestamp freshness against a staleness threshold, enforces strict numerical bounds (rejecting non-finite values like NaN/Inf), and tags samples with explicit health statuses. Discovers and reports live scrape target health from `/api/v1/targets`.
* **Public Classes & Functions:**
  - `MetricStatus(str, Enum)`: Health enumeration (`VALID`, `MISSING`, `STALE`, `ERROR`, `SIMULATED`, `INVALID`, `UNAVAILABLE`).
  - `MetricSample`: Dataclass holding `metric_name`, `value`, `timestamp`, `status`, `source`, `query`, `unit`, `freshness_seconds`, `scrape_target`, `error_message`. Method: `is_usable() -> bool`.
  - `PrometheusTelemetryProvider(prometheus_url, staleness_threshold_seconds, request_timeout_seconds)`:
    - `check_connection() -> Tuple[bool, str]`
    - `get_targets_status() -> Dict[str, Any]` (inspects `/api/v1/targets`)
    - `query_instant(query: str, metric_name: str, unit: Optional[str] = None) -> MetricSample`
    - `session -> requests.Session`
  - `SimulatedTelemetryProvider(initial_values)`:
    - `set_metric(name, value, status)`
    - `query_instant(query, metric_name, unit)`
  - `build_metric_queries(namespace: str, deployment: str) -> Dict[str, str]` (implements dual PromQL cAdvisor and app-level fallback via PromQL `or`)
* **Inputs:** PromQL query string, metric name, unit, Prometheus URL, HTTP response body.
* **Outputs:** Dictionary of `MetricSample` objects indexed by metric name with strict status guarantees.
* **Dependencies:** `requests`, `math`, standard Python libraries (`time`, `dataclasses`, `enum`).
* **Error Handling:**
  - HTTP errors (non-200) $\to$ `status = MetricStatus.ERROR`.
  - Connection timeout $\to$ `status = MetricStatus.ERROR`.
  - Connection error / unreachable $\to$ `status = MetricStatus.UNAVAILABLE`.
  - Empty vector results $\to$ `status = MetricStatus.MISSING`.
  - Non-finite values (`NaN`, `+Inf`, `-Inf`) $\to$ `status = MetricStatus.INVALID`.
  - Sample timestamp $> 60.0\text{s}$ old $\to$ `status = MetricStatus.STALE`.
  - Missing or invalid telemetry is NEVER converted to zero; PRAH engine treats `not sample.is_usable()` as an immediate fail-safe HOLD condition.
* **Logging:** Emits warnings on stale metrics or HTTP failures; errors on timeout and network failures.
* **Existing Tests:** 9 unit/mocked tests in [`tests/test_telemetry.py`](file:///C:/Users/SRIRAM/design_project/tests/test_telemetry.py) covering valid responses, stale detection, empty results, non-finite rejection, HTTP 500 error, timeout, connection errors, scrape target discovery, and simulated labeling. (100% passing).

---

### Module 2 / 3: Policy Engine Implementation
* **File Location:** [`controller/policy_engine.py`](file:///C:/Users/SRIRAM/design_project/controller/policy_engine.py)
* **Purpose:** Deterministic, configuration-driven policy engine that parses and strictly validates declarative scaling policies from YAML, tracks duration persistence across control iterations, and evaluates mathematical conditions against validated telemetry to produce structured policy proposals for the PRAH decision controller.
* **Non-Negotiable Architecture:** Strictly rule-based comparison. NO machine learning, NO predictive models, NO LLMs, NO probabilistic guessing.
* **Public Classes & Functions:**
  - `SUPPORTED_OPERATORS`: Dict of explicit comparison operators (`>`, `>=`, `<`, `<=`, `==`, `!=`). Floating point equality uses `math.isclose` with `rel_tol=1e-5`.
  - `SUPPORTED_ACTIONS`: Set of authorized policy actions (`{"SCALE_OUT", "SCALE_IN", "HOLD"}`).
  - `SUPPORTED_METRICS`: Set of validated metric names (`{"cpu_utilization_percent", "memory_utilization_percent", "http_requests_per_second"}`).
  - `PolicyValidationError(Exception)`: Custom exception raised when policy configuration violates schema or semantic integrity rules.
  - `PolicyRule`: Dataclass representing a validated policy rule with `evaluate_condition(value: float) -> bool` and `to_dict() -> Dict[str, Any]`.
  - `PolicyEvaluationResult`: Dataclass holding evaluation outcome:
    - `policy_id: str`
    - `policy_name: str`
    - `metric: str`
    - `operator: str`
    - `threshold: float`
    - `action: str`
    - `priority: int`
    - `replica_delta: int`
    - `matched: bool`
    - `evaluable: bool`
    - `observed_value: Optional[float]`
    - `reason: str`
    - `duration_seconds: float`
    - `cooldown_seconds: float`
    - `to_dict() -> Dict[str, Any]`
  - `PolicyEngine(policy_file_path: Optional[str])`:
    - `load_from_yaml(file_path: str) -> None`: Loads and parses policy YAML from disk.
    - `validate_and_parse(data: Dict[str, Any]) -> None`: Enforces strict validation:
      1. Rejects missing required fields (`id`, `name`, `metric`, `operator`, `threshold`, `action`, `priority`).
      2. Rejects duplicate policy IDs.
      3. Rejects empty policy lists.
      4. Rejects unsupported operators or unsupported metrics.
      5. Rejects non-finite, negative, or out-of-range thresholds (e.g. percentage not in $[0, 100]$).
      6. Rejects semantic direction mismatches (negative delta on `SCALE_OUT`, positive delta on `SCALE_IN`).
      7. Rejects negative durations, priorities, or cooldowns.
    - `evaluate(metrics: Dict[str, MetricSample], now: Optional[float] = None) -> List[PolicyEvaluationResult]`: Evaluates all enabled policies against provided telemetry without arbitrating or suppressing lower priorities.
* **Inputs:** YAML file path, dictionary of `MetricSample` objects, optional timestamp `now`.
* **Outputs:** Deterministic list of `PolicyEvaluationResult` instances detailing condition match, evaluability, and duration persistence.
* **Dependencies:** `yaml` (PyYAML), `math`, `time`, `dataclasses`, `controller.telemetry.MetricSample`.
* **Safe Telemetry & Degradation Behavior:**
  - If a metric sample is missing, stale, invalid, or unavailable (`not sample.is_usable()`), the policy is evaluated as `evaluable=False`, `matched=False`, `action="HOLD"`.
  - Missing or invalid telemetry is NEVER silently converted to 0.0 or fabricated.
  - Explanations explicitly state the failure cause (e.g., `cpu_utilization_percent metric unavailable (status=MISSING)`).
* **PRAH Arbitration Handoff Contract:**
  - The Policy Engine never filters or arbitrates between conflicting policies. It returns ALL matching proposals along with their configured priorities (`priority` int).
  - The PRAH Decision Controller (`controller/decision_controller.py`) is solely responsible for priority arbitration, tie-breaking, direction-flip hysteresis, and cooldown enforcement.
* **Dashboard Integration:**
  - `/api/policies`: Returns loaded policy metadata along with current threshold configurations.
  - `/api/decisions`: Exposes evaluation results and competing proposals.
  - `/api/policies/update-threshold`: Dynamically updates thresholds with strict validation (finite, numeric, bounded).
* **Logging:** Structured logging for rule loading, validation errors, and evaluation outcomes.
* **Existing Tests:** 18 comprehensive pytest test cases in [`tests/test_policy_engine.py`](file:///C:/Users/SRIRAM/design_project/tests/test_policy_engine.py) covering schema validation, duplicate detection, empty list rejection, operator correctness, boundary conditions, safe degraded telemetry handling, multiple matches with different priorities, determinism, and PRAH handoff. (100% passing).

---

### Module 3: PRAH Decision Controller
* **File Location:** [`controller/decision_controller.py`](file:///C:/Users/SRIRAM/design_project/controller/decision_controller.py)
* **Purpose:** Coordinates rule evaluation results, executes priority-based arbitration, breaks equal-priority conflicts with scale-out preference, suppresses directional flapping via hysteresis delay, enforces cooldowns, and generates structured decision outputs.
* **Public Classes & Functions:**
  - `Proposal`: Candidate action dataclass.
  - `Decision`: Arbitrated decision dataclass with full explanatory rationale.
  - `DecisionController(policy_engine, default_cooldown_seconds, hysteresis_band_percent, min_direction_flip_delay_seconds)`:
    - `compute_decision(metrics, current_replicas, now) -> Decision`
    - `record_action_executed(action, policy_id, cooldown_seconds, now) -> None`
    - `reset_cooldown() -> None`
* **Inputs:** Dict of `MetricSample`, current workload replica count, optional timestamp.
* **Outputs:** Single `Decision` instance with approved action, proposed delta, selected policy, and reason.
* **Dependencies:** `controller.policy_engine.PolicyEngine`, `controller.telemetry.MetricSample`.
* **Error Handling & Failure Behavior:**
  - Degraded metrics (`MISSING`, `STALE`, `ERROR`) $\to$ Triggers **Telemetry Safety Fallback**: immediately outputs `HOLD` (priority 999) with full diagnostic explanation.
  - Direction flip within 30 seconds $\to$ Triggers **Hysteresis Protection**: converts action to `HOLD`.
  - Active cooldown $\to$ Converts action to `HOLD` with remaining seconds reported.
* **Logging:** Logs scaling action executions and cooldown activations.
* **Existing Tests:** 8 tests across [`tests/test_decision_controller.py`](file:///C:/Users/SRIRAM/design_project/tests/test_decision_controller.py) and [`tests/test_hysteresis.py`](file:///C:/Users/SRIRAM/design_project/tests/test_hysteresis.py) covering arbitration priority, tie-breaking, missing/stale fallback, cooldown expiration, and direction-flip suppression. (93% coverage).
* **Missing Tests / Gaps:** Test behavior when 3 or more competing policies have identical priority.

---

### Module 4: Scaling Strategy Coordinator
* **File Location:** [`controller/strategy_coordinator.py`](file:///C:/Users/SRIRAM/design_project/controller/strategy_coordinator.py)
* **Purpose:** Ensures single-controller ownership of the target Deployment. Detects competing native `HorizontalPodAutoscaler` objects targeting the same workload to prevent conflicting replica updates. Coordinates guardrail validation and execution delegation.
* **Public Classes & Functions:**
  - `StrategyCoordinator(executor, guardrail_engine, enforce_exclusive_ownership)`:
    - `check_competing_hpa() -> Tuple[bool, Optional[str]]`
    - `coordinate_and_execute(proposed_action, current_replicas, target_replicas, replica_delta) -> Tuple[GuardrailResult, ExecutionResult]`
* **Inputs:** `proposed_action`, `current_replicas`, `target_replicas`, `replica_delta`.
* **Outputs:** Tuple of `(GuardrailResult, ExecutionResult)`.
* **Dependencies:** `controller.guardrails.GuardrailEngine`, `controller.kubernetes_executor.KubernetesExecutor`, `kubernetes.client.AutoscalingV2Api`.
* **Error Handling:**
  - Competing HPA detected $\to$ Aborts execution, returns `REJECTED` GuardrailResult and failure `ExecutionResult`.
  - API errors during HPA inspection $\to$ Gracefully skips check without crashing.
* **Logging:** Logs ownership conflicts at ERROR level; debugs skipped checks.
* **Existing Tests:** Covered via integration flows in [`tests/test_guardrails.py`](file:///C:/Users/SRIRAM/design_project/tests/test_guardrails.py) and [`tests/test_dashboard_api.py`](file:///C:/Users/SRIRAM/design_project/tests/test_dashboard_api.py). (59% coverage).
* **Missing Tests / Gaps:** Dedicated unit test with mocked `AutoscalingV2Api` simulating a live competing HPA.

---

### Module 5: Guardrails
* **File Location:** [`controller/guardrails.py`](file:///C:/Users/SRIRAM/design_project/controller/guardrails.py)
* **Purpose:** Operational safety layer separating decision proposal from execution authorization. Enforces $[min\_replicas, max\_replicas]$ bounds, clamps step sizes ($+2$ scale-out, $-1$ scale-in), filters redundant actions, and gates live cluster mutations.
* **Public Classes & Functions:**
  - `GuardrailResult`: Dataclass holding approval boolean, action (`EXECUTE`, `HOLD`, `REJECTED`), clamped target, and notes.
  - `GuardrailEngine(min_replicas, max_replicas, max_scale_step_up, max_scale_step_down, dry_run, enable_live_execution)`:
    - `set_live_execution(enabled: bool) -> None`
    - `validate_action(proposed_action, current_replicas, target_replicas, replica_delta) -> GuardrailResult`
* **Inputs:** Proposed action string, current replica count, target replica count, replica delta.
* **Outputs:** `GuardrailResult` instance.
* **Dependencies:** Pure Python (`dataclasses`, `logging`).
* **Error Handling:**
  - Target $< min\_replicas$ when already at min $\to$ `REJECTED`.
  - Target $> max\_replicas$ when already at max $\to$ `REJECTED`.
  - Exceeds step size $\to$ clamps delta to `max_scale_step_up` or `max_scale_step_down` with `clamped = True`.
  - Target equals current replicas $\to$ filters as redundant `HOLD`.
* **Logging:** Logs clamping actions and live execution state changes.
* **Existing Tests:** 8 comprehensive unit tests in [`tests/test_guardrails.py`](file:///C:/Users/SRIRAM/design_project/tests/test_guardrails.py). (99% coverage).
* **Missing Tests / Gaps:** None; full branch coverage achieved.

---

### Module 6: Kubernetes Executor
* **File Location:** [`controller/kubernetes_executor.py`](file:///C:/Users/SRIRAM/design_project/controller/kubernetes_executor.py)
* **Purpose:** Communicates with the Kubernetes API (`apps/v1` and `core/v1`), queries deployment state and pod readiness, patches the `scale` subresource, polls the cluster to verify state convergence, and supports safe dry-run preview mode.
* **Public Classes & Functions:**
  - `WorkloadState`: Dataclass holding desired/current/ready/unavailable replica counts, connection boolean, status message, and individual pod records.
  - `ExecutionResult`: Dataclass holding success boolean, dry_run flag, confirmed replicas, duration ms, and error.
  - `KubernetesExecutor(namespace, deployment_name, kubeconfig_path, verification_timeout_seconds)`:
    - `is_connected() -> Tuple[bool, str]`
    - `get_workload_state() -> WorkloadState`
    - `execute_scaling(action, target_replicas, dry_run) -> ExecutionResult`
* **Inputs:** Namespace, Deployment name, kubeconfig path, scaling target replicas, dry_run boolean.
* **Outputs:** `WorkloadState` or `ExecutionResult`.
* **Dependencies:** `kubernetes` Python client (`AppsV1Api`, `CoreV1Api`, `config`).
* **Error Handling:**
  - Cluster unreachable $\to$ Gracefully returns simulated workload state (`connected = False`).
  - Scale patch API exception $\to$ Returns `ExecutionResult(success=False, error=...)` without unhandled exception.
  - Scale patch sent but replica count fails to update within timeout $\to$ Reports verification timeout.
* **Logging:** Logs client initialization, patches executed, verification outcomes, and API errors.
* **Existing Tests:** 4 unit/mocked tests in [`tests/test_kubernetes_executor.py`](file:///C:/Users/SRIRAM/design_project/tests/test_kubernetes_executor.py). (70% coverage).
* **Missing Tests / Gaps:** Test pod readiness condition inspection when container crashes or restarts; test partial scale convergence timeout.

---

### Module 7: Decision Logger
* **File Location:** [`controller/decision_logger.py`](file:///C:/Users/SRIRAM/design_project/controller/decision_logger.py)
* **Purpose:** Thread-safe, non-blocking structured audit logging. Appends JSON records to an append-only `.jsonl` file and maintains an in-memory ring buffer (`collections.deque`) for fast REST API query responses.
* **Public Classes & Functions:**
  - `DecisionLogger(log_file_path, max_history_records)`:
    - `log_cycle(decision, guardrail_result, execution_result, metrics, error) -> Dict[str, Any]`
    - `get_recent_decisions(limit: int = 50) -> List[Dict[str, Any]]`
    - `clear() -> None`
* **Inputs:** Dicts of `decision`, `guardrail_result`, `execution_result`, `metrics`, and optional `error`.
* **Outputs:** Structured JSON-serializable dictionary.
* **Dependencies:** Pure Python (`json`, `threading`, `collections`, `datetime`, `pathlib`).
* **Error Handling:** File write failures are caught and logged without disrupting the scaling loop. Corrupted lines during preload are skipped gracefully.
* **Logging:** Logs record count preloaded on startup.
* **Existing Tests:** Tested via controller integration and dashboard API tests in [`tests/test_dashboard_api.py`](file:///C:/Users/SRIRAM/design_project/tests/test_dashboard_api.py). (83% coverage).
* **Missing Tests / Gaps:** Concurrency stress test with multiple worker threads logging simultaneously.
