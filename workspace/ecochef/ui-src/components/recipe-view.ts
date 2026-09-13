import { LitElement, html, css } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { geminiService } from '../services/gemini.service';
import { storageService } from '../services/storage.service';
import { Recipe } from '../models/eco-chef.models';

@customElement('recipe-view')
export class RecipeView extends LitElement {
  @state() private recipe: Recipe | null = null;
  @state() private isLoading: boolean = false;
  @state() private errorMessage: string = '';

  static styles = css`
    :host { display: block; padding: 1rem; font-family: system-ui, sans-serif; }
    .card { background: #fff; border-radius: 12px; padding: 1.25rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .btn-primary { background: #2e7d32; color: white; border: none; padding: 0.75rem 1rem; border-radius: 6px; cursor: pointer; font-weight: bold; }
    .btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
    .badge { padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.8rem; font-weight: bold; }
    .badge-eco-a { background: #2e7d32; color: white; }
    .error { color: #c53030; margin-top: 1rem; }
  `;

  private async generateNewRecipe() {
    this.isLoading = true;
    this.errorMessage = '';
    try {
      const items = await storageService.getPantryItems();
      this.recipe = await geminiService.generateRecipe({ availableIngredients: items });
    } catch (e) {
      this.errorMessage = 'Rezept konnte nicht generiert werden. Bitte Vorräte prüfen.';
    } finally {
      this.isLoading = false;
    }
  }

  render() {
    return html`
      <div class="card">
        <h2>👨‍🍳 EcoChef Rezept-Generator</h2>
        <button class="btn-primary" @click=${this.generateNewRecipe} ?disabled=${this.isLoading} aria-label="Neues Rezept generieren">
          ${this.isLoading ? 'Generiere...' : 'Neues Rezept generieren'}
        </button>
        ${this.errorMessage ? html`<p class="error" role="alert">${this.errorMessage}</p>` : ''}
        ${this.recipe ? html`
          <div style="margin-top: 1.5rem;">
            <h3>${this.recipe.title} <span class="badge badge-eco-${this.recipe.ecoScore.toLowerCase()}">Eco-Score ${this.recipe.ecoScore}</span></h3>
            <p>${this.recipe.description}</p>
            <h4>Zutaten:</h4>
            <ul>${this.recipe.ingredients.map(i => html`<li>${i}</li>`)}</ul>
            <h4>Schritte:</h4>
            <ol>${this.recipe.steps.map(s => html`<li>${s}</li>`)}</ol>
          </div>
        ` : ''}
      </div>
    `;
  }
}
