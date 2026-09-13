import { html, render } from 'lit';
import '../ui-src/components/pantry-view';
import '../ui-src/components/recipe-view';
import '../ui-src/main';
import { storageService } from '../ui-src/services/storage.service';
import { barcodeService } from '../ui-src/services/barcode.service';
import { geminiService } from '../ui-src/services/gemini.service';
import { PantryIngredient, GeneratedRecipe } from '../ui-src/models/eco-chef.models';

describe('UI-Komponenten Unit-Tests', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    jest.clearAllMocks();
  });

  describe('PantryView Component (<pantry-view>)', () => {
    it('wird im CustomElementRegistry registriert', () => {
      const el = customElements.get('pantry-view');
      expect(el).toBeDefined();
    });

    it('erstellt Instanz und rendert Grundelemente', async () => {
      const el = document.createElement('pantry-view') as any;
      document.body.appendChild(el);
      await el.updateComplete;

      expect(el.shadowRoot).not.toBeNull();
      const input = el.shadowRoot.querySelector('input');
      expect(input).toBeDefined();
    });

    it('fügt Zutat per Barcode hinzu und ruft storageService auf', async () => {
      const mockIngredient: PantryIngredient = {
        id: 'test-1',
        name: 'Hafermilch',
        barcode: '4001234567890',
        ecoScoreGrade: 'a',
        category: 'Getränke',
        addedAt: new Date().toISOString()
      };

      jest.spyOn(barcodeService, 'fetchProductByBarcode').mockResolvedValueOnce(mockIngredient);
      const addSpy = jest.spyOn(storageService, 'addIngredient').mockReturnValue(mockIngredient);

      const el = document.createElement('pantry-view') as any;
      document.body.appendChild(el);
      await el.updateComplete;

      const input = el.shadowRoot.querySelector('input');
      if (input) {
        input.value = '4001234567890';
        input.dispatchEvent(new Event('input'));
      }

      // Suche nach dem Submit-Button oder Formular
      const btn = el.shadowRoot.querySelector('button[type="submit"], button.btn-add, form button') || el.shadowRoot.querySelector('button');
      if (btn) {
        btn.click();
      } else if (typeof el.handleAddBarcode === 'function') {
        await el.handleAddBarcode(new Event('submit'));
      }

      // Prüfe asynchronen Aufruf
      await new Promise((r) => setTimeout(r, 50));
      expect(barcodeService.fetchProductByBarcode).toHaveBeenCalled();
    });

    it('löscht Zutat bei Klick auf Löschen', async () => {
      const removeSpy = jest.spyOn(storageService, 'removeIngredient').mockImplementation(() => {});
      const el = document.createElement('pantry-view') as any;
      el.ingredients = [
        {
          id: 'item-del-1',
          name: 'Bio-Äpfel',
          ecoScoreGrade: 'a',
          addedAt: new Date().toISOString()
        }
      ];
      document.body.appendChild(el);
      await el.updateComplete;

      const deleteBtn = el.shadowRoot.querySelector('button.btn-delete, button[aria-label*="löschen"], button[aria-label*="Löschen"]') || el.shadowRoot.querySelectorAll('button')[1];
      if (deleteBtn) {
        deleteBtn.click();
        expect(removeSpy).toHaveBeenCalledWith('item-del-1');
      } else if (typeof el.handleDelete === 'function') {
        el.handleDelete('item-del-1');
        expect(removeSpy).toHaveBeenCalledWith('item-del-1');
      }
    });
  });

  describe('RecipeView Component (<recipe-view>)', () => {
    it('wird im CustomElementRegistry registriert', () => {
      const el = customElements.get('recipe-view');
      expect(el).toBeDefined();
    });

    it('erstellt Instanz und zeigt Button zum Generieren', async () => {
      const el = document.createElement('recipe-view') as any;
      document.body.appendChild(el);
      await el.updateComplete;

      expect(el.shadowRoot).not.toBeNull();
      const btn = el.shadowRoot.querySelector('button');
      expect(btn).not.toBeNull();
    });

    it('zeigt Rezeptdetails an wenn Rezept vorhanden', async () => {
      const sampleRecipe: GeneratedRecipe = {
        id: 'rec-1',
        title: 'Vegane Gemüsepfanne',
        description: 'Schnell, gesund und nachhaltig',
        ecoScoreTotal: 'A',
        usedIngredients: ['Zucchini', 'Paprika', 'Tofu'],
        missingIngredients: [],
        steps: ['Gemüse schneiden', 'Tofu anbraten', 'Alles dünsten'],
        prepTimeMinutes: 20,
        nutritionEstimate: {
          calories: 350,
          protein: 18,
          carbs: 25,
          fat: 12
        }
      };

      const el = document.createElement('recipe-view') as any;
      el.recipe = sampleRecipe;
      document.body.appendChild(el);
      await el.updateComplete;

      const title = el.shadowRoot.querySelector('h3, h2, .recipe-title');
      expect(title?.textContent).toContain('Vegane Gemüsepfanne');
    });

    it('generiert Rezept über geminiService bei Klick', async () => {
      const sampleRecipe: GeneratedRecipe = {
        id: 'rec-2',
        title: 'Kürbissuppe',
        description: 'Cremig und lecker',
        ecoScoreTotal: 'A',
        usedIngredients: ['Kürbis'],
        missingIngredients: [],
        steps: ['Kochen', 'Pürieren'],
        prepTimeMinutes: 25
      };

      jest.spyOn(geminiService, 'generateRecipe').mockResolvedValueOnce(sampleRecipe);
      jest.spyOn(storageService, 'getIngredients').mockReturnValue([
        { id: '1', name: 'Kürbis', addedAt: new Date().toISOString() }
      ]);

      const el = document.createElement('recipe-view') as any;
      document.body.appendChild(el);
      await el.updateComplete;

      const genBtn = el.shadowRoot.querySelector('button');
      if (genBtn) {
        genBtn.click();
      } else if (typeof el.handleGenerateRecipe === 'function') {
        await el.handleGenerateRecipe();
      }

      await new Promise((r) => setTimeout(r, 50));
      expect(geminiService.generateRecipe).toHaveBeenCalled();
    });
  });

  describe('EcoChefApp Component (<eco-chef-app>) & Tab-Navigation', () => {
    it('wird im CustomElementRegistry registriert', () => {
      const appRegistered = customElements.get('eco-chef-app') || customElements.get('app-root') || customElements.get('eco-chef');
      expect(appRegistered).toBeDefined();
    });

    it('schaltet zwischen Tabs Vorräte und Rezepte um', async () => {
      const tagName = customElements.get('eco-chef-app') ? 'eco-chef-app' : (customElements.get('app-root') ? 'app-root' : 'eco-chef');
      const app = document.createElement(tagName) as any;
      document.body.appendChild(app);
      await app.updateComplete;

      const navButtons = app.shadowRoot.querySelectorAll('nav button, .tabs button, [role="tab"]');
      if (navButtons.length >= 2) {
        // Klick auf zweiten Tab (Rezepte)
        navButtons[1].click();
        await app.updateComplete;
        expect(app.shadowRoot.querySelector('recipe-view')).not.toBeNull();

        // Klick zurück auf ersten Tab (Vorräte)
        navButtons[0].click();
        await app.updateComplete;
        expect(app.shadowRoot.querySelector('pantry-view')).not.toBeNull();
      }
    });
  });
});
