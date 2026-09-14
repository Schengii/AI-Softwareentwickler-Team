import { describe, it, expect } from 'vitest';
import {
  DEFAULT_CONFIG,
  createInitialState,
  createResetBall,
  updatePaddlePositions,
  checkPaddleCollision,
  updateBallPosition,
  gameStep
} from './gameLogic';
import { Ball, Paddle } from './types';

describe('Pong Spiellogik (gameLogic.ts)', () => {
  describe('createInitialState', () => {
    it('erstellt den Initialzustand mit Standardkonfiguration', () => {
      const state = createInitialState();

      expect(state.config).toEqual(DEFAULT_CONFIG);
      expect(state.isPaused).toBe(false);
      expect(state.isGameOver).toBe(false);
      expect(state.player1.score).toBe(0);
      expect(state.player2.score).toBe(0);
      expect(state.player1.x).toBe(20);
      expect(state.player1.y).toBe(DEFAULT_CONFIG.canvasHeight / 2 - DEFAULT_CONFIG.paddleHeight / 2);
      expect(state.player2.x).toBe(DEFAULT_CONFIG.canvasWidth - 20 - DEFAULT_CONFIG.paddleWidth);
      expect(state.player2.y).toBe(DEFAULT_CONFIG.canvasHeight / 2 - DEFAULT_CONFIG.paddleHeight / 2);
    });

    it('erlaubt das Überschreiben mit einer benutzerdefinierten Konfiguration', () => {
      const state = createInitialState({ canvasWidth: 1000, canvasHeight: 600 });

      expect(state.config.canvasWidth).toBe(1000);
      expect(state.config.canvasHeight).toBe(600);
      expect(state.player1.y).toBe(600 / 2 - DEFAULT_CONFIG.paddleHeight / 2);
    });
  });

  describe('createResetBall', () => {
    it('setzt den Ball in die Spielfeldmitte zurück', () => {
      const ball = createResetBall(DEFAULT_CONFIG, 1);

      expect(ball.x).toBe(DEFAULT_CONFIG.canvasWidth / 2);
      expect(ball.y).toBe(DEFAULT_CONFIG.canvasHeight / 2);
      expect(ball.speed).toBe(DEFAULT_CONFIG.ballInitialSpeed);
      expect(ball.dx).toBe(DEFAULT_CONFIG.ballInitialSpeed);
    });

    it('berücksichtigt die angegebene X-Richtung', () => {
      const ballLeft = createResetBall(DEFAULT_CONFIG, -1);
      expect(ballLeft.dx).toBe(-DEFAULT_CONFIG.ballInitialSpeed);
    });
  });

  describe('updatePaddlePositions', () => {
    it('bewegt Spieler 1 nach oben bei KeyW / w', () => {
      const state = createInitialState();
      const initialY = state.player1.y;

      const newState = updatePaddlePositions(state, { KeyW: true });
      expect(newState.player1.y).toBe(initialY - DEFAULT_CONFIG.paddleSpeed);
    });

    it('bewegt Spieler 1 nach unten bei KeyS / s', () => {
      const state = createInitialState();
      const initialY = state.player1.y;

      const newState = updatePaddlePositions(state, { KeyS: true });
      expect(newState.player1.y).toBe(initialY + DEFAULT_CONFIG.paddleSpeed);
    });

    it('bewegt Spieler 2 nach oben bei ArrowUp und nach unten bei ArrowDown', () => {
      const state = createInitialState();
      const initialY = state.player2.y;

      const stateUp = updatePaddlePositions(state, { ArrowUp: true });
      expect(stateUp.player2.y).toBe(initialY - DEFAULT_CONFIG.paddleSpeed);

      const stateDown = updatePaddlePositions(state, { ArrowDown: true });
      expect(stateDown.player2.y).toBe(initialY + DEFAULT_CONFIG.paddleSpeed);
    });

    it('begrenzt die Paddle-Position am oberen Spielfeldrand', () => {
      let state = createInitialState();
      state.player1.y = 2;

      const newState = updatePaddlePositions(state, { KeyW: true });
      expect(newState.player1.y).toBe(0);
    });

    it('begrenzt die Paddle-Position am unteren Spielfeldrand', () => {
      let state = createInitialState();
      const maxY = DEFAULT_CONFIG.canvasHeight - DEFAULT_CONFIG.paddleHeight;
      state.player1.y = maxY - 2;

      const newState = updatePaddlePositions(state, { KeyS: true });
      expect(newState.player1.y).toBe(maxY);
    });
  });

  describe('checkPaddleCollision', () => {
    it('erkennt eine Kollision zwischen Ball und Paddle', () => {
      const paddle: Paddle = {
        x: 20,
        y: 100,
        width: 15,
        height: 90,
        speed: 8,
        score: 0,
        color: 'green',
      };
      const ball: Ball = {
        x: 30,
        y: 120,
        radius: 8,
        dx: -5,
        dy: 0,
        speed: 5,
      };

      expect(checkPaddleCollision(ball, paddle)).toBe(true);
    });

    it('erkennt keine Kollision wenn der Ball außerhalb des Paddles ist', () => {
      const paddle: Paddle = {
        x: 20,
        y: 100,
        width: 15,
        height: 90,
        speed: 8,
        score: 0,
        color: 'green',
      };
      const ball: Ball = {
        x: 200,
        y: 120,
        radius: 8,
        dx: -5,
        dy: 0,
        speed: 5,
      };

      expect(checkPaddleCollision(ball, paddle)).toBe(false);
    });
  });

  describe('updateBallPosition', () => {
    it('bewegt den Ball gemäß dx und dy', () => {
      const state = createInitialState();
      state.ball.x = 200;
      state.ball.y = 200;
      state.ball.dx = 5;
      state.ball.dy = 3;

      const newState = updateBallPosition(state);
      expect(newState.ball.x).toBe(205);
      expect(newState.ball.y).toBe(203);
    });

    it('prallt an der oberen Bande ab', () => {
      const state = createInitialState();
      state.ball.x = 200;
      state.ball.y = 5;
      state.ball.dx = 5;
      state.ball.dy = -10;

      const newState = updateBallPosition(state);
      expect(newState.ball.dy).toBeGreaterThan(0);
      expect(newState.ball.y).toBeGreaterThanOrEqual(state.ball.radius);
    });

    it('prallt an der unteren Bande ab', () => {
      const state = createInitialState();
      state.ball.x = 200;
      state.ball.y = DEFAULT_CONFIG.canvasHeight - 5;
      state.ball.dx = 5;
      state.ball.dy = 10;

      const newState = updateBallPosition(state);
      expect(newState.ball.dy).toBeLessThan(0);
    });

    it('prallt am linken Paddle ab und kehrt X-Richtung um', () => {
      const state = createInitialState();
      state.player1.x = 20;
      state.player1.y = 100;
      state.ball.x = 36;
      state.ball.y = 110;
      state.ball.dx = -5;
      state.ball.dy = 0;

      const newState = updateBallPosition(state);
      expect(newState.ball.dx).toBeGreaterThan(0);
    });

    it('erhöht den Punktestand von Spieler 2, wenn Ball links ins Aus geht', () => {
      const state = createInitialState();
      state.ball.x = -10;
      state.ball.dx = -5;

      const newState = updateBallPosition(state);
      expect(newState.player2.score).toBe(1);
      expect(newState.player1.score).toBe(0);
      expect(newState.ball.x).toBe(DEFAULT_CONFIG.canvasWidth / 2);
    });

    it('erhöht den Punktestand von Spieler 1, wenn Ball rechts ins Aus geht', () => {
      const state = createInitialState();
      state.ball.x = DEFAULT_CONFIG.canvasWidth + 20;
      state.ball.dx = 5;

      const newState = updateBallPosition(state);
      expect(newState.player1.score).toBe(1);
      expect(newState.player2.score).toBe(0);
      expect(newState.ball.x).toBe(DEFAULT_CONFIG.canvasWidth / 2);
    });

    it('verändert den Zustand nicht, wenn das Spiel pausiert ist', () => {
      const state = createInitialState();
      state.isPaused = true;
      const initialBallX = state.ball.x;

      const newState = updateBallPosition(state);
      expect(newState.ball.x).toBe(initialBallX);
    });
  });

  describe('gameStep', () => {
    it('aktualisiert Paddle und Ball in einem Einzelschritt', () => {
      const state = createInitialState();
      const keys = { KeyS: true };

      const newState = gameStep(state, keys);
      expect(newState.player1.y).toBe(state.player1.y + DEFAULT_CONFIG.paddleSpeed);
      expect(newState.ball.x).not.toBe(state.ball.x);
    });

    it('macht nichts, wenn das Spiel pausiert ist', () => {
      const state = createInitialState();
      state.isPaused = true;

      const newState = gameStep(state, { KeyS: true });
      expect(newState).toBe(state);
    });
  });
});
