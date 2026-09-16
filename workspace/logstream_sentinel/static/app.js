const logOutput = document.getElementById('log-output');
const searchInput = document.getElementById('search-input');
const levelFilter = document.getElementById('level-filter');
const pauseBtn = document.getElementById('pause-btn');

let isPaused = false;
let ws;

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/live`;
    ws = new WebSocket(wsUrl);
    
    ws.onmessage = (event) => {
        if (isPaused) return;
        
        const log = JSON.parse(event.data);
        const div = document.createElement('div');
        div.className = `log-entry log-${log.level}`;
        div.textContent = `[${log.timestamp}] ${log.level}: ${log.service_name} - ${log.message}`;
        logOutput.appendChild(div);
        
        // Auto-scroll
        logOutput.scrollTop = logOutput.scrollHeight;
    };

    ws.onclose = () => {
        document.getElementById('status-indicator').textContent = '● Getrennt';
        setTimeout(connect, 5000);
    };
}

pauseBtn.addEventListener('click', () => {
    isPaused = !isPaused;
    pauseBtn.textContent = isPaused ? 'Resume' : 'Pause';
});

connect();
