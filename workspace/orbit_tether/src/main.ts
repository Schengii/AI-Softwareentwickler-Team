/**
 * Orbit Tether - Haupteinstiegspunkt
 */

import { deviceService } from './services/DeviceService.js';
import { hapticService } from './services/HapticService.js';

interface GameState {
  score: number;
  highScore: number;
  player: {
    x: number;
    y: number;
    vx: number;
    vy: number;
    radius: number;
    angle: number;
  };
  center: {
    x: number;
    y: number;
    radius: number;
  };
  isTethered: boolean;
  tetherLength: number;
  stars: Array<{ x: number; y: number; radius: number; alpha: number }>;
}

class OrbitTetherGame {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private scoreElement: HTMLElement | null;
  private animationFrameId: number = 0;
  private lastTime: number = 0;

  private state: GameState = {
    score: 0,
    highScore: 0,
    player: {
      x: 0,
      y: 0,
      vx: 3,
      vy: 0,
      radius: 12,
      angle: 0
    },
    center: {
      x: 0,
      y: 0,
      radius: 28
    },
    isTethered: false,
    tetherLength: 120,
    stars: []
  };

  constructor() {
    const canvas = document.getElementById('game-canvas') as HTMLCanvasElement;
    if (!canvas) {
      throw new Error('Canvas-Element mit ID "game-canvas" nicht gefunden.');
    }
    this.canvas = canvas;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      throw new Error('2D-Rendering-Kontext konnte nicht initialisiert werden.');
    }
    this.ctx = ctx;
    this.scoreElement = document.getElementById('score-display');

    this.initResize();
    this.initStars();
    this.initInputs();

    // Sofort initial zeichnen, damit Canvas direkt Pixel enthält
    this.render();

    // Spielschleife starten
    this.lastTime = performance.now();
    this.loop = this.loop.bind(this);
    this.animationFrameId = requestAnimationFrame(this.loop);
  }

  private initResize(): void {
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const width = window.innerWidth;
      const height = window.innerHeight;

      this.canvas.width = width * dpr;
      this.canvas.height = height * dpr;
      this.canvas.style.width = `${width}px`;
      this.canvas.style.height = `${height}px`;

      this.ctx.resetTransform?.();
      this.ctx.scale(dpr, dpr);

      this.state.center.x = width / 2;
      this.state.center.y = height / 2;

      if (this.state.player.x === 0 && this.state.player.y === 0) {
        this.state.player.x = width / 2;
        this.state.player.y = height / 2 - this.state.tetherLength;
      }
    };

    window.addEventListener('resize', resize);
    resize();
  }

  private initStars(): void {
    const width = window.innerWidth || 800;
    const height = window.innerHeight || 600;
    this.state.stars = [];
    for (let i = 0; i < 60; i++) {
      this.state.stars.push({
        x: Math.random() * width,
        y: Math.random() * height,
        radius: Math.random() * 1.5 + 0.5,
        alpha: Math.random() * 0.8 + 0.2
      });
    }
  }

  private initInputs(): void {
    const startTether = (e: Event) => {
      e.preventDefault();
      this.state.isTethered = true;
      try {
        hapticService.impactMedium();
      } catch {
        // Fallback falls native Services nicht verfügbar
      }
    };

    const stopTether = (e: Event) => {
      e.preventDefault();
      this.state.isTethered = false;
      try {
        hapticService.impactLight();
      } catch {
        // Fallback
      }
    };

    window.addEventListener('pointerdown', startTether);
    window.addEventListener('pointerup', stopTether);
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Space' && !e.repeat) {
        startTether(e);
      }
    });
    window.addEventListener('keyup', (e) => {
      if (e.code === 'Space') {
        stopTether(e);
      }
    });
  }

  private update(dt: number): void {
    const p = this.state.player;
    const c = this.state.center;

    if (this.state.isTethered) {
      // Gravitation / Tether-Zugkraft zum Zentrum
      const dx = c.x - p.x;
      const dy = c.y - p.y;
      const dist = Math.hypot(dx, dy) || 1;
      const force = 0.008 * dt;

      p.vx += (dx / dist) * force * 50;
      p.vy += (dy / dist) * force * 50;

      // Punkte sammeln während Orbit
      this.state.score += Math.floor(dt * 0.05);
      if (this.scoreElement) {
        this.scoreElement.textContent = `Score: ${this.state.score}`;
      }
    }

    p.x += p.vx * (dt / 16);
    p.y += p.vy * (dt / 16);
    p.angle += 0.05 * (dt / 16);

    // Bildschirm-Rand-Reflexion für kontinuierlichen Spielspaß
    const w = window.innerWidth;
    const h = window.innerHeight;
    if (p.x < p.radius) { p.x = p.radius; p.vx *= -0.8; }
    if (p.x > w - p.radius) { p.x = w - p.radius; p.vx *= -0.8; }
    if (p.y < p.radius) { p.y = p.radius; p.vy *= -0.8; }
    if (p.y > h - p.radius) { p.y = h - p.radius; p.vy *= -0.8; }
  }

  private render(): void {
    const width = window.innerWidth;
    const height = window.innerHeight;
    const ctx = this.ctx;

    // Hintergrund leeren
    ctx.fillStyle = '#050813';
    ctx.fillRect(0, 0, width, height);

    // Sterne im Hintergrund
    for (const star of this.state.stars) {
      ctx.fillStyle = `rgba(255, 255, 255, ${star.alpha})`;
      ctx.beginPath();
      ctx.arc(star.x, star.y, star.radius, 0, Math.PI * 2);
      ctx.fill();
    }

    const { player, center, isTethered } = this.state;

    // Tether-Verbindungslinie zeichnen
    if (isTethered) {
      ctx.save();
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 2.5;
      ctx.shadowColor = '#0284c7';
      ctx.shadowBlur = 10;
      ctx.beginPath();
      ctx.moveTo(center.x, center.y);
      ctx.lineTo(player.x, player.y);
      ctx.stroke();
      ctx.restore();
    }

    // Zentrum (Orbit-Kern) zeichnen
    ctx.save();
    const grad = ctx.createRadialGradient(center.x, center.y, 5, center.x, center.y, center.radius);
    grad.addColorStop(0, '#60a5fa');
    grad.addColorStop(1, '#1e3a8a');
    ctx.fillStyle = grad;
    ctx.shadowColor = '#3b82f6';
    ctx.shadowBlur = 15;
    ctx.beginPath();
    ctx.arc(center.x, center.y, center.radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    // Spieler-Orbiter zeichnen
    ctx.save();
    ctx.translate(player.x, player.y);
    ctx.rotate(player.angle);
    ctx.fillStyle = '#f43f5e';
    ctx.shadowColor = '#fb7185';
    ctx.shadowBlur = 12;
    ctx.beginPath();
    ctx.arc(0, 0, player.radius, 0, Math.PI * 2);
    ctx.fill();

    // Schiff-Leitfaden / Spitze
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.moveTo(player.radius, 0);
    ctx.lineTo(-player.radius / 2, -player.radius / 2);
    ctx.lineTo(-player.radius / 2, player.radius / 2);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  private loop(timestamp: number): void {
    const dt = Math.min(timestamp - this.lastTime, 100);
    this.lastTime = timestamp;

    this.update(dt);
    this.render();

    this.animationFrameId = requestAnimationFrame(this.loop);
  }

  public destroy(): void {
    cancelAnimationFrame(this.animationFrameId);
  }
}

// Spiel starten sobald DOM bereit ist
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    new OrbitTetherGame();
  });
} else {
  new OrbitTetherGame();
}
