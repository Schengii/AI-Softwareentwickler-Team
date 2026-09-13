import { LitElement, html, css } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { barcodeService } from '../services/barcode.service';
import { storageService } from '../services/storage.service';
import { PantryItem, EcoScoreGrade } from '../models/eco-chef.models';

@customElement('pantry-view')
export class PantryView extends LitElement {
  @state() private items: PantryItem[] = [];
  @state() private barcodeInput: string = '';
  @state() private manualName: string = '';
  @state() private manualQuantity: number = 1;
  @state() private manualUnit: string = 'g';
  @state() private isLoading: boolean = false;
  @state() private errorMessage: string = '';
  @state() private successMessage: string = '';

  static styles = css`
    :host {
      display: block;
      padding: 1rem;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #2d3748;
    }

    .card {
      background: #ffffff;
      border-radius: 12px;
      padding: 1.25rem;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
      margin-bottom: 1.5rem;
    }

    h2 {
      margin-top: 0;
      color: #2e7d32;
      font-size: 1.4rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .form-group {
      display: flex;
      gap: 0.5rem;
      margin-bottom: 0.75rem;
      flex-wrap: wrap;
    }

    input, select, button {
      font-size: 0.95rem;
      padding: 0.5rem 0.75rem;
      border-radius: 6px;
      border: 1px solid #cbd5e0;
    }

    input:focus, select:focus {
      outline: none;
      border-color: #38a169;
      box-shadow: 0 0 0 3px rgba(56, 161, 105, 0.2);
    }

    .btn-primary {
      background-color: #2e7d32;
      color: white;
      border: none;
      font-weight: 600;
      cursor: pointer;
      transition: background-color 0.2s;
    }

    .btn-primary:hover:not(:disabled) {
      background-color: #1b5e20;
    }

    .btn-danger {
      background-color: #e53e3e;
      color: white;
      border: none;
      cursor: pointer;
      padding: 0.25rem 0.5rem;
      font-size: 0.85rem;
    }

    .btn-danger:hover {
      background-color: #c53030;
    }

    button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .feedback {
      padding: 0.75rem;
      border-radius: 6px;
      margin-bottom: 1rem;
      font-size: 0.9rem;
    }

    .error {
      background-color: #fed7d7;
      color: #9b2c2c;
      border: 1px solid #feb2b2;
    }

    .success {
      background-color: #c6f6d5;
      color: #22543d;
      border: 1px solid #9ae6b4;
    }

    .pantry-list {
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 0.75rem;
    }

    .pantry-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.75rem 1rem;
      background: #f7fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
    }

    .item-details {
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
    }

    .item-name {
      font-weight: 600;
      font-size: 1rem;
    }

    .item-meta {
      font-size: 0.85rem;
      color: #718096;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .badge {
      display: inline-block;
      padding: 0.15rem 0.4rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: bold;
      text-transform: uppercase;
    }

    .badge-eco-a { background: #2e7d32; color: white; }
    .badge-eco-b { background: #689f38; color: white; }
    .badge-eco-c { background: #fbc02d; color: #333; }
    .badge-eco-d { background: #f57c00; color: white; }
    .badge-eco-e { background: #d32f2f; color: white; }
    .badge-eco-unknown { background: #9e9e9e; color: white; }

    .empty-state {
      text-align: center;
      color: #718096;
      padding: 2rem;
      font-style: italic;
    }
  `;

  connectedCallback(): void {
    super.connectedCallback();
    this.loadPantryItems();
  }

  private loadPantryItems(): void {
    try {
      this.items = storageService.getPantryItems();
    } catch {
      this.errorMessage = 'Fehler beim Laden der Vorräte.';
    }
  }

  private async handleBarcodeSubmit(e: Event): Promise<void> {
    e.preventDefault();
    this.errorMessage = '';
    this.successMessage = '';

    const code = this.barcodeInput.trim();
    if (!code) {
      this.errorMessage = 'Bitte einen Barcode eingeben.';
      return;
    }

    this.isLoading = true;
    try {
      const product = await barcodeService.getProductByBarcode(code);
      const pantryItem = barcodeService.toPantryItem(product, 1, 'Stück');
      storageService.addPantryItem(pantryItem);
      this.loadPantryItems();
      this.barcodeInput = '';
      this.successMessage = `„${product.name}“ wurde zum Vorrat hinzugefügt!`;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Produkt konnte nicht gefunden werden.';
      this.errorMessage = msg;
    } finally {
      this.isLoading = false;
    }
  }

