document.addEventListener('DOMContentLoaded', () => {
    const container = document.getElementById('pipelines-container');
    const modal = document.getElementById('modal');

    async function loadPipelines() {
        try {
            const res = await fetch('/api/pipelines');
            const data = await res.json();
            container.innerHTML = data.map(p => `
                <div class="card">
                    <h3>${p.name}</h3>
                    <p>${p.description || ''}</p>
                    <button onclick="runPipeline(${p.id})">Starten</button>
                </div>
            `).join('');
        } catch (e) {
            console.error('Fehler beim Laden:', e);
        }
    }

    document.getElementById('add-pipeline-btn').onclick = () => modal.classList.remove('hidden');
    document.getElementById('close-modal').onclick = () => modal.classList.add('hidden');

    window.runPipeline = async (id) => {
        await fetch(`/api/pipelines/${id}/run`, { method: 'POST' });
        loadPipelines();
    };

    loadPipelines();
});
