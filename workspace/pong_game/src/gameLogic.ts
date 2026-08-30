import { GameConfig, GameState, Ball, Paddle } from './types';

export const DEFAULT_CONFIG: GameConfig = {
  canvasWidth: 800,
  canvasHeight: 500,
  paddleWidth: 15,
  paddleHeight: 90,
  paddleSpeed: 8,
  ballRadius: 8,
  ballInitialSpeed: 5,
};

export function createInitialState(customConfig?: Partial<GameConfig>): GameState {
  const config: GameConfig = { ...DEFAULT_CONFIG, ...customConfig };
  
  return {
    config,
    isPaused: false,
    isGameOver: false,
    player1: {
      x: 20,
      y: config.canvasHeight / 2 - config.paddleHeight / 2,
      width: config.paddleWidth,
      height: config.paddleHeight,
      speed: config.paddleSpeed,
      score: 0,
      color: '#10b981',
    },
    player2: {
      x: config.canvasWidth - 20 - config.paddleWidth,
      y: config.canvasHeight / 2 - config.paddleHeight / 2,
      width: config.paddleWidth,
      height: config.paddleHeight,
      speed: config.paddleSpeed,
      score: 0,
      color: '#6366f1',
    },
    ball: createResetBall(config, 1),
  };
}

export function createResetBall(config: GameConfig, directionX: number = 1): Ball {
  return {
    x: config.canvasWidth / 2,
    y: config.canvasHeight / 2,
    radius: config.ballRadius,
    dx: directionX * config.ballInitialSpeed,
    dy: (Math.random() > 0.5 ? 1 : -1) * (config.ballInitialSpeed * 0.6),
    speed: config.ballInitialSpeed,
  };
}

export function updatePaddlePositions(state: GameState, keys: Record<string, boolean>): GameState {
  let p1Y = state.player1.y;
  let p2Y = state.player2.y;

  // Spieler 1: W / S oder A / D (W/A = nach oben, S/D = nach unten)
  if (keys['KeyW'] || keys['KeyA'] || keys['w'] || keys['a']) {
    p1Y -= state.player1.speed;
  }
  if (keys['KeyS'] || keys['KeyD'] || keys['s'] || keys['d']) {
    p1Y += state.player1.speed;
  }

  // Spieler 2: ArrowUp / ArrowDown oder ArrowLeft / ArrowRight
  if (keys['ArrowUp'] || keys['ArrowLeft']) {
    p2Y -= state.player2.speed;
  }
  if (keys['ArrowDown'] || keys['ArrowRight']) {
    p2Y += state.player2.speed;
  }

  // Begrenzung innerhalb des Spielfelds
  const maxY = state.config.canvasHeight - state.config.paddleHeight;
  p1Y = Math.max(0, Math.min(maxY, p1Y));
  p2Y = Math.max(0, Math.min(maxY, p2Y));

  return {
    ...state,
    player1: { ...state.player1, y: p1Y },
    player2: { ...state.player2, y: p2Y },
  };
}

export function checkPaddleCollision(ball: Ball, paddle: Paddle): boolean {
  return (
    ball.x - ball.radius <= paddle.x + paddle.width &&
    ball.x + ball.radius >= paddle.x &&
    ball.y + ball.radius >= paddle.y &&
    ball.y - ball.radius <= paddle.y + paddle.height
  );
}

export function updateBallPosition(state: GameState): GameState {
  if (state.isPaused) return state;

  let { x, y, dx, dy, speed } = state.ball;
  let { player1, player2 } = state;

  x += dx;
  y += dy;

  // Banden-Kollision (oben / unten)
  if (y - state.ball.radius <= 0) {
    y = state.ball.radius;
    dy = Math.abs(dy);
  } else if (y + state.ball.radius >= state.config.canvasHeight) {
    y = state.config.canvasHeight - state.ball.radius;
    dy = -Math.abs(dy);
  }

  const nextBall: Ball = { ...state.ball, x, y, dx, dy, speed };

  // Kollision mit Spieler 1 (linkes Paddle)
  if (checkPaddleCollision(nextBall, player1) && dx < 0) {
    nextBall.dx = Math.abs(dx) * 1.05; // leichte Geschwindigkeitserhöhung
    nextBall.x = player1.x + player1.width + nextBall.radius;
  }

  // Kollision mit Spieler 2 (rechtes Paddle)
  if (checkPaddleCollision(nextBall, player2) && dx > 0) {
    nextBall.dx = -Math.abs(dx) * 1.05;
    nextBall.x = player2.x - nextBall.radius;
  }

  // Punktgewinn Spieler 2 (Ball verlässt links das Feld)
  if (nextBall.x + nextBall.radius < 0) {
    return {
      ...state,
      player2: { ...player2, score: player2.score + 1 },
      ball: createResetBall(state.config, 1),
    };
  }

  // Punktgewinn Spieler 1 (Ball verlässt rechts das Feld)
  if (nextBall.x - nextBall.radius > state.config.canvasWidth) {
    return {
      ...state,
      player1: { ...player1, score: player1.score + 1 },
      ball: createResetBall(state.config, -1),
    };
  }

  return {
    ...state,
    ball: nextBall,
  };
}

export function gameStep(state: GameState, keys: Record<string, boolean>): GameState {
  if (state.isPaused) return state;
  const stateWithPaddles = updatePaddlePositions(state, keys);
  return updateBallPosition(stateWithPaddles);
}
