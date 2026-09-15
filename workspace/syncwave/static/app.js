/**
 * SyncWave Dashboard Client
 * Real-time event log viewer via WebSocket
 */
(() => {
    'use strict';

    // State
    const state = {
        logs: [],
        filteredLogs: [],
        activeLevel: 'ALL',
        serviceFilter: '',
        searchQuery: '',
        isPaused: false,
        socket: null,
        reconnectTimer: null,
        services: new Set(),
        errorCountLast5Min: 0,
        totalEventsReceived: 0,
        eventTimestamps: []
    };

    // DOM Elements
    const elements = {
        connectionPill: document.getElementById('connection-pill'),
        connectionDot: document.getElementById('connection-dot'),
        connectionStatus: document.getElementById('connection-status'),
        btnPauseStream: document.getElementById('btn-pause-stream'),
        pauseIcon: document.getElementById('pause-icon'),
        pauseLabel: document.getElementById('pause-label'),
        btnClearLogs: document.getElementById('btn-clear-logs'),
        kpiTotalEvents: document.getElementById('kpi-total-events'),
        kpiErrorRate: document.getElementById('kpi-error-rate'),
        kpiRate: document.getElementById('kpi-rate'),
        kpiServicesCount: document.getElementById('kpi-services-count'),
        filterSearch: document.getElementById('filter-search'),
        filterService: document.getElementById('filter-service'),
        levelFilterContainer: document.getElementById('level-filter-container'),
        logStreamView: document.getElementById('log-stream-view'),
        detailModal: document.getElementById('detail-modal'),
        modalServiceName: document.getElementById('modal-service-name'),
        modalCloseBtn: document.getElementById('modal-close-btn'),
        modalPayload: document.getElementById('modal-payload')
    };

    // WebSocket Management
    function initWebSocket() {
        if (state.socket) {
            try {
                state.socket.close();
            } catch {
                // Ignore error on close
            }
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/logs`;

        updateConnectionState('connecting', 'Verbinde...');

        try {
            state.socket = new WebSocket(wsUrl);

            state.socket.onopen = () => {
                updateConnectionState('connected', 'Verbunden');
                if (state.reconnectTimer) {
                    clearTimeout(state.reconnectTimer);
                    state.reconnectTimer = null;
                }
            };

            state.socket.onmessage = (event) => {
                try {
                    const logData = JSON.parse(event.data);
                    handleIncomingLog(logData);
                } catch (err) {
                    console.error('Fehler beim Parsen der WebSocket-Nachricht:', err);
                }
            };

            state.socket.onclose = () => {
                updateConnectionState('disconnected', 'Getrennt');
                scheduleReconnect();
            };

            state.socket.onerror = (err) => {
                console.warn('WebSocket-Verbindungsfehler:', err);
                updateConnectionState('disconnected', 'Fehler');
                try {
                    state.socket.close();
                } catch {
                    // Ignore
                }
            };
        } catch (err) {
            console.error('WebSocket-Initialisierung fehlgeschlagen:', err);
            updateConnectionState('disconnected', 'Fehlgeschlagen');
            scheduleReconnect();
        }
    }

    function scheduleReconnect() {
        if (!state.reconnectTimer) {
            state.reconnectTimer = setTimeout(() => {
                state.reconnectTimer = null;
                initWebSocket();
            }, 3000);
        }
    }

    function updateConnectionState(status, text) {
        if (!elements.connectionDot || !elements.connectionStatus) return;

        elements.connectionDot.className = 'status-dot ' + status;
        elements.connectionStatus.textContent = text;
    }

    // Log Handling
    function handleIncomingLog(log) {
        state.totalEventsReceived++;
        const now = Date.now();
        state.eventTimestamps.push(now);

        // Service erfassen
        if (log.service_name && !state.services.has(log.service_name)) {
            state.services.add(log.service_name);
            updateServiceDropdown();
        }

        // Zu Logliste hinzufügen
        state.logs.unshift(log);
        if (state.logs.length > 500) {
            state.logs.pop();
        }

        updateMetrics();

        // Wenn nicht pausiert, Filter & UI anwenden
        if (!state.isPaused) {
            applyFilters();
        }
    }

    function updateServiceDropdown() {
        if (!elements.filterService) return;
        const currentVal = elements.filterService.value;
        const services = Array.from(state.services).sort();

        elements.filterService.innerHTML = '<option value="">Alle Services</option>';
        services.forEach(svc => {
            const opt = document.createElement('option');
            opt.value = svc;
            opt.textContent = svc;
            if (svc === currentVal) opt.selected = true;
            elements.filterService.appendChild(opt);
        });
    }

    function updateMetrics() {
        const now = Date.now();
        const fiveMinAgo = now - 5 * 60 * 1000;
        const oneSecAgo = now - 1000;

        // Rate berechnen
        state.eventTimestamps = state.eventTimestamps.filter(ts => ts > fiveMinAgo);
        const recentSecondCount = state.eventTimestamps.filter(ts => ts > oneSecAgo).length;

        // Fehlerquote letzte 5 Minuten
        const recentLogs = state.logs.filter(l => {
            if (!l.timestamp) return true;
            const t = new Date(l.timestamp).getTime();
            return isNaN(t) || t > fiveMinAgo;
        });

        const errorLogs = recentLogs.filter(l => l.level === 'ERROR' || l.level === 'FATAL');
        const errorRate = recentLogs.length > 0 ? ((errorLogs.length / recentLogs.length) * 100).toFixed(1) : '0.0';

        if (elements.kpiTotalEvents) elements.kpiTotalEvents.textContent = state.totalEventsReceived.toLocaleString();
        if (elements.kpiErrorRate) elements.kpiErrorRate.textContent = `${errorRate}%`;
        if (elements.kpiRate) elements.kpiRate.innerHTML = `${recentSecondCount.toFixed(1)} <span class="unit">evt/s</span>`;
        if (elements.kpiServicesCount) elements.kpiServicesCount.textContent = state.services.size.toString();
    }

    function applyFilters() {
        const query = state.searchQuery.toLowerCase();
        const service = state.serviceFilter;
        const level = state.activeLevel;

        state.filteredLogs = state.logs.filter(log => {
            if (level !== 'ALL' && log.level !== level) {
                return false;
            }
            if (service && log.service_name !== service) {
                return false;
            }
            if (query) {
                const message = (log.payload || '').toLowerCase();
                const sName = (log.service_name || '').toLowerCase();
                if (!message.includes(query) && !sName.includes(query)) {
                    return false;
                }
            }
            return true;
        });

        renderLogs();
    }

    function renderLogs() {
        if (!elements.logStreamView) return;

        if (state.filteredLogs.length === 0) {
            elements.logStreamView.innerHTML = '<div class="log-empty-state">Keine Log-Ereignisse vorhanden oder entsprechen den Filtern.</div>';
            return;
        }

        const fragment = document.createDocumentFragment();

        state.filteredLogs.slice(0, 100).forEach(log => {
            const row = document.createElement('div');
            row.className = `log-entry level-${(log.level || 'info').toLowerCase()}`;
            row.setAttribute('role', 'button');
            row.setAttribute('tabindex', '0');

            const timeStr = log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();

            const timeSpan = document.createElement('span');
            timeSpan.className = 'log-time';
            timeSpan.textContent = timeStr;

            const badgeSpan = document.createElement('span');
            badgeSpan.className = `log-level-badge badge-${(log.level || 'info').toLowerCase()}`;
            badgeSpan.textContent = log.level || 'INFO';

            const serviceSpan = document.createElement('span');
            serviceSpan.className = 'log-service';
            serviceSpan.textContent = log.service_name || 'unknown';

            const messageSpan = document.createElement('span');
            messageSpan.className = 'log-message';
            messageSpan.textContent = log.payload || '';

            row.appendChild(timeSpan);
            row.appendChild(badgeSpan);
            row.appendChild(serviceSpan);
            row.appendChild(messageSpan);

            row.addEventListener('click', () => showDetails(log));
            row.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    showDetails(log);
                }
            });

            fragment.appendChild(row);
        });

        elements.logStreamView.innerHTML = '';
        elements.logStreamView.appendChild(fragment);
    }

    function showDetails(log) {
        if (!elements.detailModal || !elements.modalPayload || !elements.modalServiceName) return;

        elements.modalServiceName.textContent = `${log.service_name || 'Unbekannt'} [${log.level || 'INFO'}]`;
        let formatted = log.payload || '';
        try {
            const parsed = JSON.parse(log.payload);
            formatted = JSON.stringify(parsed, null, 2);
        } catch {
            // Keine JSON-Struktur, Text bleibt wie er ist
        }

        elements.modalPayload.textContent = formatted;
        elements.detailModal.classList.remove('hidden');
    }

    function hideDetails() {
        if (elements.detailModal) {
            elements.detailModal.classList.add('hidden');
        }
    }

    // Event Listeners Setup
    function setupEventListeners() {
        // Pause Button
        if (elements.btnPauseStream) {
            elements.btnPauseStream.addEventListener('click', () => {
                state.isPaused = !state.isPaused;
                if (elements.pauseIcon) {
                    elements.pauseIcon.textContent = state.isPaused ? '▶' : '⏸';
                }
                if (elements.pauseLabel) {
                    elements.pauseLabel.textContent = state.isPaused ? 'Fortsetzen' : 'Pause';
                }
                elements.btnPauseStream.classList.toggle('active', state.isPaused);
                if (!state.isPaused) {
                    applyFilters();
                }
            });
        }

        // Clear Logs
        if (elements.btnClearLogs) {
            elements.btnClearLogs.addEventListener('click', () => {
                state.logs = [];
                state.filteredLogs = [];
                renderLogs();
                updateMetrics();
            });
        }

        // Search Filter
        if (elements.filterSearch) {
            let timeout = null;
            elements.filterSearch.addEventListener('input', (e) => {
                clearTimeout(timeout);
                timeout = setTimeout(() => {
                    state.searchQuery = e.target.value.trim();
                    applyFilters();
                }, 200);
            });
        }

        // Service Filter
        if (elements.filterService) {
            elements.filterService.addEventListener('change', (e) => {
                state.serviceFilter = e.target.value;
                applyFilters();
            });
        }

        // Level Filter Buttons
        if (elements.levelFilterContainer) {
            elements.levelFilterContainer.addEventListener('click', (e) => {
                const target = e.target.closest('.level-chip');
                if (!target) return;

                const level = target.getAttribute('data-level');
                if (!level) return;

                state.activeLevel = level;
                elements.levelFilterContainer.querySelectorAll('.level-chip').forEach(btn => {
                    btn.classList.remove('active');
                });
                target.classList.add('active');
                applyFilters();
            });
        }

        // Modal Close
        if (elements.modalCloseBtn) {
            elements.modalCloseBtn.addEventListener('click', hideDetails);
        }
        if (elements.detailModal) {
            elements.detailModal.addEventListener('click', (e) => {
                if (e.target === elements.detailModal) {
                    hideDetails();
                }
            });
        }
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && elements.detailModal && !elements.detailModal.classList.contains('hidden')) {
                hideDetails();
            }
        });

        // Metrics Interval
        setInterval(updateMetrics, 1000);
    }

    // Init
    document.addEventListener('DOMContentLoaded', () => {
        setupEventListeners();
        initWebSocket();
        renderLogs();
    });
})();
