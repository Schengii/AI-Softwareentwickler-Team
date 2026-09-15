/**
 * HapticService - Schnittstelle für haptisches Feedback auf iOS & Android
 * Bietet native Capacitor-Integration mit automatischem Fallback für Web-Vibration.
 */

export type HapticType = 'light' | 'medium' | 'heavy' | 'selection' | 'success' | 'warning' | 'error';

export interface HapticsPlugin {
  impact(options: { style: string }): Promise<void>;
  selectionChanged(): Promise<void>;
  notification(options: { type: string }): Promise<void>;
}

export class HapticService {
  private static instance: HapticService;
  private enabled: boolean = true;
  private capacitorHaptics: HapticsPlugin | null = null;

  private constructor() {
    this.initCapacitor();
  }

  public static getInstance(): HapticService {
    if (!HapticService.instance) {
      HapticService.instance = new HapticService();
    }
    return HapticService.instance;
  }

  private async initCapacitor(): Promise<void> {
    try {
      // Dynamischer Import des Capacitor Plugins für Web-Kompatibilität
      const hapticsModule = (await import('@capacitor/haptics')) as unknown as { Haptics: HapticsPlugin };
      this.capacitorHaptics = hapticsModule.Haptics;
    } catch {
      // Web-Fallback oder Plugin noch nicht gebündelt
      this.capacitorHaptics = null;
    }
  }

  public setEnabled(enabled: boolean): void {
    this.enabled = enabled;
  }

  public isEnabled(): boolean {
    return this.enabled;
  }

  /**
   * Triggert haptisches Feedback basierend auf Typ
   */
  public async trigger(type: HapticType): Promise<void> {
    if (!this.enabled) return;

    if (this.capacitorHaptics) {
      try {
        switch (type) {
          case 'light':
            await this.capacitorHaptics.impact({ style: 'LIGHT' });
            return;
          case 'medium':
            await this.capacitorHaptics.impact({ style: 'MEDIUM' });
            return;
          case 'heavy':
            await this.capacitorHaptics.impact({ style: 'HEAVY' });
            return;
          case 'selection':
            await this.capacitorHaptics.selectionChanged();
            return;
          case 'success':
            await this.capacitorHaptics.notification({ type: 'SUCCESS' });
            return;
          case 'warning':
            await this.capacitorHaptics.notification({ type: 'WARNING' });
            return;
          case 'error':
            await this.capacitorHaptics.notification({ type: 'ERROR' });
            return;
        }
      } catch {
        // Fallback auf Web Vibration bei Fehler
      }
    }

    // Web Fallback über navigator.vibrate
    if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
      try {
        switch (type) {
          case 'light':
          case 'selection':
            navigator.vibrate(15);
            break;
          case 'medium':
            navigator.vibrate(30);
            break;
          case 'heavy':
            navigator.vibrate(60);
            break;
          case 'success':
            navigator.vibrate([20, 50, 20]);
            break;
          case 'warning':
            navigator.vibrate([40, 40, 40]);
            break;
          case 'error':
            navigator.vibrate([60, 60, 100]);
            break;
        }
      } catch {
        // Ignorieren falls Browser Vibration blockiert
      }
    }
  }

  /** Kurzer Impuls beim Ankern an einen Gravitationspunkt */
  public anchorAttached(): Promise<void> {
    return this.trigger('medium');
  }

  /** Subtiles Klicken beim Loslassen / Katapultieren */
  public anchorReleased(): Promise<void> {
    return this.trigger('light');
  }

  /** Kollision mit Barriere oder Fehlschlag */
  public collision(): Promise<void> {
    return this.trigger('heavy');
  }

  /** Durchqueren eines Tors oder Score-Erhöhung */
  public scorePoint(): Promise<void> {
    return this.trigger('success');
  }
}

export const hapticService = HapticService.getInstance();
