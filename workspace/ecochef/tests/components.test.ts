import { storageService } from '../ui-src/services/storage.service';
import { barcodeService } from '../ui-src/services/barcode.service';
import { geminiService } from '../ui-src/services/gemini.service';
import { PantryItem, Recipe, BarcodeProductInfo } from '../ui-src/models/eco-chef.models';
import '../ui-src/components/pantry-view';
import '../ui-src/components/recipe-view';
import '../ui-src/main';

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
      const mockProduct: BarcodeProductInfo = {
        barcode: '4001234567890',
        name: 'Hafermilch',
        ecoScore: 'a',
        nutriScore: 'a'
      };
      const mockPantryItem: PantryItem = {
        id: 'test-1',
        name: 'Hafermilch',
        quantity: 1,
        unit: 'Stück',
        barcode: '4001234567890',
        ecoScore: 'a'
      };

      jest.spyOn(storageService, 'getPantryItems').mockReturnValue([]);
      jest.spyOn(barcodeService, 'getProductByBarcode').mockResolvedValueOnce(mockProduct);
      jest.spyOn(barcodeService, 'toPantryItem').mockReturnValueOnce(mockPantryItem);
      const addSpy = jest.spyOn(storageService, 'addPantryItem').mockReturnValue(mockPantryItem);

      const el = document.createElement('pantry-view') as any;
      document.body.appendChild(el);
      await el.updateComplete;

      const input = el.shadowRoot.querySelector('input');
      input.value = '4001234567890';
      input.dispatchEvent(new Event('input'));

      const form = el.shadowRoot.querySelector('form');
      form.dispatchEvent(new Event('submit', { cancelable: true }));

      await new Promise((r) => setTimeout(r, 50));
      expect(barcodeService.getProductByBarcode).toHaveBeenCalledWith('4001234567890');
      expect(addSpy).toHaveBeenCalledWith(mockPantryItem);
    });

    it('löscht Zutat bei Klick auf Löschen', async () => {
      const items: PantryItem[] = [
        { id: 'item-del-1', name: 'Bio-Äpfel', quantity: 2, unit: 'Stück' }
      ];
      jest.spyOn(storageService, 'getPantryItems').mockReturnValue(items);
      const removeSpy = jest.spyOn(storageService, 'removePantryItem').mockImplementation(() => {});

      const el = document.createElement('pantry-view') as any;
      document.body.appendChild(el);
      await el.updateComplete;

      const deleteBtn = el.shadowRoot.querySelector('button.btn-danger, button[aria-label*="Löschen"]');
      expect(deleteBtn).not.toBeNull();
      deleteBtn.click();

      expect(removeSpy).toHaveBeenCalledWith('item-del-1');
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
      const sampleRecipe: Recipe = {
        id: 'rec-1',
        title: 'Vegane Gemüsepfanne',
        description: 'Schnell, gesund und nachhaltig',
        difficulty: 'easy',
        ingredients: [{ name: 'Zucchini', amount: 1, unit: 'Stück' }],
        steps: [{ stepNumber: 1, instruction: 'Gemüse schneiden' }],
        ecoScoreGrade: 'a'
      };

      const el = document.createElement('recipe-view') as any;
      document.body.appendChild(el);
      el.recipe = sampleRecipe;
      await el.updateComplete;

      const title = el.shadowRoot.querySelector('h3');
      expect(title?.textContent).toContain('Vegane Gemüsepfanne');
    });

    it('generiert Rezept über geminiService bei Klick', async () => {
      const sampleRecipe: Recipe = {
        id: 'rec-2',
        title: 'Kürbissuppe',
        description: 'Cremig und lecker',
        difficulty: 'easy',
        ingredients: [{ name: 'Kürbis', amount: 1, unit: 'Stück' }],
        steps: [{ stepNumber: 1, instruction: 'Kochen' }, { stepNumber: 2, instruction: 'Pürieren' }],
        ecoScoreGrade: 'a'
      };

      jest.spyOn(storageService, 'getPantryItems').mockReturnValue([
        { id: '1', name: 'Kürbis', quantity: 1, unit: 'Stück' }
      ]);
      jest.spyOn(geminiService, 'generateRecipe').mockResolvedValueOnce(sampleRecipe);

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
      expect(navButtons.length).toBeGreaterThanOrEqual(2);

      // Klick auf zweiten Tab (Rezepte)
      navButtons[1].click();
      await app.updateComplete;
      expect(app.shadowRoot.querySelector('recipe-view')).not.toBeNull();

      // Klick zurück auf ersten Tab (Vorräte)
      navButtons[0].click();
      await app.updateComplete;
      expect(app.shadowRoot.querySelector('pantry-view')).not.toBeNull();
    });
  });
});
