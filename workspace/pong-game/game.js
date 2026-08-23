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
    }
}
