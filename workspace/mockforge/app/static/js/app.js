document.addEventListener('DOMContentLoaded', () => {
    console.log('MockForge App initialized');

    const mockForm = document.getElementById('mock-form');
    if (mockForm) {
        mockForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const method = document.getElementById('method').value;
            const path = document.getElementById('path').value;
            const status = parseInt(document.getElementById('status').value);
            const body = document.getElementById('body').value;

            try {
                const response = await fetch('/api/v1/mocks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ method, path, status, response_body: body })
                });

                if (!response.ok) throw new Error('Fehler beim Erstellen des Mocks');
                alert('Mock erfolgreich erstellt!');
                mockForm.reset();
            } catch (error) {
                console.error('Error:', error);
                alert('Fehler: ' + error.message);
            }
        });
    }
});
