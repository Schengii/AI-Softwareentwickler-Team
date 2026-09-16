document.addEventListener('DOMContentLoaded', () => {
    const bucketContainer = document.getElementById('bucket-list');
    const eventDetails = document.getElementById('event-details');

    async function loadBuckets() {
        try {
            const res = await fetch('/api/buckets');
            if (!res.ok) throw new Error('Fehler beim Laden der Buckets');
            const buckets = await res.json();
            bucketContainer.innerHTML = buckets.map(b => `
                <div class="bucket-card p-4 rounded-lg cursor-pointer" onclick="selectBucket('${b.id}')">
                    <h3 class="font-bold">${b.name}</h3>
                    <p class="text-xs text-gray-400 truncate">ID: ${b.id}</p>
                </div>
            `).join('');
        } catch (err) {
            console.error(err);
        }
    }

    window.selectBucket = async (id) => {
        try {
            const res = await fetch(`/api/buckets/${id}/events`);
            const events = await res.json();
            eventDetails.innerHTML = events.length ? events.map(e => `
                <div class="mb-4 p-3 bg-gray-900 rounded">
                    <span class="method-badge method-${e.method}">${e.method}</span>
                    <span class="text-sm ml-2">${new Date(e.timestamp).toLocaleString()}</span>
                    <pre class="text-xs mt-2 text-green-400">${JSON.stringify(e.payload, null, 2)}</pre>
                </div>
            `).join('') : '<p>Keine Events gefunden.</p>';
        } catch (err) {
            eventDetails.textContent = 'Fehler beim Laden der Events.';
        }
    };

    loadBuckets();
});
