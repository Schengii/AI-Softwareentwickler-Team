export interface Paddle {
  x: number;
  y: number;
  width: number;
  height: number;
  speed: number;
  score: number;
  color: string;
}

export interface Ball {
  x: number;
  y: number;
  radius: number;
  dx: number;
  dy: number;
  speed: number;
}

export interface GameConfig {
  canvasWidth: number;
  canvasHeight: number;
  paddleWidth: number;
  paddleHeight: number;
  paddleSpeed: number;
  ballRadius: number;
  ballInitialSpeed: number;
}

export interface GameState {
  player1: Paddle;
  player2: Paddle;
  ball: Ball;
  isPaused: boolean;
  isGameOver: boolean;
  config: GameConfig;
}
