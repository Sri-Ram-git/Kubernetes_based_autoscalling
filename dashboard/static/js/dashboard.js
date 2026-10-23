/**
 * Kubernetes Auto-Scaling Framework - Review-Ready Dashboard Logic
 * Project ID: 357 | Alliance University, Bengaluru
 * Algorithm: PRAH (Priority-based Rule Arbitration with Hysteresis)
 */

let pollInterval = null;
let isFetching = false;
let currentLiveStatus = false;
let pendingModalAction = null;
let isSimulationModeActive = false;

document.addEventListener("DOMContentLoaded", () => {
  loadUiOverrides();
  ensureWorkloadControls();
  fetchAllData();

  // Poll every 3 seconds
  startPolling();

  // Pause polling when browser tab is hidden to prevent resource thrashing
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopPolling();
    } else {
      fetchAllData();
      startPolling();
    }
  });
});

function loadUiOverrides() {
  if (document.querySelector('link[data-kubepilot-ui-overrides]')) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/static/css/ui-overrides.css";
  link.dataset.kubepilotUiOverrides = "true";
  document.head.appendChild(link);
}

function ensureWorkloadControls() {
  const table = document.getElementById("pod-table");
  if (!table || document.getElementById("workload-control-panel")) return;
  const panel = document.createElement("section");
  panel.id = "workload-control-panel";
  panel.className = "panel control-panel";
  panel.innerHTML = `<div class="panel-header"><div><div class="eyebrow">Guarded manual operation</div><h2>Request replica change</h2><p class="panel-subtitle">Requests pass through the controller guardrails and require a verified Kubernetes connection.</p></div></div><form id="manual-scale-form" class="control-stack"><label for="manual-target-replicas">Target replicas</label><input id="manual-target-replicas" type="number" min="1" max="100" step="1" required><button class="btn btn-danger" id="btn-manual-scale" type="submit">Request guarded scale</button><p id="manual-scale-status" class="control-note" role="status">No operation submitted.</p></form>`;
  panel.querySelector("#manual-scale-form").addEventListener("submit", requestWorkloadScale);
  table.closest(".panel").insertAdjacentElement("afterend", panel);
}

function startPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(fetchAllData, 3000);
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

async function triggerManualRefresh() {
  const btn = document.getElementById("btn-manual-refresh");
  if (btn) btn.classList.add("spinning");
  await fetchAllData();
  if (btn) btn.classList.remove("spinning");
}

async function fetchAllData() {
  if (isFetching) return;
  isFetching = true;

  try {
    await Promise.all([
      fetchStatus(),
      fetchMetrics(),
      fetchDecisions(),
      fetchPolicies(),
      fetchHistory(),
    ]);

    // Update refresh timestamp
    const now = new Date();
    const timeStr = now.toLocaleTimeString();
    const refreshEl = document.getElementById("last-refresh-time");
    if (refreshEl) refreshEl.textContent = `Refreshed: ${timeStr}`;

  } catch (err) {
    console.error("Dashboard synchronization error:", err);
  } finally {
    isFetching = false;
  }
}

