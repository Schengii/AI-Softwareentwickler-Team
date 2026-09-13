import { LitElement, html, css } from 'lit';
import { storageService } from '../services/storage.service';

export class OnboardingScreen extends LitElement {
  static styles = css`
    :host {
      display: block;
      font-family: system-ui, -apple-system, sans-serif;
      padding: 1.5rem;
      max-width: 600px;
      margin: 0 auto;
      color: #1f2937;
      background: #ffffff;
      border-radius: 12px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    }

    h2 {
      margin-top: 0;
      color: #166534;
      font-size: 1.5rem;
    }

    p {
      line-height: 1.5;
      font-size: 0.95rem;
      color: #4b5563;
    }

    .consent-group {
      margin: 1.5rem 0;
      display: flex;
      flex-direction: column;
      gap: 1.25rem;
    }

    .consent-item {
      display: flex;
      align-items: flex-start;
      gap: 0.75rem;
      padding: 0.75rem;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      background-color: #f9fafb;
    }

    .consent-item input[type='checkbox'] {
      margin-top: 0.25rem;
      width: 1.25rem;
      height: 1.25rem;
      cursor: pointer;
    }

    .consent-label {
      font-size: 0.9rem;
      line-height: 1.4;
      cursor: pointer;
    }

    .consent-label strong {
      color: #111827;
      display: block;
      margin-bottom: 0.25rem;
    }

    .actions {
      display: flex;
      gap: 1rem;
      justify-content: flex-end;
      margin-top: 1.5rem;
    }

    button {
      padding: 0.65rem 1.25rem;
      border-radius: 6px;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      border: none;
      transition: background-color 0.2s;
    }

    .btn-primary {
      background-color: #16a34a;
      color: white;
    }

    .btn-primary:disabled {
      background-color: #9ca3af;
      cursor: not-allowed;
    }

    .btn-danger {
      background-color: #ef4444;
      color: white;
    }

    .btn-danger:hover {
      background-color: #dc2626;
    }

    .danger-zone {
      margin-top: 2rem;
      padding-top: 1rem;
      border-top: 1px solid #e5e7eb;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  `;

  // Opt-In Vorgabe nach DSGVO: standardmäßig zwingend unangekreuzt (false)
  private healthConsent = false;
  private geminiConsent = false;

  static properties = {
    healthConsent: { type: Boolean },
    geminiConsent: { type: Boolean }
  };

  private handleHealthChange(e: Event) {
    this.healthConsent = (e.target as HTMLInputElement).checked;
    this.requestUpdate();
  }

  private handleGeminiChange(e: Event) {
    this.geminiConsent = (e.target as HTMLInputElement).checked;
    this.requestUpdate();
  }

  private handleSaveConsent() {
    if (!this.healthConsent || !this.geminiConsent) return;

    storageService.saveOnboardingConsent({
      healthDataAccepted: this.healthConsent,
      geminiDataAccepted: this.geminiConsent
    });

    this.dispatchEvent(new CustomEvent('onboarding-completed', {
      detail: { healthConsent: this.healthConsent, geminiConsent: this.geminiConsent },
      bubbles: true,
      composed: true
    }));
  }

  private handleClearAllData() {
    if (confirm('Möchtest du wirklich alle lokalen Daten unwiderruflich löschen?')) {
      storageService.clearAllData();
      this.healthConsent = false;
      this.geminiConsent = false;
      this.requestUpdate();
      alert('Alle Daten wurden vollständig aus dem lokalen Speicher gelöscht.');
      this.dispatchEvent(new CustomEvent('data-cleared', { bubbles: true, composed: true }));
    }
  }

  render() {
    const isConsentValid = this.healthConsent && this.geminiConsent;

    return html`
      <div>
        <h2>🌱 Willkommen bei EcoChef</h2>
        <p>
          Für die Nutzung von EcoChef und die Bereitstellung personalisierter, nachhaltiger Rezepte
          bitten wir um deine ausdrückliche Einwilligung gemäß DSGVO (Art. 6 & Art. 9 DSGVO).
        </p>

        <div class="consent-group">
          <!-- 1. Gesundheitsdaten (Allergene) - Unchecked Default -->
          <div class="consent-item">
            <input
              type="checkbox"
              id="health-consent"
              .checked=${this.healthConsent}
              @change=${this.handleHealthChange}
              aria-required="true"
            />
            <label for="health-consent" class="consent-label">
              <strong>Verarbeitung von Gesundheitsdaten (Allergene & Unverträglichkeiten)</strong>
              Ich willige ausdrücklich ein, dass EcoChef Angaben zu meinen Allergenen und Unverträglichkeiten
              lokal verarbeitet, um Rezepte auf meine gesundheitlichen Bedürfnisse anzupassen.
            </label>
          </div>

          <!-- 2. Google Gemini API Datenübermittlung - Unchecked Default -->
          <div class="consent-item">
            <input
              type="checkbox"
              id="gemini-consent"
              .checked=${this.geminiConsent}
              @change=${this.handleGeminiChange}
              aria-required="true"
            />
            <label for="gemini-consent" class="consent-label">
              <strong>Übermittlung von Daten an die Google Gemini API</strong>
              Ich willige ein, dass meine Zutatenangaben und Rezeptpräferenzen zur Generierung von
              Rezeptvorschlägen verschlüsselt an die Google Gemini API übertragen werden. Personenbezogene Daten
              werden dabei vorab automatisch gefiltert und maskiert.
            </label>
          </div>
        </div>

        <div class="actions">
          <button
            class="btn-primary"
            ?disabled=${!isConsentValid}
            @click=${this.handleSaveConsent}
          >
            Zustimmen & Weiter
          </button>
        </div>

        <!-- 4. Löschkonzept: Alle Daten löschen -->
        <div class="danger-zone">
          <span style="font-size: 0.85rem; color: #6b7280;">DSGVO Art. 17: Alle gespeicherten Daten unwiderruflich entfernen</span>
          <button class="btn-danger" @click=${this.handleClearAllData}>
            Alle Daten löschen
          </button>
        </div>
      </div>
    `;
  }
}

if (!customElements.get('eco-onboarding-screen')) {
  customElements.define('eco-onboarding-screen', OnboardingScreen);
}