  private async handleManualSubmit(e: Event): Promise<void> {
    e.preventDefault();
    this.errorMessage = '';
    this.successMessage = '';

    const name = this.manualName.trim();
    if (!name) {
      this.errorMessage = 'Bitte einen Zutatennamen eingeben.';
      return;
    }

    const newItem: PantryItem = {
      id: `pantry-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
      name,
      quantity: Number(this.manualQuantity) || 1,
      unit: this.manualUnit || 'Stück',
      category: 'Lebensmittel',
      addedAt: Date.now()
    };

    try {
      storageService.addPantryItem(newItem);
      this.loadPantryItems();
      this.manualName = '';
      this.manualQuantity = 1;
      this.successMessage = `„${name}“ hinzugefügt!`;
    } catch {
      this.errorMessage = 'Fehler beim Speichern der Zutat.';
    }
  }

  private handleDeleteItem(id: string): void {
    try {
      storageService.removePantryItem(id);
      this.loadPantryItems();
    } catch {
      this.errorMessage = 'Fehler beim Löschen der Zutat.';
    }
  }

  private renderEcoBadge(grade?: EcoScoreGrade) {
    if (!grade) return null;
    return html`<span class="badge badge-eco-${grade.toLowerCase()}">Eco-Score ${grade.toUpperCase()}</span>`;
  }

  render() {
    return html`
      <div class="card">
        <h2>📦 Vorrat per Barcode erfassen</h2>
        <form @submit=${this.handleBarcodeSubmit} class="form-group">
          <input
            type="text"
            placeholder="Barcode scannen oder eingeben..."
            .value=${this.barcodeInput}
            @input=${(e: Event) => (this.barcodeInput = (e.target as HTMLInputElement).value)}
            ?disabled=${this.isLoading}
            aria-label="Barcode"
          />
          <button type="submit" class="btn-primary" ?disabled=${this.isLoading}>
            ${this.isLoading ? 'Lädt...' : 'Barcode suchen'}
          </button>
        </form>
      </div>

      <div class="card">
        <h2>✏️ Manuell Zutat hinzufügen</h2>
        <form @submit=${this.handleManualSubmit} class="form-group">
          <input
            type="text"
            placeholder="Zutat (z. B. Haferflocken)"
            .value=${this.manualName}
            @input=${(e: Event) => (this.manualName = (e.target as HTMLInputElement).value)}
            required
            aria-label="Zutatenname"
          />
          <input
            type="number"
            min="0.1"
            step="any"
            placeholder="Menge"
            style="width: 80px;"
            .value=${String(this.manualQuantity)}
            @input=${(e: Event) => (this.manualQuantity = parseFloat((e.target as HTMLInputElement).value) || 1)}
            aria-label="Menge"
          />
          <select
            .value=${this.manualUnit}
            @change=${(e: Event) => (this.manualUnit = (e.target as HTMLSelectElement).value)}
            aria-label="Einheit"
          >
            <option value="g">g</option>
            <option value="kg">kg</option>
            <option value="ml">ml</option>
            <option value="l">l</option>
            <option value="Stück">Stück</option>
            <option value="EL">EL</option>
            <option value="TL">TL</option>
            <option value="Prise">Prise</option>
          </select>
          <button type="submit" class="btn-primary">Hinzufügen</button>
        </form>
      </div>

      ${this.errorMessage ? html`<div class="feedback error" role="alert">${this.errorMessage}</div>` : ''}
      ${this.successMessage ? html`<div class="feedback success" role="status" aria-live="polite">${this.successMessage}</div>` : ''}

      <div class="card">
        <h2>Aktuelle Vorräte (${this.items.length})</h2>
        ${this.items.length === 0
          ? html`<div class="empty-state">Noch keine Zutaten im Vorrat vorhanden.</div>`
          : html`
              <ul class="pantry-list">
                ${this.items.map(
                  (item) => html`
                    <li class="pantry-item">
                      <div class="item-details">
                        <span class="item-name">${item.name}</span>
                        <div class="item-meta">
                          <span>${item.quantity} ${item.unit}</span>
                          ${this.renderEcoBadge(item.ecoScore)}
                          ${item.category ? html`<span>• ${item.category}</span>` : ''}
                        </div>
                      </div>
                      <button
                        class="btn-danger"
                        @click=${() => this.handleDeleteItem(item.id)}
                        aria-label="Zutat löschen"
                      >
                        Löschen
                      </button>
                    </li>
                  `
                )}
              </ul>
            `}
      </div>
    `;
  }
}