async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();
    const targetContext = document.getElementById("target-context");
    if (targetContext) targetContext.textContent = `${data.target.namespace} / ${data.target.deployment}`;

    // 1. K8s pill
    const k8sPill = document.getElementById("badge-k8s");
    const k8sText = document.getElementById("k8s-status-text");
    const k8sSource = document.getElementById("k8s-source-tag");

    if (data.connectivity.kubernetes.connected) {
      k8sPill.className = "status-pill pill-success";
      k8sText.textContent = "Connected";
      if (k8sSource) k8sSource.textContent = "Source: Kubernetes API (Live)";
      const clusterStatus = document.getElementById("cluster-status-value");
      if (clusterStatus) clusterStatus.textContent = "Connected";
    } else {
      k8sPill.className = "status-pill pill-danger";
      k8sText.textContent = "Offline";
      if (k8sSource) k8sSource.textContent = "Source: Offline (Local Mode)";
      const clusterStatus = document.getElementById("cluster-status-value");
      if (clusterStatus) clusterStatus.textContent = "Offline";
    }
    const healthK8s = document.getElementById("health-k8s-detail");
    if (healthK8s) healthK8s.textContent = data.connectivity.kubernetes.connected ? "Connected" : `Unavailable — ${data.connectivity.kubernetes.message || "connection failed"}`;

    // 2. Prometheus pill
    const promPill = document.getElementById("badge-prom");
    const promText = document.getElementById("prom-status-text");
    const promEndpoint = document.getElementById("telemetry-endpoint-tag");
    const dotProm = document.getElementById("dot-prom");
    const dotTargets = document.getElementById("dot-targets");
    const dotK8s = document.getElementById("dot-k8s");

    if (data.connectivity.prometheus.connected) {
      promPill.className = "status-pill pill-success";
      promText.textContent = "Online";
      if (promEndpoint) promEndpoint.textContent = data.connectivity.prometheus.url || "http://localhost:9090";
      if (dotProm) dotProm.className = "status-dot success";
    } else {
      promPill.className = "status-pill pill-danger";
      promText.textContent = "Offline";
      if (promEndpoint) promEndpoint.textContent = "Endpoint Unreachable";
      if (dotProm) dotProm.className = "status-dot danger";
    }

    if (dotK8s) dotK8s.className = `status-dot ${data.connectivity.kubernetes.connected ? 'success' : 'danger'}`;

    const healthProm = document.getElementById("health-prom-detail");
    if (healthProm) healthProm.textContent = data.connectivity.prometheus.connected ? `Online — Reachable at ${data.connectivity.prometheus.url || "http://localhost:9090"}` : `Unavailable — ${data.connectivity.prometheus.message || "connection failed"}`;
    
    const healthTargets = document.getElementById("health-targets-detail");
    if (healthTargets) {
      const healthy = data.connectivity.prometheus.healthy_targets || 0;
      const total = data.connectivity.prometheus.total_targets || 0;
      healthTargets.textContent = `${healthy} of ${total} scrape targets UP`;
      if (dotTargets) dotTargets.className = `status-dot ${healthy > 0 ? 'success' : (total > 0 ? 'danger' : 'warning')}`;
    }

    const healthLastCheck = document.getElementById("health-last-check");
    if (healthLastCheck) healthLastCheck.textContent = `Last diagnostics check: ${new Date().toLocaleTimeString()}`;

    const healthMode = document.getElementById("health-mode-detail");
    if (healthMode) healthMode.textContent = data.mode;

    // 3. Operational mode pill
    const modePill = document.getElementById("badge-mode");
    const modeText = document.getElementById("mode-status-text");
    const btnToggle = document.getElementById("btn-toggle-live");
    currentLiveStatus = data.enable_live_execution;

    if (data.enable_live_execution && !data.dry_run) {
      modePill.className = "status-pill pill-live";
      modeText.textContent = "LIVE EXECUTION";
      if (btnToggle) { btnToggle.textContent = "Disable Live Execution (Switch to Dry-Run)"; btnToggle.className = "btn btn-secondary"; }
    } else {
      modePill.className = "status-pill pill-dry-run";
      modeText.textContent = "DRY RUN (Preview)";
      if (btnToggle) { btnToggle.textContent = "Enable Live Execution (Caution)"; btnToggle.className = "btn btn-warning"; }
    }

    // 4. Global Simulation Banner
    isSimulationModeActive = data.simulation_mode;
    const banner = document.getElementById("global-mode-banner");
    if (banner) {
      if (data.simulation_mode) {
        banner.classList.remove("hidden");
      } else {
        banner.classList.add("hidden");
      }
    }

    // 5. Workload stats
    const desiredEl = document.getElementById("stat-desired-replicas");
    const currentEl = document.getElementById("stat-current-replicas");
    const readyEl = document.getElementById("stat-ready-replicas");
    const unavailableEl = document.getElementById("stat-unavail-replicas");
    if (desiredEl) desiredEl.textContent = data.connectivity.kubernetes.connected && data.target.desired_replicas != null ? data.target.desired_replicas : "Unavailable";
    if (currentEl) currentEl.textContent = data.connectivity.kubernetes.connected && data.target.current_replicas != null ? data.target.current_replicas : "Unavailable";
    if (readyEl) readyEl.textContent = data.connectivity.kubernetes.connected && data.target.ready_replicas != null ? data.target.ready_replicas : "Unavailable";
    if (unavailableEl) unavailableEl.textContent = data.connectivity.kubernetes.connected && data.target.desired_replicas != null && data.target.ready_replicas != null ? Math.max(0, data.target.desired_replicas - data.target.ready_replicas) : "Unknown";
    const healthStatus = document.getElementById("health-status-value");
    if (healthStatus) healthStatus.textContent = data.connectivity.kubernetes.connected && data.target.ready_replicas != null ? `${data.target.ready_replicas} ready` : "Unavailable";
    const boundsEl = document.getElementById("stat-bounds");
    const workloadMsg = document.getElementById("workload-msg");
    const workloadTag = document.getElementById("workload-tag");
    if (boundsEl) boundsEl.textContent = `${data.guardrails.min_replicas} – ${data.guardrails.max_replicas}`;
    if (workloadMsg) workloadMsg.textContent = data.target.status_message || "";
    if (workloadTag) workloadTag.textContent = `${data.target.namespace} / ${data.target.deployment}`;

    // 6. Pod list inspection
    const podBody = document.getElementById("pod-table-body");
    if (!podBody) return;
    const podBadge = document.getElementById("pod-count-badge");
    const pods = data.target.pods || [];

    if (podBadge) podBadge.textContent = `${pods.length} pod(s)`;

    if (pods.length === 0) {
      podBody.innerHTML = `<tr><td colspan="5" class="empty-state">${data.connectivity.kubernetes.connected ? 'No active pods found matching selector app=' + data.target.deployment : 'Cluster offline. Pod inspection suspended.'}</td></tr>`;
    } else {
      podBody.innerHTML = pods.map(p => `
        <tr>
          <td class="font-mono"><small>${escapeHtml(p.name)}</small></td>
          <td><span class="badge ${p.phase === 'Running' ? 'badge-accent' : ''}">${escapeHtml(p.phase)}</span></td>
          <td><span class="${p.ready ? 'text-success' : 'text-danger'} font-mono">${p.ready ? '&#10003; Ready' : '&#10007; Not Ready'}</span></td>
          <td class="font-mono">${p.restarts}</td>
          <td><small class="font-mono">${escapeHtml(p.node || 'unassigned')}</small></td>
        </tr>
      `).join("");
    }

  } catch (e) {
    console.error("fetchStatus error:", e);
  }
}

