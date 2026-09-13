/**
 * StorageService zur Verwaltung lokaler Daten und Umsetzung des DSGVO-Löschkonzepts.
 */
export class StorageService {
  private static instance: StorageService;

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
}

export const storageService = StorageService.getInstance();
