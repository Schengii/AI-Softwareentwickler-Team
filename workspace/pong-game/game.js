export const CONFIG = {
    CANVAS_WIDTH: 800,
    CANVAS_HEIGHT: 400,
    PLAYER_WIDTH: 10,
    PLAYER_HEIGHT: 80,
    BALL_RADIUS: 5,
    WIN_SCORE: 5,
    AI_SPEED: 0.1
};

export class PongGame {
    constructor(canvas, uiElements) {
        if (!canvas) throw new Error("Canvas element required");
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.ui = uiElements;
        this.score = { player: 0, ai: 0 };
        this.gameActive = false;
        this.timerInterval = null;
        this.player = { x: 10, y: 150, dy: 0 };
        this.ai = { x: 780, y: 150 };
        this.ball = { x: 400, y: 200, dx: 4, dy: 4 };
    }

    resetGame() {
        this.score = { player: 0, ai: 0 };
        this.gameActive = false;
        clearInterval(this.timerInterval);
        this.ball = { x: 400, y: 200, dx: 4, dy: 4 };
        this.updateUI();
    }

    updateUI() {
        if (this.ui.playerScore) this.ui.playerScore.innerText = this.score.player;
        if (this.ui.aiScore) this.ui.aiScore.innerText = this.score.ai;
    }

    update() {
        if (!this.gameActive) return;
        this.ball.x += this.ball.dx;
        this.ball.y += this.ball.dy;

        if (this.ball.y < 0 || this.ball.y > this.canvas.height) this.ball.dy *= -1;
        this.ai.y += (this.ball.y - (this.ai.y + CONFIG.PLAYER_HEIGHT / 2)) * CONFIG.AI_SPEED;

        if (this.ball.x < this.player.x + CONFIG.PLAYER_WIDTH && this.ball.y > this.player.y && this.ball.y < this.player.y + CONFIG.PLAYER_HEIGHT) this.ball.dx *= -1;
        if (this.ball.x > this.ai.x && this.ball.y > this.ai.y && this.ball.y < this.ai.y + CONFIG.PLAYER_HEIGHT) this.ball.dx *= -1;

        if (this.ball.x < 0) { this.score.ai++; this.resetBall(); }
        if (this.ball.x > this.canvas.width) { this.score.player++; this.resetBall(); }

        this.updateUI();
        if (this.score.player >= CONFIG.WIN_SCORE || this.score.ai >= CONFIG.WIN_SCORE) this.endGame();
    }

    resetBall() {
        this.ball = { x: 400, y: 200, dx: 4 * (Math.random() > 0.5 ? 1 : -1), dy: 4 * (Math.random() > 0.5 ? 1 : -1) };
    }

    endGame() {
        this.gameActive = false;
        clearInterval(this.timerInterval);
        if (this.ui.winMessage) {
            this.ui.winMessage.innerText = this.score.player > this.score.ai ? 'Du gewinnst!' : 'KI gewinnt!';
        }
        if (this.ui.gameUi) this.ui.gameUi.classList.add('hidden');
        if (this.ui.winScreen) this.ui.winScreen.classList.remove('hidden');
    }

    // Realer Fund (Code-Review): die bisherige Klasse enthielt KEINE einzige Methode, die
    // tatsächlich in den Canvas-Context zeichnete (kein fillRect/arc-Aufruf) - das Spiel lud
    // fehlerfrei, zeigte aber niemals ein Pixel an. draw() rendert jetzt den kompletten
    // Spielzustand (Hintergrund, Mittellinie, beide Schläger, Ball) in JEDEM Frame.
    draw() {
        const ctx = this.ctx;
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        ctx.strokeStyle = '#555';
        ctx.setLineDash([8, 8]);
        ctx.beginPath();
        ctx.moveTo(this.canvas.width / 2, 0);
        ctx.lineTo(this.canvas.width / 2, this.canvas.height);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#fff';
        ctx.fillRect(this.player.x, this.player.y, CONFIG.PLAYER_WIDTH, CONFIG.PLAYER_HEIGHT);
        ctx.fillRect(this.ai.x, this.ai.y, CONFIG.PLAYER_WIDTH, CONFIG.PLAYER_HEIGHT);

        ctx.beginPath();
        ctx.arc(this.ball.x, this.ball.y, CONFIG.BALL_RADIUS, 0, Math.PI * 2);
        ctx.fill();
    }

    // Verdrahtet Maus-Steuerung, Start-Button, Game-Loop (requestAnimationFrame) und Timer mit
    // dem DOM - fehlte bisher komplett, weshalb new PongGame(...) nirgends aufgerufen wurde und
    // die Klasse trotz korrekter Logik nie tatsächlich lief (siehe ADR 0001).
    start() {
        this.canvas.addEventListener('mousemove', (evt) => {
            const rect = this.canvas.getBoundingClientRect();
            const mouseY = evt.clientY - rect.top;
            this.player.y = Math.min(
                Math.max(mouseY - CONFIG.PLAYER_HEIGHT / 2, 0),
                this.canvas.height - CONFIG.PLAYER_HEIGHT,
            );
        });

        const beginRound = () => {
            this.resetGame();
            this.gameActive = true;
            this.elapsedSeconds = 0;
            if (this.ui.time) this.ui.time.innerText = '0';
            this.timerInterval = setInterval(() => {
                this.elapsedSeconds += 1;
                if (this.ui.time) this.ui.time.innerText = String(this.elapsedSeconds);
            }, 1000);
        };

        if (this.ui.startBtn) {
            this.ui.startBtn.addEventListener('click', () => {
                if (this.ui.startScreen) this.ui.startScreen.classList.add('hidden');
                if (this.ui.gameUi) this.ui.gameUi.classList.remove('hidden');
                beginRound();
            });
        }

        const loop = () => {
            this.update();
            this.draw();
            requestAnimationFrame(loop);
        };
        requestAnimationFrame(loop);

        if (this.ui.loadingScreen) this.ui.loadingScreen.classList.add('hidden');
        if (this.ui.startScreen) this.ui.startScreen.classList.remove('hidden');
    }
}

// Nur im echten Browser bootstrappen, NIE beim Import durch Jest (dort existiert `document`
// nicht) - siehe game.test.js, das PongGame ausschließlich isoliert mit injizierten Mocks
// testet, ohne dieses Modul jemals real im Browser zu laden.
if (typeof document !== 'undefined' && document.getElementById('pongCanvas')) {
    const game = new PongGame(document.getElementById('pongCanvas'), {
        playerScore: document.getElementById('player-score'),
        aiScore: document.getElementById('ai-score'),
        time: document.getElementById('time'),
        loadingScreen: document.getElementById('loading-screen'),
        startScreen: document.getElementById('start-screen'),
        startBtn: document.getElementById('start-btn'),
        gameUi: document.getElementById('game-ui'),
        winScreen: document.getElementById('win-screen'),
        winMessage: document.getElementById('win-message'),
    });
    game.start();
}