async function fetchMetrics() {
  try {
    const res = await fetch("/api/metrics");
    if (!res.ok) return;
    const data = await res.json();
    const metrics = data.metrics || {};
    if (!document.getElementById("val-cpu")) return;

    const sourceBadge = document.getElementById("telemetry-source-badge");
    if (sourceBadge) {
      sourceBadge.textContent = data.source;
      if (data.source === "SIMULATED") {
        sourceBadge.className = "badge badge-accent";
      } else {
        sourceBadge.className = "badge";
      }
    }

    // CPU
    updateMetricCard("cpu", metrics["cpu_utilization_percent"], "%", 100);
    // Memory
    updateMetricCard("mem", metrics["memory_utilization_percent"], "%", 100);
    // RPS
    updateMetricCard("rps", metrics["http_requests_per_second"], "req/s", 200);

    // Scrape Targets Table Rendering
    const targetsBody = document.getElementById("targets-table-body");
    const targetsBadge = document.getElementById("targets-count-badge");
    const targetsSummary = data.targets_summary || {};
    const targets = targetsSummary.targets || [];

    if (targetsBadge) {
      if (targetsSummary.reachable) {
        targetsBadge.textContent = `${targetsSummary.healthy_targets}/${targetsSummary.total_targets} Targets UP`;
        targetsBadge.className = targetsSummary.healthy_targets > 0 ? "badge badge-accent" : "badge";
      } else {
        targetsBadge.textContent = "Prometheus unreachable";
        targetsBadge.className = "badge";
      }
    }

    if (targetsBody) {
      if (!targetsSummary.reachable) {
        targetsBody.innerHTML = `<tr><td colspan="5" class="empty-state">Prometheus unreachable (${escapeHtml(targetsSummary.error || "Connection failed")})</td></tr>`;
      } else if (targets.length === 0) {
        targetsBody.innerHTML = `<tr><td colspan="5" class="empty-state">No scrape targets configured in Prometheus</td></tr>`;
      } else {
        targetsBody.innerHTML = targets.map(t => {
          const isUp = t.health === "up";
          const lastTime = t.last_scrape ? t.last_scrape.split(".")[0].replace("T", " ") : "Never";
          return `
            <tr>
              <td><strong>${escapeHtml(t.job)}</strong></td>
              <td class="font-mono"><small>${escapeHtml(t.scrape_url || t.instance)}</small></td>
              <td><span class="badge ${isUp ? 'badge-accent' : ''}">${isUp ? '● UP' : '○ ' + escapeHtml(t.health.toUpperCase())}</span></td>
              <td class="font-mono"><small>${escapeHtml(lastTime)}</small></td>
              <td><small class="${isUp ? 'text-success' : 'text-danger'}">${escapeHtml(t.last_error || 'Healthy (Scraping successful)')}</small></td>
            </tr>
          `;
        }).join("");
      }
    }

    // Warning banner check
    const warningBox = document.getElementById("telemetry-warning");
    const warningText = document.getElementById("telemetry-warning-text");
    const freshnessMsg = document.getElementById("telemetry-freshness-msg");

    const degraded = Object.entries(metrics).filter(([_, m]) => m.status === "MISSING" || m.status === "STALE" || m.status === "ERROR" || m.status === "UNAVAILABLE" || m.status === "INVALID");

    if (degraded.length > 0) {
      if (warningBox) warningBox.classList.remove("hidden");
      if (warningText) warningText.textContent = `Telemetry degraded: ${degraded.map(([k, m]) => `${k} [${m.status}]`).join(", ")}. Safe fallback HOLD triggered.`;
      if (freshnessMsg) freshnessMsg.textContent = "Telemetry status degraded. Autoscaler fallback is holding replica counts.";
    } else {
      if (warningBox) warningBox.classList.add("hidden");
      if (freshnessMsg) {
        if (data.source === "SIMULATED") {
          freshnessMsg.textContent = "Telemetry Source: Injected simulation dataset (deterministic testing).";
        } else {
          freshnessMsg.textContent = "Telemetry Source: Verified real-time Prometheus HTTP scrape vector.";
        }
      }
    }

  } catch (e) {
    console.error("fetchMetrics error:", e);
  }
}

