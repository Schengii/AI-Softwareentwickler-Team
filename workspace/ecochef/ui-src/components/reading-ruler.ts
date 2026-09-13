import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';

/**
 * ReadingRuler - Kognitives Leselineal zur visuellen Zeilenfokussierung.
 */
@customElement('reading-ruler')
export class ReadingRuler extends LitElement {
  @property({ type: Boolean, reflect: true }) active = false;

  static styles = css`
    :host {
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 48px;
      background: rgba(255, 235, 59, 0.22);
      border-top: 2px solid rgba(245, 158, 11, 0.6);
      border-bottom: 2px solid rgba(245, 158, 11, 0.6);
      pointer-events: none;
      z-index: 99999;
      display: none;
      transform: translateY(-50%);
      transition: top 0.05s ease-out;
    }
    :host([active]) {
      display: block;
    }
  `;

  private handlePointerMove = (e: PointerEvent): void => {
    if (this.active) {
      this.style.top = `${e.clientY}px`;
    }
  };

  connectedCallback(): void {
    super.connectedCallback();
    window.addEventListener('pointermove', this.handlePointerMove, { passive: true });
  }

  disconnectedCallback(): void {
    window.removeEventListener('pointermove', this.handlePointerMove);
    super.disconnectedCallback();
  }

  render() {
    return html``;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'reading-ruler': ReadingRuler;
  }
}
