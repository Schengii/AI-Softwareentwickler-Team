// AegisFlow - Dashboard Client Application
document.addEventListener("DOMContentLoaded", () => {
  const eventsTableBody = document.getElementById("eventsTableBody");
  const eventForm = document.getElementById("eventForm");
  const topicInput = document.getElementById("topicInput");
  const idempotencyKeyInput = document.getElementById("idempotencyKeyInput");
  const payloadInput = document.getElementById("payloadInput");
  const submitBtn = document.getElementById("submitBtn");
  const refreshBtn = document.getElementById("refreshBtn");
  const alertContainer = document.getElementById("alertContainer");
  const topicFilter = document.getElementById("topicFilter");
  const clearFilterBtn = document.getElementById("clearFilterBtn");

  // Metrics
  const metricTotalEvents = document.getElementById("metricTotalEvents");
  const metricTopicsCount = document.getElementById("metricTopicsCount");
  const brokerStatusDot = document.getElementById("brokerStatusDot");
  const brokerStatusText = document.getElementById("brokerStatusText");

  let allEvents = [];

  // Helper: Zeige Nachricht
  function showAlert(message, type = "success") {
    if (!alertContainer) return;
    alertContainer.textContent = message;
    alertContainer.className = `alert-container alert-${type}`;
    alertContainer.style.display = "block";
    setTimeout(() => {
      alertContainer.style.display = "none";
    }, 5000);
  }

  // Update Status
  function setBrokerOnline(online) {
    if (brokerStatusDot && brokerStatusText) {
      if (online) {
        brokerStatusDot.className = "status-indicator online";
        brokerStatusText.textContent = "Verbunden";
      } else {
        brokerStatusDot.className = "status-indicator offline";
        brokerStatusText.textContent = "Getrennt / Offline";
      }
    }
  }

  // Events laden
  async function fetchEvents() {
    try {
      const response = await fetch("/api/v1/events");
      if (!response.ok) {
        throw new Error(`HTTP-Fehler: ${response.status} ${response.statusText}`);
      }
      const data = await response.json();
      allEvents = Array.isArray(data) ? data : (data.items || []);
      setBrokerOnline(true);
      renderEvents();
      updateMetrics();
    } catch (err) {
      setBrokerOnline(false);
      renderEmptyTable("Fehler beim Abrufen der Events: " + (err instanceof Error ? err.message : String(err)));
    }
  }

  // Leere Tabelle rendern
  function renderEmptyTable(text) {
    if (!eventsTableBody) return;
    eventsTableBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">${text}</td></tr>`;
  }

  // Events filtern und anzeigen
  function renderEvents() {
    if (!eventsTableBody) return;

    const filterText = (topicFilter ? topicFilter.value : "").trim().toLowerCase();
    const filtered = allEvents.filter(ev => {
      if (!filterText) return true;
      const topic = (ev.topic || "").toLowerCase();
      return topic.includes(filterText);
    });

    if (filtered.length === 0) {
      renderEmptyTable(allEvents.length === 0 ? "Keine Events vorhanden." : "Keine Events entsprechen dem Filter.");
      return;
    }

    eventsTableBody.innerHTML = filtered.map(ev => {
      const id = ev.id ?? "-";
      const topic = escapeHtml(ev.topic || "unbekannt");
      const idemKey = escapeHtml(ev.idempotency_key || "–");
      const timestamp = ev.created_at ? new Date(ev.created_at).toLocaleString("de-DE") : (ev.timestamp ? new Date(ev.timestamp).toLocaleString("de-DE") : "Jetzt");
      const payloadStr = typeof ev.payload === "object" ? JSON.stringify(ev.payload) : String(ev.payload || "{}");
      const safePayload = escapeHtml(payloadStr);

      return `
        <tr>
          <td><strong>#${id}</strong></td>
          <td><span class="badge badge-topic">${topic}</span></td>
          <td><div class="payload-cell" title="${safePayload}">${safePayload}</div></td>
          <td><code>${idemKey}</code></td>
          <td class="text-muted">${timestamp}</td>
          <td><span class="badge badge-success">Gespeichert</span></td>
        </tr>
      `;
    }).join("");
  }

  // Metriken aktualisieren
  function updateMetrics() {
    if (metricTotalEvents) {
      metricTotalEvents.textContent = String(allEvents.length);
    }
    if (metricTopicsCount) {
      const topics = new Set(allEvents.map(e => e.topic).filter(Boolean));
      metricTopicsCount.textContent = String(topics.size);
    }
  }

  // HTML-Escaping zur XSS-Vermeidung
  function escapeHtml(str) {
    if (typeof str !== "string") return String(str);
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Formular-Submit: Event Ingestion
  if (eventForm) {
    eventForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const topic = (topicInput ? topicInput.value : "").trim();
      const idempotencyKey = (idempotencyKeyInput ? idempotencyKeyInput.value : "").trim();
      const rawPayload = (payloadInput ? payloadInput.value : "").trim();

      if (!topic) {
        showAlert("Bitte ein Topic angeben.", "danger");
        return;
      }

      let parsedPayload;
      try {
        parsedPayload = JSON.parse(rawPayload || "{}");
      } catch (jsonErr) {
        showAlert("Ungültiges JSON im Payload-Feld: " + (jsonErr instanceof Error ? jsonErr.message : String(jsonErr)), "danger");
        return;
      }

      const bodyData = {
        topic: topic,
        payload: parsedPayload
      };
      if (idempotencyKey) {
        bodyData.idempotency_key = idempotencyKey;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Wird übertragen...";
      }

      try {
        const res = await fetch("/api/v1/events", {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(bodyData)
        });

        if (!res.ok) {
          const errorData = await res.json().catch(() => ({}));
          const errMsg = errorData.detail || `Serverfehler (${res.status})`;
          throw new Error(errMsg);
        }

        const result = await res.json();
        showAlert(`Event erfolgreich veröffentlicht (ID: ${result.id || "neu"})!`, "success");

        // Formular zurücksetzen (außer Topic für einfache Mehrfacheingabe)
        if (idempotencyKeyInput) idempotencyKeyInput.value = "";
        
        // Liste neu laden
        await fetchEvents();
      } catch (err) {
        showAlert("Fehler beim Senden des Events: " + (err instanceof Error ? err.message : String(err)), "danger");
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "⚡ Event senden";
        }
      }
    });
  }

  // Filter & Refresh Listener
  if (topicFilter) {
    topicFilter.addEventListener("input", () => renderEvents());
  }

  if (clearFilterBtn) {
    clearFilterBtn.addEventListener("click", () => {
      if (topicFilter) {
        topicFilter.value = "";
        renderEvents();
      }
    });
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      fetchEvents();
    });
  }

  // Initiales Laden
  fetchEvents();
});