function updateMetricCard(prefix, metricObj, defaultUnit, scaleMax) {
  const numEl = document.getElementById(`val-${prefix}`);
  const fillEl = document.getElementById(`fill-${prefix}`);
  const statusEl = document.getElementById(`status-${prefix}`);
  const freshnessEl = document.getElementById(`freshness-${prefix}`);
  const unitEl = document.getElementById(`unit-${prefix}`);

  const unit = (metricObj && metricObj.unit) ? metricObj.unit : defaultUnit;
  if (unitEl) unitEl.textContent = unit;

  if (!metricObj || metricObj.value === null || metricObj.value === undefined) {
    if (numEl) {
      numEl.textContent = "Unavailable";
      numEl.style.fontSize = "1.05rem";
    }
    if (fillEl) fillEl.style.width = "0%";
    if (statusEl) {
      statusEl.textContent = metricObj ? metricObj.status : "MISSING";
      statusEl.className = "metric-status-tag missing";
    }
    if (freshnessEl) {
      freshnessEl.textContent = metricObj && metricObj.error_message ? metricObj.error_message : "Telemetry unavailable";
    }
    return;
  }

  const val = metricObj.value;
  if (numEl) {
    numEl.style.fontSize = "1.6rem";
    numEl.textContent = unitEl ? val.toFixed(1) : `${val.toFixed(1)} ${unit}`;
  }

  const pct = Math.min(100, Math.max(0, (val / scaleMax) * 100));
  if (fillEl) fillEl.style.width = `${pct}%`;

  if (statusEl) {
    statusEl.textContent = metricObj.status;
    if (metricObj.status === "VALID") {
      statusEl.className = "metric-status-tag";
    } else if (metricObj.status === "SIMULATED") {
      statusEl.className = "metric-status-tag simulated";
    } else if (metricObj.status === "STALE") {
      statusEl.className = "metric-status-tag stale";
    } else {
      statusEl.className = "metric-status-tag missing";
    }
  }

  if (freshnessEl) {
    const age = metricObj.freshness_seconds != null ? `${metricObj.freshness_seconds.toFixed(1)}s` : (metricObj.age_seconds != null ? `${metricObj.age_seconds.toFixed(1)}s` : '--');
    freshnessEl.textContent = `Sample age: ${age} · Source: ${metricObj.source || 'prometheus'}`;
  }
}

async function refreshTelemetryManual() {
  const btn = document.getElementById("btn-refresh-telemetry");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Querying Prometheus...";
  }
  try {
    const res = await fetch("/api/telemetry/refresh", { method: "POST" });
    if (res.ok) {
      await fetchAllData();
    }
  } catch (e) {
    console.error("Telemetry refresh error:", e);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "↻ Query Prometheus";
    }
  }
}

