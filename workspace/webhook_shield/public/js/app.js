document.addEventListener('DOMContentLoaded', () => {
    console.log('WebhookShield Dashboard geladen.');
    
    // Beispiel: Initiales Laden der Daten oder SSE Verbindung
    fetchWebhooks();
});

async function fetchWebhooks() {
    try {
        const response = await fetch('/logs');
        if (!response.ok) throw new Error('Fehler beim Laden der Webhooks');
        const data = await response.json();
        renderWebhooks(data);
    } catch (error) {
        console.error('Fehler:', error);
    }
}

function renderWebhooks(webhooks) {
    const container = document.getElementById('logs-container');
    container.innerHTML = webhooks.length > 0 
        ? webhooks.map(w => `<div class="webhook-card">ID: ${w.id} - Event: ${w.event_type}</div>`).join('')
        : '<p>Keine Webhooks gefunden.</p>';
}
