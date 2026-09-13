import { PantryItem } from '../models/eco-chef.models';

/**
 * StorageService zur Verwaltung lokaler Daten und Umsetzung des DSGVO-Löschkonzepts.
 */
export class StorageService {
  private static instance: StorageService;
  private readonly PANTRY_STORAGE_KEY = 'ecochef_pantry_items';

  private constructor() {}

  public static getInstance(): StorageService {
    if (!StorageService.instance) {
      StorageService.instance = new StorageService();
    }
    return StorageService.instance;
  }

  public getItem(key: string): string | null {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        return window.localStorage.getItem(key);
      }
    } catch {
      // Ignore storage access exceptions
    }
    return null;
  }

  public setItem(key: string, value: string): void {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        window.localStorage.setItem(key, value);
      }
    } catch {
      // Ignore storage access exceptions
    }
  }

  public removeItem(key: string): void {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        window.localStorage.removeItem(key);
      }
    } catch {
      // Ignore storage access exceptions
    }
  }

  /**
   * DSGVO Art. 17: Recht auf Löschung / Löschkonzept
   * Leert den gesamten localStorage sowie SessionStorage vollständig.
   */
  public clearAllData(): void {
    try {
      if (typeof window !== 'undefined') {
        if (window.localStorage) {
          window.localStorage.clear();
        }
        if (window.sessionStorage) {
          window.sessionStorage.clear();
        }
      }
    } catch (e) {
      console.error('Fehler beim Löschen des lokalen Speichers:', e);
    }
  }

  /**
   * Prüft den DSGVO-Onboarding-Status
   */
  public getOnboardingConsent(): { healthDataAccepted: boolean; geminiDataAccepted: boolean } | null {
    const raw = this.getItem('ecochef_gdpr_consent');
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  public saveOnboardingConsent(consent: { healthDataAccepted: boolean; geminiDataAccepted: boolean }): void {
    this.setItem('ecochef_gdpr_consent', JSON.stringify({
      ...consent,
      consentTimestamp: new Date().toISOString()
    }));
  }

  /**
   * Liest alle gespeicherten Vorratsdaten (PantryItem).
   * Gibt bei fehlendem oder defektem Datensatz ein leeres Array zurück, statt zu werfen.
   */
  public getPantryItems(): PantryItem[] {
    const raw = this.getItem(this.PANTRY_STORAGE_KEY);
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? (parsed as PantryItem[]) : [];
    } catch {
      return [];
    }
  }

  /**
   * Fügt ein PantryItem zum Vorrat hinzu und persistiert die aktualisierte Liste.
   */
  public addPantryItem(item: PantryItem): PantryItem {
    const items = this.getPantryItems();
    items.push(item);
    this.setItem(this.PANTRY_STORAGE_KEY, JSON.stringify(items));
    return item;
  }

  /**
   * Entfernt ein PantryItem anhand seiner id aus dem Vorrat.
   */
  public removePantryItem(id: string): void {
    const items = this.getPantryItems().filter((item) => item.id !== id);
    this.setItem(this.PANTRY_STORAGE_KEY, JSON.stringify(items));
  }
}

export const storageService = StorageService.getInstance();