async function fetchDecisions() {
  try {
    const res = await fetch("/api/decisions");
    if (!res.ok) return;
    const data = await res.json();
    const d = data.decision;
    const g = data.guardrail;
    if (!document.getElementById("decision-action-badge")) return;

    const actionBadge = document.getElementById("decision-action-badge");
    const cooldownPill = document.getElementById("cooldown-indicator");

    if (!d) {
      actionBadge.textContent = "IDLE";
      actionBadge.className = "action-badge badge-hold";
      return;
    }

    if (d.cooldown_active) {
      actionBadge.textContent = `BLOCKED BY COOLDOWN (${d.cooldown_remaining_seconds ? d.cooldown_remaining_seconds.toFixed(0) + 's' : 'ACTIVE'})`;
      actionBadge.className = "action-badge badge-warning";
    } else if (g && g.action === "REJECTED") {
      actionBadge.textContent = "GUARDRAIL REJECTED";
      actionBadge.className = "action-badge badge-danger";
    } else if (d.action === "HOLD" && !d.selected_policy_id) {
      actionBadge.textContent = "NO POLICY MATCHED";
      actionBadge.className = "action-badge badge-hold";
    } else if (d.action === "SCALE_OUT") {
      actionBadge.textContent = "SCALE_OUT";
      actionBadge.className = "action-badge badge-scale-out";
    } else if (d.action === "SCALE_IN") {
      actionBadge.textContent = "SCALE_IN";
      actionBadge.className = "action-badge badge-scale-in";
    } else {
      actionBadge.textContent = d.action || "HOLD";
      actionBadge.className = "action-badge badge-hold";
    }

    if (d.cooldown_active) {
      cooldownPill.textContent = `Cooldown: ${d.cooldown_remaining_seconds.toFixed(1)}s remaining`;
      cooldownPill.className = "cooldown-pill active";
    } else {
      cooldownPill.textContent = "Cooldown: Inactive";
      cooldownPill.className = "cooldown-pill";
    }

    document.getElementById("decision-policy").textContent = d.selected_policy_name || "NO POLICY MATCHED";
    document.getElementById("decision-priority").textContent = d.priority || 0;
    document.getElementById("decision-delta").textContent = d.proposed_replica_delta >= 0 ? `+${d.proposed_replica_delta}` : `${d.proposed_replica_delta}`;
    document.getElementById("decision-target").textContent = d.target_replicas;
    document.getElementById("decision-explanation").textContent = d.explanation;

    const guardrailText = document.getElementById("guardrail-status-text");
    if (g) {
      if (g.action === "EXECUTE") {
        guardrailText.textContent = `Approved (Target: ${g.authorized_target_replicas})`;
        guardrailText.style.color = "var(--color-success)";
      } else if (g.action === "REJECTED") {
        guardrailText.textContent = `Rejected: ${g.rejection_reason || 'Boundary exceeded'}`;
        guardrailText.style.color = "var(--color-danger)";
      } else {
        guardrailText.textContent = `HOLD: ${g.authorization_note || 'Maintained'}`;
        guardrailText.style.color = "var(--text-muted)";
      }
    }

    // Populate competing proposals with properly mapped columns
    const proposalsBody = document.getElementById("proposals-table-body");
    const proposals = d.competing_proposals || [];
    if (proposals.length === 0) {
      proposalsBody.innerHTML = `<tr><td colspan="7" class="empty-state">NO POLICY MATCHED — Workload operating within nominal parameters.</td></tr>`;
    } else {
      proposalsBody.innerHTML = proposals.map(p => `
        <tr>
          <td><span class="badge font-mono">${p.priority}</span></td>
          <td><strong>${escapeHtml(p.policy_name)}</strong></td>
          <td><span class="font-mono ${p.action === 'SCALE_OUT' ? 'highlight' : ''}">${p.action}</span></td>
          <td class="font-mono">${p.replica_delta >= 0 ? '+' : ''}${p.replica_delta}</td>
          <td class="font-mono">${p.observed_value !== null && p.observed_value !== undefined ? Number(p.observed_value).toFixed(1) : '--'}</td>
          <td class="font-mono">${p.threshold !== null && p.threshold !== undefined ? p.threshold : '--'}</td>
          <td><small>${escapeHtml(p.reason || '')}</small></td>
        </tr>
      `).join("");
    }

  } catch (e) {
    console.error("fetchDecisions error:", e);
  }
}

async function fetchPolicies() {
  try {
    const res = await fetch("/api/policies");
    if (!res.ok) return;
    const data = await res.json();
    const policies = data.policies || [];
    const evaluations = data.evaluations || [];
    if (!document.getElementById("policies-table-body")) return;
    const fileLabel = document.getElementById("policy-file-label");
    if (fileLabel) fileLabel.textContent = data.policy_file || "";

    const tbody = document.getElementById("policies-table-body");
    if (policies.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" class="empty-state">No policies found.</td></tr>`;
      return;
    }

    const evalMap = {};
    evaluations.forEach(e => { evalMap[e.policy_id] = e; });

    tbody.innerHTML = policies.map(p => {
      const ev = evalMap[p.id];
      let statusHtml = '<small class="text-muted">Awaiting cycle</small>';
      if (ev) {
        if (ev.matched) {
          statusHtml = `<span class="policy-status policy-status-match">&#10003; MATCHED</span><br><small title="${escapeHtml(ev.reason)}">${escapeHtml(ev.reason)}</small>`;
        } else if (!ev.evaluable) {
          statusHtml = `<span class="policy-status policy-status-warning">&#9888; UNEVALUABLE</span><br><small title="${escapeHtml(ev.reason)}">${escapeHtml(ev.reason)}</small>`;
        } else {
          statusHtml = `<span class="policy-status policy-status-muted">NOT BREACHED</span><br><small class="text-muted" title="${escapeHtml(ev.reason)}">${escapeHtml(ev.reason)}</small>`;
        }
      }

       return `
        <tr>
          <td class="font-mono"><small>${escapeHtml(p.id)}</small></td>
          <td><strong>${escapeHtml(p.name)}</strong></td>
          <td><span class="badge">${p.priority}</span></td>
          <td><small class="font-mono">${escapeHtml(p.metric)}</small></td>
          <td><span class="policy-condition"><span class="operator font-mono">${escapeHtml(p.operator || p.operator_str || "")}</span> <span class="font-mono">${escapeHtml(String(p.threshold))}</span></span></td>
          <td><span class="font-mono ${p.action === 'SCALE_OUT' ? 'text-success' : (p.action === 'SCALE_IN' ? 'text-danger' : '')}">${p.action}</span></td>
          <td class="font-mono">${p.replica_delta >= 0 ? '+' : ''}${p.replica_delta}</td>
          <td>${p.cooldown_seconds}s</td>
          <td>${statusHtml}</td>
          <td class="policy-actions">
            <button class="btn btn-sm btn-quiet" type="button" onclick='editPolicy(${JSON.stringify(p)})'>Edit</button>
            <button class="btn btn-sm ${p.enabled ? "btn-warning" : "btn-secondary"}" type="button" onclick="togglePolicy('${escapeHtml(p.id)}', ${!p.enabled})">${p.enabled ? "Disable" : "Enable"}</button>
          </td>
        </tr>
      `;
    }).join("");
  } catch (e) {
    console.error("fetchPolicies error:", e);
  }
}

