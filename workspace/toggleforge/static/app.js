/**
 * ToggleForge Dashboard – Frontend-Logik.
 * Bindet die statische UI (index.html) an das REST-Backend unter /api/v1 an:
 * Feature Flags CRUD, Live-Evaluator und Audit-Trail.
 */
(() => {
  "use strict";

  const API_BASE = "/api/v1";

  const el = (id) => document.getElementById(id);

  const state = {
    flags: [],
  };

  // ---------------------------------------------------------------------
  // API-Hilfsfunktionen
  // ---------------------------------------------------------------------

  async function apiRequest(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || detail;
      } catch {
        /* Antwort war kein JSON – statusText genügt */
      }
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  const fetchFlags = () => apiRequest("/flags");
  const fetchAuditLogs = () => apiRequest("/audit");
  const createFlag = (payload) =>
    apiRequest("/flags", { method: "POST", body: JSON.stringify(payload) });
  const deleteFlagApi = (key) =>
    apiRequest(`/flags/${encodeURIComponent(key)}`, { method: "DELETE" });
  const updateFlagApi = (key, payload) =>
    apiRequest(`/flags/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  const evaluateFlag = (payload) =>
    apiRequest("/evaluate", { method: "POST", body: JSON.stringify(payload) });

  // ---------------------------------------------------------------------
  // Toasts
  // ---------------------------------------------------------------------

  function showToast(message, kind = "info") {
    const container = el("toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `toast toast-${kind}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  // ---------------------------------------------------------------------
  // Rendering: Stats & System-Status
  // ---------------------------------------------------------------------

  function setSystemStatus(online) {
    const badge = el("system-status");
    const text = el("status-text");
    if (!badge || !text) return;
    badge.classList.toggle("badge-online", online);
    badge.classList.toggle("badge-neutral", !online);
    text.textContent = online ? "Server online" : "Server nicht erreichbar";
  }

  function renderStats() {
    const total = state.flags.length;
    const enabled = state.flags.filter((f) => f.enabled).length;
    const canary = state.flags.filter((f) => f.flag_type === "percentage").length;
    if (el("stat-total-flags")) el("stat-total-flags").textContent = String(total);
    if (el("stat-enabled-flags")) el("stat-enabled-flags").textContent = String(enabled);
    if (el("stat-canary-flags")) el("stat-canary-flags").textContent = String(canary);
  }

  // ---------------------------------------------------------------------
  // Rendering: Flags-Liste
  // ---------------------------------------------------------------------

  function flagTypeLabel(type) {
    return { boolean: "Boolean", percentage: "Percentage Rollout", targeting: "User-Targeting" }[type] || type;
  }

  function renderFlags() {
    const container = el("flags-container");
    const empty = el("flags-empty");
    if (!container) return;

    const searchTerm = (el("flag-search")?.value || "").toLowerCase();
    const typeFilter = el("flag-type-filter")?.value || "all";

    const filtered = state.flags.filter((flag) => {
      const matchesSearch =
        !searchTerm ||
        flag.key.toLowerCase().includes(searchTerm) ||
        flag.name.toLowerCase().includes(searchTerm) ||
        flag.flag_type.toLowerCase().includes(searchTerm);
      const matchesType = typeFilter === "all" || flag.flag_type === typeFilter;
      return matchesSearch && matchesType;
    });

    container.innerHTML = "";
    empty?.classList.toggle("hidden", filtered.length > 0);

    for (const flag of filtered) {
      const card = document.createElement("div");
      card.className = "glass-card flag-card";
      card.innerHTML = `
        <div class="flag-card-header">
          <div>
            <h3 class="flag-key">${escapeHtml(flag.key)}</h3>
            <p class="flag-name">${escapeHtml(flag.name)}</p>
          </div>
          <span class="badge ${flag.enabled ? "badge-success" : "badge-neutral"}">
            ${flag.enabled ? "Aktiviert" : "Deaktiviert"}
          </span>
        </div>
        <div class="flag-card-body">
          <span class="badge badge-type">${escapeHtml(flagTypeLabel(flag.flag_type))}</span>
          ${flag.flag_type === "percentage" ? `<span class="text-muted">${flag.rollout_percentage}% Rollout</span>` : ""}
          ${flag.description ? `<p class="text-muted flag-desc">${escapeHtml(flag.description)}</p>` : ""}
        </div>
        <div class="flag-card-actions">
          <button class="btn btn-secondary btn-sm" data-action="toggle" data-key="${escapeHtml(flag.key)}">
            ${flag.enabled ? "Deaktivieren" : "Aktivieren"}
          </button>
          <button class="btn btn-danger btn-sm" data-action="delete" data-key="${escapeHtml(flag.key)}">Löschen</button>
        </div>
      `;
      container.appendChild(card);
    }
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value ?? "";
    return div.innerHTML;
  }

  function populateEvalFlagSelect() {
    const select = el("eval-flag-key");
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value="">-- Flag auswählen --</option>';
    for (const flag of state.flags) {
      const opt = document.createElement("option");
      opt.value = flag.key;
      opt.textContent = `${flag.key} (${flagTypeLabel(flag.flag_type)})`;
      select.appendChild(opt);
    }
    if (current) select.value = current;
  }

  // ---------------------------------------------------------------------
  // Rendering: Audit-Trail
  // ---------------------------------------------------------------------

  function renderAuditLogs(logs) {
    const body = el("audit-table-body");
    if (!body) return;
    if (!logs.length) {
      body.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted">Keine Audit-Einträge vorhanden.</td></tr>';
      if (el("stat-audit-count")) el("stat-audit-count").textContent = "0";
      return;
    }
    body.innerHTML = logs
      .map(
        (log) => `
        <tr>
          <td>${new Date(log.created_at).toLocaleString("de-DE")}</td>
          <td class="font-mono">${escapeHtml(log.flag_key)}</td>
          <td>${escapeHtml(log.action)}</td>
          <td class="font-mono text-muted">${escapeHtml(log.details || "-")}</td>
          <td>${escapeHtml(log.actor || "system")}</td>
        </tr>`,
      )
      .join("");
    if (el("stat-audit-count")) el("stat-audit-count").textContent = String(logs.length);
  }

  // ---------------------------------------------------------------------
  // Datenladen
  // ---------------------------------------------------------------------

  async function loadFlags() {
    try {
      state.flags = await fetchFlags();
      setSystemStatus(true);
      renderStats();
      renderFlags();
      populateEvalFlagSelect();
    } catch (err) {
      setSystemStatus(false);
      showToast(`Flags konnten nicht geladen werden: ${err.message}`, "error");
    }
  }

  async function loadAuditLogs() {
    try {
      const logs = await fetchAuditLogs();
      renderAuditLogs(logs);
    } catch (err) {
      showToast(`Audit-Log konnte nicht geladen werden: ${err.message}`, "error");
    }
  }

  // ---------------------------------------------------------------------
  // Event-Wiring: Tabs
  // ---------------------------------------------------------------------

  function wireTabs() {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach((b) => {
          b.classList.remove("active");
          b.setAttribute("aria-selected", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");

        const target = btn.dataset.target;
        document.querySelectorAll(".tab-panel").forEach((panel) => {
          panel.classList.toggle("hidden", panel.id !== target);
          panel.classList.toggle("active", panel.id === target);
        });

        if (target === "panel-audit") loadAuditLogs();
      });
    });
  }

  // ---------------------------------------------------------------------
  // Event-Wiring: Modal / Flag-Formular
  // ---------------------------------------------------------------------

  function openModal() {
    el("flag-modal")?.classList.remove("hidden");
  }

  function closeModal() {
    el("flag-modal")?.classList.add("hidden");
    el("flag-form")?.reset();
  }

  function wireModal() {
    el("btn-open-modal")?.addEventListener("click", openModal);
    el("modal-close")?.addEventListener("click", closeModal);
    el("modal-cancel")?.addEventListener("click", closeModal);

    el("flag-type")?.addEventListener("change", (e) => {
      const type = e.target.value;
      el("group-rollout")?.classList.toggle("hidden", type !== "percentage");
      el("group-targeting")?.classList.toggle("hidden", type !== "targeting");
    });

    el("flag-rollout")?.addEventListener("input", (e) => {
      if (el("slider-val-display")) el("slider-val-display").textContent = `${e.target.value}%`;
    });

    el("flag-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const flagType = el("flag-type").value;
      let targetingRules = [];
      if (flagType === "targeting") {
        const raw = el("flag-targeting").value.trim();
        if (raw) {
          try {
            const parsed = JSON.parse(raw);
            targetingRules = parsed.map((rule) => ({
              attribute_name: rule.attribute,
              operator: rule.operator,
              values: rule.value,
              enabled: true,
              priority: 0,
            }));
          } catch {
            showToast("Targeting-Regeln sind kein gültiges JSON.", "error");
            return;
          }
        }
      }

      const payload = {
        key: el("flag-key").value.trim(),
        name: el("flag-name").value.trim() || el("flag-key").value.trim(),
        description: el("flag-desc").value.trim() || null,
        flag_type: flagType,
        enabled: el("flag-enabled").checked,
        rollout_percentage: flagType === "percentage" ? Number(el("flag-rollout").value) : 0,
        targeting_rules: targetingRules,
      };

      try {
        await createFlag(payload);
        showToast(`Flag '${payload.key}' erfolgreich angelegt.`, "success");
        closeModal();
        await loadFlags();
      } catch (err) {
        showToast(`Flag konnte nicht angelegt werden: ${err.message}`, "error");
      }
    });
  }

  // ---------------------------------------------------------------------
  // Event-Wiring: Flags-Liste (Toggle/Delete via Event-Delegation)
  // ---------------------------------------------------------------------

  function wireFlagsList() {
    el("flags-container")?.addEventListener("click", async (e) => {
      const btn = e.target.closest("button[data-action]");
      if (!btn) return;
      const key = btn.dataset.key;
      const flag = state.flags.find((f) => f.key === key);
      if (!flag) return;

      if (btn.dataset.action === "toggle") {
        try {
          await updateFlagApi(key, { enabled: !flag.enabled });
          showToast(`Flag '${key}' ${!flag.enabled ? "aktiviert" : "deaktiviert"}.`, "success");
          await loadFlags();
        } catch (err) {
          showToast(`Aktion fehlgeschlagen: ${err.message}`, "error");
        }
      } else if (btn.dataset.action === "delete") {
        try {
          await deleteFlagApi(key);
          showToast(`Flag '${key}' gelöscht.`, "success");
          await loadFlags();
        } catch (err) {
          showToast(`Löschen fehlgeschlagen: ${err.message}`, "error");
        }
      }
    });

    el("flag-search")?.addEventListener("input", renderFlags);
    el("flag-type-filter")?.addEventListener("change", renderFlags);
  }

  // ---------------------------------------------------------------------
  // Event-Wiring: Evaluator
  // ---------------------------------------------------------------------

  function wireEvaluator() {
    el("eval-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const flagKey = el("eval-flag-key").value;
      const entityId = el("eval-entity-id").value.trim();
      let attributes = {};
      const rawAttrs = el("eval-attributes").value.trim();
      if (rawAttrs) {
        try {
          attributes = JSON.parse(rawAttrs);
        } catch {
          showToast("Attribute/Context ist kein gültiges JSON.", "error");
          return;
        }
      }

      try {
        const result = await evaluateFlag({
          flag_key: flagKey,
          entity_id: entityId,
          attributes,
        });
        const box = el("eval-result-box");
        box?.classList.remove("hidden");
        if (el("eval-badge")) {
          el("eval-badge").textContent = result.enabled ? "Aktiv" : "Inaktiv";
          el("eval-badge").className = `badge ${result.enabled ? "badge-success" : "badge-neutral"}`;
        }
        if (el("eval-status-val")) el("eval-status-val").textContent = result.enabled ? "Aktiv" : "Inaktiv";
        if (el("eval-reason-val")) el("eval-reason-val").textContent = result.reason;
        if (el("eval-raw-json")) el("eval-raw-json").textContent = JSON.stringify(result, null, 2);
      } catch (err) {
        showToast(`Evaluierung fehlgeschlagen: ${err.message}`, "error");
      }
    });
  }

  // ---------------------------------------------------------------------
  // Event-Wiring: Sonstiges
  // ---------------------------------------------------------------------

  function wireGlobal() {
    el("btn-refresh")?.addEventListener("click", loadFlags);
    el("btn-refresh-audit")?.addEventListener("click", loadAuditLogs);
  }

  // ---------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------

  function init() {
    wireTabs();
    wireModal();
    wireFlagsList();
    wireEvaluator();
    wireGlobal();
    loadFlags();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
