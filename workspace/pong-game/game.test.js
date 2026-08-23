import { PongGame } from './game.js';

describe('PongGame', () => {
    let canvas;
    let ui;

    beforeEach(() => {
        canvas = { getContext: () => ({ fillRect: jest.fn(), fill: jest.fn(), beginPath: jest.fn() }), width: 800, height: 400 };
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
});