function editPolicy(policy) {
  document.getElementById("policy-edit-id").value = policy.id;
  document.getElementById("policy-id").value = policy.id;
  document.getElementById("policy-id").disabled = true;
  document.getElementById("policy-name").value = policy.name || "";
  document.getElementById("policy-metric").value = policy.metric;
  document.getElementById("policy-operator").value = policy.operator || policy.operator_str || ">";
  document.getElementById("policy-threshold").value = policy.threshold;
  document.getElementById("policy-priority").value = policy.priority;
  document.getElementById("policy-action").value = policy.action;
  document.getElementById("policy-delta").value = policy.replica_delta;
  document.getElementById("policy-duration").value = policy.duration_seconds;
  document.getElementById("policy-cooldown").value = policy.cooldown_seconds;
  document.getElementById("policy-description").value = policy.description || "";
  document.getElementById("policy-enabled").checked = policy.enabled !== false;
  document.getElementById("policy-save-btn").textContent = "Save policy";
  document.getElementById("policy-editor").scrollIntoView({ behavior: "smooth", block: "center" });
}

function resetPolicyEditor() {
  const form = document.getElementById("policy-editor");
  if (!form) return;
  form.reset();
  document.getElementById("policy-edit-id").value = "";
  document.getElementById("policy-id").disabled = false;
  document.getElementById("policy-save-btn").textContent = "Create policy";
  document.getElementById("policy-editor-status").textContent = "";
}

function policyPayload() {
  return {
    id: document.getElementById("policy-id").value.trim(),
    name: document.getElementById("policy-name").value.trim(),
    description: document.getElementById("policy-description").value.trim(),
    metric: document.getElementById("policy-metric").value,
    operator: document.getElementById("policy-operator").value,
    threshold: Number(document.getElementById("policy-threshold").value),
    priority: Number(document.getElementById("policy-priority").value),
    action: document.getElementById("policy-action").value,
    replica_delta: Number(document.getElementById("policy-delta").value),
    duration_seconds: Number(document.getElementById("policy-duration").value),
    cooldown_seconds: Number(document.getElementById("policy-cooldown").value),
    enabled: document.getElementById("policy-enabled").checked,
  };
}

