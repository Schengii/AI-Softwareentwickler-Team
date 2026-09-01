import type { Paddle as PaddleType, Ball as BallType } from "./types";

const canvas = document.getElementById("pongCanvas") as HTMLCanvasElement;
const ctx = canvas.getContext("2d")!;
const CANVAS_W = canvas.width;
const CANVAS_H = canvas.height;

class Paddle implements PaddleType {
  x: number;
  y: number;
  width = 10;
  height = 100;
  dy = 0;
  speed = 6;
  score = 0;
  color: string;

  constructor(x: number, y: number, color: string) {
    this.x = x;
    this.y = y;
    this.color = color;
  }

  update() {
    this.y += this.dy;
    if (this.y < 0) this.y = 0;
    if (this.y + this.height > CANVAS_H) this.y = CANVAS_H - this.height;
  }

  draw() {
    ctx.fillStyle = this.color;
    ctx.fillRect(this.x, this.y, this.width, this.height);
  }
}

class Ball implements BallType {
  x: number;
  y: number;
  radius = 8;
  dx = 4;
  dy = 4;
  speed = 4;
  color = "#fff";

  constructor() {
    this.reset(1);
  }

  reset(direction: 1 | -1) {
    this.x = CANVAS_W / 2;
    this.y = CANVAS_H / 2;
    this.dx = this.speed * direction;
    this.dy = (Math.random() * 2 - 1) * this.speed;
  }

  update(p1: Paddle, p2: Paddle) {
    this.x += this.dx;
    this.y += this.dy;

    if (this.y - this.radius < 0 || this.y + this.radius > CANVAS_H) this.dy *= -1;

    if (this.x - this.radius < p1.x + p1.width && this.y > p1.y && this.y < p1.y + p1.height) {
      this.dx = Math.abs(this.dx) + 0.5;
      this.dx *= -1;
    }

    if (this.x + this.radius > p2.x && this.y > p2.y && this.y < p2.y + p2.height) {
      this.dx = -(Math.abs(this.dx) + 0.5);
    }

    if (this.x < 0) { p2.score++; this.reset(1); }
    else if (this.x > CANVAS_W) { p1.score++; this.reset(-1); }
  }

  draw() {
    ctx.fillStyle = this.color;
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
    ctx.fill();
  }
}

const leftPaddle = new Paddle(30, CANVAS_H / 2 - 50, "#ff5555");
const rightPaddle = new Paddle(CANVAS_W - 40, CANVAS_H / 2 - 50, "#55ff55");
const ball = new Ball();
const keys: Record<string, boolean> = {};

window.addEventListener("keydown", e => keys[e.key] = true);
window.addEventListener("keyup", e => keys[e.key] = false);

function handleInput() {
  leftPaddle.dy = (keys["w"] || keys["W"] || keys["a"] || keys["A"]) ? -leftPaddle.speed : 
                  (keys["s"] || keys["S"] || keys["d"] || keys["D"]) ? leftPaddle.speed : 0;
  rightPaddle.dy = (keys["ArrowUp"] || keys["ArrowLeft"]) ? -rightPaddle.speed : 
                   (keys["ArrowDown"] || keys["ArrowRight"]) ? rightPaddle.speed : 0;
}

let paused = false;
window.addEventListener("keydown", e => {
  if (e.key === " ") paused = !paused;
  if (e.key.toLowerCase() === "r") { leftPaddle.score = rightPaddle.score = 0; ball.reset(1); }
});

function loop() {
  if (!paused) {
    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);
    handleInput();
    leftPaddle.update();
    rightPaddle.update();
    ball.update(leftPaddle, rightPaddle);
    leftPaddle.draw();
    rightPaddle.draw();
    ball.draw();
    ctx.fillStyle = "#fff"; ctx.font = "30px sans-serif";
    ctx.fillText(`${leftPaddle.score}`, CANVAS_W * 0.25, 40);
    ctx.fillText(`${rightPaddle.score}`, CANVAS_W * 0.75, 40);
  }
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
