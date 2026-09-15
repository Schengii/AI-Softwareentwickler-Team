import { describe, it, expect, beforeEach } from 'vitest';

/**
 * Interface-Definitionen für Vektoren und Entitäten
 */
export interface Vector2D {
  x: number;
  y: number;
}

export interface Anchor {
  x: number;
  y: number;
  radius: number;
}

/**
 * MathUtils - Kern-Vektorrechnung und Kollisionserkennung
 */
export class MathUtils {
  static distance(p1: Vector2D, p2: Vector2D): number {
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    return Math.hypot(dx, dy);
  }

  static normalize(v: Vector2D): Vector2D {
    const len = Math.hypot(v.x, v.y);
    if (len === 0) {
      return { x: 0, y: 0 }; // Zero-Division Guard
    }
    return { x: v.x / len, y: v.y / len };
  }

  static checkCircleCollision(
    p1: Vector2D,
    r1: number,
    p2: Vector2D,
    r2: number
  ): boolean {
    const dist = MathUtils.distance(p1, p2);
    // Exakte Berührung (d <= r1 + r2) gilt als Kollision
    return dist <= r1 + r2;
  }

  static calculateTangent(
    particlePos: Vector2D,
    anchorPos: Vector2D,
    clockwise: boolean = true
  ): Vector2D {
    const radial = {
      x: particlePos.x - anchorPos.x,
      y: particlePos.y - anchorPos.y,
    };
    const normRadial = MathUtils.normalize(radial);
    if (normRadial.x === 0 && normRadial.y === 0) {
      return { x: 1, y: 0 };
    }
    // Tangentialer 90-Grad-Vektor
    return clockwise
      ? { x: -normRadial.y, y: normRadial.x }
      : { x: normRadial.y, y: -normRadial.x };
  }
}

/**
 * Particle - Physik- & Orbit-Mechanik
 */
export class Particle {
  public pos: Vector2D;
  public vel: Vector2D;
  public radius: number;
  public isTethered: boolean = false;
  public currentAnchor: Anchor | null = null;
  public angularVelocity: number = 0; // in Radian/s
  public orbitAngle: number = 0;
  public orbitRadius: number = 0;

  constructor(x: number, y: number, radius: number = 6) {
    this.pos = { x, y };
    this.vel = { x: 0, y: -300 }; // Standardflug nach oben
    this.radius = radius;
  }

  tetherTo(anchor: Anchor, clockwise: boolean = true): void {
    this.isTethered = true;
    this.currentAnchor = anchor;
    this.orbitRadius = Math.max(10, MathUtils.distance(this.pos, anchor));
    this.orbitAngle = Math.atan2(this.pos.y - anchor.y, this.pos.x - anchor.x);
    
    // Linear-Geschwindigkeit in Winkelgeschwindigkeit umrechnen (v = omega * r => omega = v / r)
    const currentSpeed = Math.hypot(this.vel.x, this.vel.y) || 300;
    this.angularVelocity = (currentSpeed / this.orbitRadius) * (clockwise ? 1 : -1);
  }

  release(): void {
    if (!this.isTethered || !this.currentAnchor) return;
    const tangent = MathUtils.calculateTangent(
      this.pos,
      this.currentAnchor,
      this.angularVelocity >= 0
    );
    const speed = Math.abs(this.angularVelocity) * this.orbitRadius;
    this.vel = { x: tangent.x * speed, y: tangent.y * speed };
    this.isTethered = false;
    this.currentAnchor = null;
  }

  update(dt: number): void {
    if (this.isTethered && this.currentAnchor) {
      // Orbit-Phase: Winkel inkrementieren
      this.orbitAngle += this.angularVelocity * dt;
      this.pos.x = this.currentAnchor.x + Math.cos(this.orbitAngle) * this.orbitRadius;
      this.pos.y = this.currentAnchor.y + Math.sin(this.orbitAngle) * this.orbitRadius;
    } else {
      // Freier Flug mit Delta-Time-Skalierung
      this.pos.x += this.vel.x * dt;
      this.pos.y += this.vel.y * dt;
    }
  }

  getCentripetalAcceleration(): number {
    if (!this.isTethered || this.orbitRadius === 0) return 0;
    const v = Math.abs(this.angularVelocity) * this.orbitRadius;
    return (v * v) / this.orbitRadius; // a = v^2 / r
  }
}

/**
 * StateStore - Highscore & Spielzustands-Persistenz
 */
export class StateStore {
  private static readonly STORAGE_KEY = 'orbit_tether_highscore';
  private static highscore: number = 0;

  static reset(): void {
    this.highscore = 0;
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(this.STORAGE_KEY);
    }
  }

  static getHighScore(): number {
    if (typeof localStorage !== 'undefined') {
      const val = localStorage.getItem(this.STORAGE_KEY);
      if (val !== null) {
        const parsed = parseInt(val, 10);
        return isNaN(parsed) ? 0 : parsed;
      }
    }
    return this.highscore;
  }

  static saveHighScore(score: number): boolean {
    if (score > this.getHighScore()) {
      this.highscore = score;
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(this.STORAGE_KEY, score.toString());
      }
      return true;
    }
    return false;
  }
}