async function savePolicy(event) {
  event.preventDefault();
  const status = document.getElementById("policy-editor-status");
  const id = document.getElementById("policy-edit-id").value;
  const btn = document.getElementById("policy-save-btn");
  btn.disabled = true;
  status.textContent = "Validating and saving…";
  try {
    const res = await fetch(id ? `/api/policies/${encodeURIComponent(id)}` : "/api/policies", {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(policyPayload()),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Policy was not saved");
    status.textContent = `Confirmed saved: ${data.policy.id} (${data.policy.enabled ? "enabled" : "disabled"}).`;
    resetPolicyEditor();
    await fetchAllData();
  } catch (error) {
    status.textContent = `Not saved: ${error.message}`;
  } finally {
    btn.disabled = false;
  }
}

async function togglePolicy(policyId, enabled) {
  if (!window.confirm(`${enabled ? "Enable" : "Disable"} policy ${policyId}?`)) return;
  try {
    const res = await fetch(`/api/policies/${encodeURIComponent(policyId)}/enabled`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Policy state was not changed");
    await fetchAllData();
  } catch (error) {
    window.alert(error.message);
  }
}

async function fetchHistory() {
  try {
    const res = await fetch("/api/history?limit=30");
    if (!res.ok) return;
    const data = await res.json();
    const records = data.records || [];
    const tbody = document.getElementById("history-table-body");
    if (!tbody) return;
    const histBadge = document.getElementById("history-count-badge");
    if (histBadge) histBadge.textContent = `${records.length} records`;

    const isHistoryPage = !!document.getElementById("history-table");

    if (records.length === 0) {
      tbody.innerHTML = isHistoryPage
        ? `<tr><td colspan="7" class="empty-state">No execution records logged yet.</td></tr>`
        : `<tr><td colspan="5" class="empty-state">No verified decision records loaded.</td></tr>`;
      return;
    }

    tbody.innerHTML = records.map(r => {
      const d = r.decision || {};
      const g = r.guardrail || {};
      const e = r.execution || {};
      const ts = r.timestamp ? r.timestamp.replace("T", " ").substring(11, 19) : "--";

      const mode = r.mode || (g.is_dry_run ? "DRY_RUN" : "LIVE");
      const isDry = mode === "DRY_RUN";
      const action = r.proposed_action || d.action || "HOLD";
      const status = r.status || (e.success ? (isDry ? "DRY_RUN" : "VERIFIED") : (g.action === "REJECTED" ? "BLOCKED" : "HOLD"));
      const policyId = r.policy_id || d.selected_policy_id || "Nominal";
      const explanation = r.explanation || e.message || d.explanation || g.authorization_note || "";

      let statusClass = "badge";
      if (status === "VERIFIED") statusClass = "badge badge-success";
      else if (status === "BLOCKED") statusClass = "badge badge-warning";
      else if (status === "FAILED") statusClass = "badge badge-danger";
      else if (status === "DRY_RUN") statusClass = "badge badge-accent";
      else if (status === "EXECUTED") statusClass = "badge badge-accent";

      let actionClass = "badge";
      if (action === "SCALE_OUT") actionClass = "badge badge-accent";
      else if (action === "SCALE_IN") actionClass = "badge badge-scale-in";

      const prev = r.previous_replicas ?? d.current_replicas ?? "-";
      let repStr = `${prev}`;
      if (action !== "HOLD") {
        if (isDry) {
          repStr = `${prev} &rarr; ${r.requested_replicas ?? d.target_replicas ?? '-'} <small class="text-muted">(preview)</small>`;
        } else if (status === "VERIFIED") {
          repStr = `${prev} &rarr; ${r.resulting_replicas ?? e.confirmed_replicas ?? '-'}`;
        } else {
          repStr = `${prev} &rarr; ${r.requested_replicas ?? d.target_replicas ?? '-'}`;
        }
      }

      if (isHistoryPage) {
        return `
          <tr>
            <td class="font-mono"><small>${ts}</small></td>
            <td><span class="${actionClass}">${action}</span></td>
            <td class="font-mono">${repStr}</td>
            <td><small class="font-mono">${mode}</small></td>
            <td><small>${escapeHtml(policyId)}</small></td>
            <td><span class="${statusClass}">${status}</span></td>
            <td><small title="${escapeHtml(explanation)}">${escapeHtml(explanation.substring(0, 85))}${explanation.length > 85 ? '…' : ''}</small></td>
          </tr>
        `;
      } else {
        return `
          <tr>
            <td class="font-mono"><small>${ts}</small></td>
            <td><span class="${actionClass}">${action}</span></td>
            <td><small class="font-mono">${mode}</small></td>
            <td><small>${escapeHtml(policyId)}</small></td>
            <td><span class="${statusClass}" style="margin-right: 6px;">${status}</span><small title="${escapeHtml(explanation)}">${escapeHtml(explanation.substring(0, 60))}${explanation.length > 60 ? '…' : ''}</small></td>
          </tr>
        `;
      }
    }).join("");
  } catch (e) {
    console.error("fetchHistory error:", e);
  }
}

// ==============================================================================
async function requestWorkloadScale(event) {
  event.preventDefault();
  const target = Number(document.getElementById("manual-target-replicas").value);
  const status = document.getElementById("manual-scale-status");
  const button = document.getElementById("btn-manual-scale");
  if (!status || !button) return;
  if (!Number.isInteger(target) || target < 1) { status.textContent = "Target replicas must be a positive integer."; return; }
  if (!window.confirm(`Request a guarded scale operation to ${target} replicas?`)) return;
  button.disabled = true; status.textContent = "Submitting to the controller…";
  try {
    const res = await fetch("/api/workloads/scale", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target_replicas: target }) });
    const data = await res.json().catch(() => ({ error: `Backend returned HTTP ${res.status} without JSON` }));
    if (!res.ok) {
      const detail = data.error || data.execution?.error || data.execution?.message || `HTTP ${res.status}`;
      throw new Error(detail);
    }
    const workload = data.workload || {};
    const stateText = workload.connected
      ? `Verified state: desired ${workload.desired_replicas}, observed ${workload.current_replicas}, ready ${workload.ready_replicas}.`
      : "Kubernetes state could not be verified.";
    const outcome = data.applied ? "Kubernetes state applied and verified." : "No Kubernetes mutation was applied.";
    status.textContent = `${data.execution?.message || "Controller completed the request."} ${outcome} ${stateText}`;
    await fetchAllData();
  } catch (error) { status.textContent = `Operation not completed: ${error.message}`; }
  finally { button.disabled = false; }
}

