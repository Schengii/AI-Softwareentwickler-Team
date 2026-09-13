// ui-src/main.ts
import { LitElement, html, css, render } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import './components/onboarding-screen';
import './components/reading-ruler';
import './components/pantry-view';
import './components/recipe-view';

type EcoChefTab = 'pantry' | 'recipes';

/**
 * Wurzelkomponente der App: bindet <pantry-view> und <recipe-view> über einfache
 * Navigations-Tabs ("Vorräte" / "Rezepte") ein (Team-Goal 20260913, Aufgabe 3).
 */
@customElement('eco-chef-app')
export class EcoChefApp extends LitElement {
  @state() private activeTab: EcoChefTab = 'pantry';

  static styles = css`
    :host {
      display: block;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }

    nav.tabs {
      display: flex;
      gap: 0.5rem;
      padding: 1rem;
      background: #2e7d32;
    }

    nav.tabs button {
      background: transparent;
      border: none;
      color: white;
      font-weight: 600;
      font-size: 1rem;
      padding: 0.5rem 1.25rem;
      border-radius: 6px;
      cursor: pointer;
    }

    nav.tabs button.active {
      background: rgba(255, 255, 255, 0.25);
    }
  `;

  private selectTab(tab: EcoChefTab): void {
    this.activeTab = tab;
  }

  render() {
    return html`
      <nav class="tabs" role="tablist">
        <button
          role="tab"
          class=${this.activeTab === 'pantry' ? 'active' : ''}
          aria-selected=${this.activeTab === 'pantry'}
          @click=${() => this.selectTab('pantry')}
        >
          Vorräte
        </button>
        <button
          role="tab"
          class=${this.activeTab === 'recipes' ? 'active' : ''}
          aria-selected=${this.activeTab === 'recipes'}
          @click=${() => this.selectTab('recipes')}
        >
          Rezepte
        </button>
      </nav>
      ${this.activeTab === 'pantry' ? html`<pantry-view></pantry-view>` : html`<recipe-view></recipe-view>`}
    `;
  }
}

const appTemplate = html`
  <eco-onboarding-screen></eco-onboarding-screen>
  <reading-ruler></reading-ruler>
  <eco-chef-app></eco-chef-app>
`;

const appRoot = document.getElementById('app');
if (appRoot) {
  render(appTemplate, appRoot);
} else {
  console.error('Kritischer Fehler: App-Root-Element (#app) nicht in index.html gefunden.');
}
