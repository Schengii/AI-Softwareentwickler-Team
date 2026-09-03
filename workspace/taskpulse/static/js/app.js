/**
 * TaskPulse Frontend Logik
 */

const API_BASE = '';

async function fetchTasks() {
    try {
        const response = await fetch(`${API_BASE}/tasks`);
        const tasks = await response.json();
        const container = document.getElementById('tasks-container');
        container.innerHTML = tasks.map(task => `
            <div class="bg-white p-4 rounded shadow">
                <h3 class="font-bold">${task.name}</h3>
                <p class="text-sm text-gray-600">Status: ${task.status}</p>
            </div>
        `).join('');
    } catch (error) {
        console.error('Fehler beim Laden der Tasks:', error);
    }
}

async function fetchStatus() {
    try {
        const response = await fetch(`${API_BASE}/status`);
        const status = await response.json();
        const container = document.getElementById('status-container');
        container.innerHTML = `<pre class="text-sm">${JSON.stringify(status, null, 2)}</pre>`;
    } catch (error) {
        console.error('Fehler beim Laden des Status:', error);
    }
}

// Initialer Aufruf und Polling
document.addEventListener('DOMContentLoaded', () => {
    fetchTasks();
    fetchStatus();
    setInterval(fetchTasks, 5000); // Alle 5 Sekunden aktualisieren
    setInterval(fetchStatus, 10000); // Alle 10 Sekunden Status prüfen
});