// Interactive Control Handlers
// ==============================================================================

async function triggerEvaluation() {
  const btn = document.getElementById("btn-eval");
  btn.disabled = true;
  btn.textContent = "Evaluating...";
  try {
    const res = await fetch("/api/evaluate", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      await fetchAllData();
    } else {
      alert(data.error || "Evaluation did not complete.");
    }
  } catch (e) {
    alert("Evaluation trigger failed: " + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<span class="icon">&#9658;</span> Trigger Evaluation Cycle`;
  }
}

function promptToggleLive() {
  const modal = document.getElementById("modal-confirm");
  const modalTitle = document.getElementById("modal-title");
  const modalText = document.getElementById("modal-body-text");
  const confirmBtn = document.getElementById("modal-confirm-btn");

  if (!currentLiveStatus) {
    modalTitle.textContent = "Confirm LIVE CLUSTER Execution";
    modalText.innerHTML = `
      Are you sure you want to enable <strong>LIVE EXECUTION</strong>?
      <br><br>
      This will authorize the framework to issue real Kubernetes API patch commands to modify Deployment replicas.
    `;
    confirmBtn.className = "btn btn-danger";
    confirmBtn.textContent = "Enable Live Execution";
    pendingModalAction = true;
  } else {
    modalTitle.textContent = "Switch to Safe DRY-RUN Mode";
    modalText.innerHTML = `
      Switch controller back to <strong>DRY-RUN PREVIEW</strong> mode?
      <br><br>
      Cluster mutations will be safely simulated without issuing live Kubernetes API writes.
    `;
    confirmBtn.className = "btn btn-primary";
    confirmBtn.textContent = "Switch to Dry-Run";
    pendingModalAction = false;
  }
  modal.classList.remove("hidden");
}

function closeModal() {
  document.getElementById("modal-confirm").classList.add("hidden");
  pendingModalAction = null;
}

async function executeModalAction() {
  const enable = pendingModalAction;
  closeModal();
  try {
    const res = await fetch("/api/controls/live-execution", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enable }),
    });
    const data = await res.json();
    if (data.success) {
      await fetchAllData();
    } else {
      alert(data.error || "Live execution change was not applied.");
    }
  } catch (e) {
    alert("Toggle failed: " + e.message);
  }
}

async function resetCooldown() {
  try {
    await fetch("/api/controls/reset-cooldown", { method: "POST" });
    await fetchAllData();
  } catch (e) {
    alert("Reset cooldown failed: " + e.message);
  }
}

async function clearSimulationMode() {
  try {
    await fetch("/api/controls/clear-simulation", { method: "POST" });
    await fetchAllData();
  } catch (e) {
    alert("Clear simulation failed: " + e.message);
  }
}

async function injectScenario(scenario) {
  try {
    if (scenario === "HIGH_CPU") {
      await fetch("/api/controls/simulate-metric", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metric_name: "cpu_utilization_percent", value: 85.0 }),
      });
    } else if (scenario === "CRITICAL_CPU") {
      await fetch("/api/controls/simulate-metric", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metric_name: "cpu_utilization_percent", value: 95.0 }),
      });
    } else if (scenario === "EQUAL_PRIORITY_CONFLICT") {
      // High CPU (scale out) and low memory (scale in)
      await fetch("/api/controls/simulate-metric", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metric_name: "cpu_utilization_percent", value: 88.0 }),
      });
      await fetch("/api/controls/simulate-metric", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metric_name: "memory_utilization_percent", value: 20.0 }),
      });
    } else if (scenario === "LOW_CPU") {
      await fetch("/api/controls/simulate-metric", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metric_name: "cpu_utilization_percent", value: 15.0 }),
      });
    } else if (scenario === "MISSING_METRICS") {
      await fetch("/api/controls/simulate-metric", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metric_name: "cpu_utilization_percent", status: "MISSING" }),
      });
    } else if (scenario === "NOMINAL") {
      await fetch("/api/controls/simulate-metric", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metric_name: "cpu_utilization_percent", value: 45.0, status: "SIMULATED" }),
      });
      await fetch("/api/controls/simulate-metric", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metric_name: "memory_utilization_percent", value: 50.0, status: "SIMULATED" }),
      });
    }

    // Trigger immediate evaluation cycle to display outcome
    await triggerEvaluation();

  } catch (e) {
    alert("Scenario injection failed: " + e.message);
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/[&<>'"]/g, tag => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  }[tag] || tag));
}
