import { jest } from '@jest/globals';
import { CONFIG, PongGame } from './game.js';

describe('PongGame', () => {
    let canvas;
    let ui;

    beforeEach(() => {
        canvas = { getContext: () => ({ fillRect: jest.fn(), fill: jest.fn(), beginPath: jest.fn(), arc: jest.fn(), setLineDash: jest.fn(), stroke: jest.fn(), moveTo: jest.fn(), lineTo: jest.fn() }), width: 800, height: 400 };
        ui = { playerScore: { innerText: '' }, aiScore: { innerText: '' } };
    });

    test('should initialize with score 0', () => {
        const game = new PongGame(canvas, ui);
        expect(game.score.player).toBe(0);
    });

    test('should reset game state', () => {
        const game = new PongGame(canvas, ui);
        game.score.player = 3;
        game.resetGame();
        expect(game.score.player).toBe(0);
    });

    test('update() does nothing while gameActive is false', () => {
        const game = new PongGame(canvas, ui);
        const initialX = game.ball.x;
        game.update();
        expect(game.ball.x).toBe(initialX);
    });

    test('ball bounces off the player paddle', () => {
        const game = new PongGame(canvas, ui);
        game.gameActive = true;
        game.player = { x: 10, y: 150, dy: 0 };
        game.ball = { x: 21, y: 180, dx: -4, dy: 0 };
        game.update();
        expect(game.ball.dx).toBe(4);
    });

    test('AI scores when the ball passes the player side', () => {
        const game = new PongGame(canvas, ui);
        game.gameActive = true;
        game.ball = { x: -1, y: 200, dx: -4, dy: 0 };
        game.update();
        expect(game.score.ai).toBe(1);
        expect(ui.aiScore.innerText).toBe(1);
    });

    test('player scores when the ball passes the AI side', () => {
        const game = new PongGame(canvas, ui);
        game.gameActive = true;
        game.ball = { x: canvas.width + 1, y: 200, dx: 4, dy: 0 };
        game.update();
        expect(game.score.player).toBe(1);
    });

    test('reaching WIN_SCORE ends the game', () => {
        const game = new PongGame(canvas, ui);
        game.gameActive = true;
        game.score.player = CONFIG.WIN_SCORE - 1;
        game.ball = { x: canvas.width + 1, y: 200, dx: 4, dy: 0 };
        game.update();
        expect(game.score.player).toBe(CONFIG.WIN_SCORE);
        expect(game.gameActive).toBe(false);
    });
});
