// CloudPulse Dashboard Logic
document.addEventListener('DOMContentLoaded', () => {
  const monitorsTableBody = document.getElementById('monitors-tbody') || document.querySelector('#monitors-table tbody');
  const monitorForm = document.getElementById('monitor-form') || document.getElementById('add-monitor-form');
  const totalMonitorsEl = document.getElementById('stat-total') || document.getElementById('total-monitors');
  const upMonitorsEl = document.getElementById('stat-up') || document.getElementById('up-monitors');
  const downMonitorsEl = document.getElementById('stat-down') || document.getElementById('down-monitors');
  const avgLatencyEl = document.getElementById('stat-latency') || document.getElementById('avg-latency');
  const errorMessageEl = document.getElementById('error-message');

  // Hilfsfunktion: Fehlermeldungen anzeigen
  function showError(msg) {
    if (errorMessageEl) {
      errorMessageEl.textContent = msg;
      errorMessageEl.style.display = 'block';
    } else {
      console.error(msg);
    }
  }

  function clearError() {
    if (errorMessageEl) {
      errorMessageEl.textContent = '';
      errorMessageEl.style.display = 'none';
    }
  }

  // Statistiken abrufen
  async function fetchStats() {
    try {
      const res = await fetch('/api/stats');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (totalMonitorsEl) totalMonitorsEl.textContent = data.total ?? 0;
      if (upMonitorsEl) upMonitorsEl.textContent = data.up ?? 0;
      if (downMonitorsEl) downMonitorsEl.textContent = data.down ?? 0;
      if (avgLatencyEl) avgLatencyEl.textContent = `${Math.round(data.avg_latency_ms ?? 0)} ms`;
    } catch (err) {
      console.warn('Statistiken konnten nicht geladen werden:', err);
    }
  }

  // Monitore abrufen
  async function fetchMonitors() {
    try {
      const res = await fetch('/api/monitors');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const monitors = await res.json();
      renderMonitors(monitors);
      clearError();
    } catch (err) {
      showError(`Fehler beim Laden der Monitore: ${err.message}`);
    }
  }

  // Monitore in Tabelle rendern
  function renderMonitors(monitors) {
    if (!monitorsTableBody) return;
    monitorsTableBody.innerHTML = '';

    if (monitors.length === 0) {
      const emptyRow = document.createElement('tr');
      emptyRow.innerHTML = `<td colspan="7" style="text-align:center; padding: 2rem; color: var(--text-muted, #888);">Keine Monitore konfiguriert.</td>`;
      monitorsTableBody.appendChild(emptyRow);
      return;
    }

    monitors.forEach(m => {
      const row = document.createElement('tr');
      let statusBadge = '<span class="badge badge-pending">PENDING</span>';
      if (m.is_up === true) {
        statusBadge = '<span class="badge badge-up">UP</span>';
      } else if (m.is_up === false) {
        statusBadge = '<span class="badge badge-down">DOWN</span>';
      }

      const latency = m.last_latency_ms !== null && m.last_latency_ms !== undefined
        ? `${Math.round(m.last_latency_ms)} ms`
        : '-';

      const lastCheck = m.last_checked_at
        ? new Date(m.last_checked_at).toLocaleTimeString()
        : 'Nie';

      row.innerHTML = `
        <td><strong>${escapeHtml(m.name)}</strong></td>
        <td><code>${escapeHtml(m.url)}</code></td>
        <td>${statusBadge}</td>
        <td>${m.last_status_code ?? '-'}</td>
        <td>${latency}</td>
        <td>${lastCheck}</td>
        <td>
          <button class="btn btn-sm btn-danger delete-btn" data-id="${m.id}" title="Monitor löschen">Löschen</button>
        </td>
      `;
      monitorsTableBody.appendChild(row);
    });

    // Delete Event Listener
    document.querySelectorAll('.delete-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const id = e.target.getAttribute('data-id');
        if (id && confirm(`Monitor #${id} wirklich löschen?`)) {
          await deleteMonitor(id);
        }
      });
    });
  }

  // Monitor löschen
  async function deleteMonitor(id) {
    try {
      const res = await fetch(`/api/monitors/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchMonitors();
      await fetchStats();
    } catch (err) {
      showError(`Fehler beim Löschen des Monitors: ${err.message}`);
    }
  }

  // Monitor erstellen Formular
  if (monitorForm) {
    monitorForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearError();

      const nameInput = document.getElementById('monitor-name') || monitorForm.elements['name'];
      const urlInput = document.getElementById('monitor-url') || monitorForm.elements['url'];
      const intervalInput = document.getElementById('monitor-interval') || monitorForm.elements['interval_seconds'];
      const expectedStatusInput = document.getElementById('monitor-status') || monitorForm.elements['expected_status'];
      const timeoutInput = document.getElementById('monitor-timeout') || monitorForm.elements['timeout'];

      const payload = {
        name: nameInput?.value?.trim() || '',
        url: urlInput?.value?.trim() || '',
        interval_seconds: intervalInput ? parseInt(intervalInput.value, 10) : 60,
        expected_status: expectedStatusInput ? parseInt(expectedStatusInput.value, 10) : 200,
        timeout: timeoutInput ? parseFloat(timeoutInput.value) : 5.0
      };

      try {
        const res = await fetch('/api/monitors', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }

        monitorForm.reset();
        await fetchMonitors();
        await fetchStats();
      } catch (err) {
        showError(`Fehler beim Erstellen des Monitors: ${err.message}`);
      }
    });
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Initialer Abruf & Interval
  fetchMonitors();
  fetchStats();
  setInterval(() => {
    fetchMonitors();
    fetchStats();
  }, 10000);
});