// ==========================================
// TEST-SUITE: MathUtils, Particle, StateStore
// ==========================================

describe('MathUtils - Kollisions- und Vektormathematik', () => {
  describe('checkCircleCollision', () => {
    it('soll Überlappung zweier Kreise korrekt als Kollision erkennen', () => {
      const p1 = { x: 0, y: 0 };
      const p2 = { x: 5, y: 0 };
      // r1 + r2 = 4 + 4 = 8 > dist (5)
      expect(MathUtils.checkCircleCollision(p1, 4, p2, 4)).toBe(true);
    });

    it('soll exakte Grenzberührung (d = r1 + r2) als Kollision werten', () => {
      const p1 = { x: 0, y: 0 };
      const p2 = { x: 10, y: 0 };
      // dist = 10, r1 + r2 = 3 + 7 = 10
      expect(MathUtils.checkCircleCollision(p1, 3, p2, 7)).toBe(true);
    });

    it('soll distanzierte Kreise (keine Berührung) als false werten', () => {
      const p1 = { x: 0, y: 0 };
      const p2 = { x: 20, y: 20 };
      expect(MathUtils.checkCircleCollision(p1, 5, p2, 5)).toBe(false);
    });
  });

  describe('distance & normalize', () => {
    it('soll die euklidische Distanz präzise berechnen', () => {
      const p1 = { x: 0, y: 0 };
      const p2 = { x: 3, y: 4 };
      expect(MathUtils.distance(p1, p2)).toBeCloseTo(5);
    });

    it('soll Vektoren auf Einheitslänge 1 normalisieren', () => {
      const v = { x: 0, y: 10 };
      const norm = MathUtils.normalize(v);
      expect(norm.x).toBeCloseTo(0);
      expect(norm.y).toBeCloseTo(1);
    });

    it('soll Zero-Division Guard bei Nullvektor {0, 0} einhalten', () => {
      const zeroV = { x: 0, y: 0 };
      const norm = MathUtils.normalize(zeroV);
      expect(norm).toEqual({ x: 0, y: 0 });
    });
  });
});

describe('Particle - Physik & Orbit-Berechnung', () => {
  let particle: Particle;
  const anchor: Anchor = { x: 100, y: 100, radius: 20 };

  beforeEach(() => {
    particle = new Particle(100, 50, 5); // 50 Pixel über dem Anker
  });

  it('soll linearen Flug mit Delta-Time im freien Flug korrekt anwenden', () => {
    particle.vel = { x: 100, y: 200 };
    particle.update(0.1); // dt = 0.1s
    expect(particle.pos.x).toBeCloseTo(110);
    expect(particle.pos.y).toBeCloseTo(70);
  });

  it('soll sich an einen Anker binden und Zentripetalbeschleunigung berechnen', () => {
    particle.tetherTo(anchor, true);
    expect(particle.isTethered).toBe(true);
    expect(particle.currentAnchor).toEqual(anchor);
    expect(particle.orbitRadius).toBeCloseTo(50);

    const a_c = particle.getCentripetalAcceleration();
    expect(a_c).toBeGreaterThan(0);
  });

  it('soll bei Orbit-Update die Kreisbahn einhalten', () => {
    particle.tetherTo(anchor, true);
    const initialRadius = particle.orbitRadius;

    particle.update(0.05);

    const newDist = MathUtils.distance(particle.pos, anchor);
    expect(newDist).toBeCloseTo(initialRadius, 3);
  });

  it('soll beim Loslassen mit tangentialem Vektor weiterfliegen', () => {
    particle.tetherTo(anchor, true);
    particle.release();

    expect(particle.isTethered).toBe(false);
    expect(particle.currentAnchor).toBeNull();
    // Geschwindigkeit muss ungleich 0 sein und tangentiale Richtung haben
    const speed = Math.hypot(particle.vel.x, particle.vel.y);
    expect(speed).toBeGreaterThan(0);
  });
});

describe('StateStore - Highscore Persistenz', () => {
  beforeEach(() => {
    StateStore.reset();
  });

  it('soll initial Highscore 0 liefern', () => {
    expect(StateStore.getHighScore()).toBe(0);
  });

  it('soll neuen Highscore speichern und bei niedrigerem Wert unverändert bleiben', () => {
    const savedFirst = StateStore.saveHighScore(150);
    expect(savedFirst).toBe(true);
    expect(StateStore.getHighScore()).toBe(150);

    const savedLower = StateStore.saveHighScore(100);
    expect(savedLower).toBe(false);
    expect(StateStore.getHighScore()).toBe(150);
  });

  it('soll reset() sauber ausführen', () => {
    StateStore.saveHighScore(500);
    expect(StateStore.getHighScore()).toBe(500);
    StateStore.reset();
    expect(StateStore.getHighScore()).toBe(0);
  });
});
