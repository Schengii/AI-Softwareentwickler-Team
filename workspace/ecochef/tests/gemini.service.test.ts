import { GeminiService } from '../ui-src/services/gemini.service';
import { RecipeGenerationOptions } from '../ui-src/models/eco-chef.models';

describe('GeminiService Unit Tests', () => {
  let geminiService: GeminiService;
  const mockApiKey = 'AIzaSyFakeKeyForTesting1234567890';

  beforeEach(() => {
    // Singleton-Instanz zurückholen und State bereinigen
    geminiService = GeminiService.getInstance();
    geminiService.setApiKey('');
    jest.clearAllMocks();
  });

  describe('Singleton-Muster & Initialisierung', () => {
    it('sollte immer dieselbe Instanz zurückgeben (Singleton)', () => {
      const instance1 = GeminiService.getInstance();
      const instance2 = GeminiService.getInstance();
      expect(instance1).toBe(instance2);
    });
  });

  describe('API-Key Handling & Validierung', () => {
    it('sollte gesetzten API-Key korrekt speichern und zurückgeben', () => {
      geminiService.setApiKey('  my-custom-api-key  ');
      expect(geminiService.getApiKey()).toBe('my-custom-api-key');
    });

    it('sollte hasValidApiKey korrekt nach Schlüssellänge validieren', () => {
      geminiService.setApiKey('kurz');
      expect(geminiService.hasValidApiKey()).toBe(false);

      geminiService.setApiKey(mockApiKey);
      expect(geminiService.hasValidApiKey()).toBe(true);
    });

    it('sollte Fehler werfen, wenn generateRecipe ohne API-Key aufgerufen wird', async () => {
      geminiService.setApiKey('');
      const options: RecipeGenerationOptions = {
        availableIngredients: ['Kartoffeln', 'Zwiebeln']
      };

      await expect(geminiService.generateRecipe(options)).rejects.toThrow(
        'Kein Gemini API-Key vorhanden'
      );
    });
  });

  describe('generateRecipe & Request-Aufbau', () => {
    it('sollte Gemini API korrekt aufrufen und Rezept parsen', async () => {
      geminiService.setApiKey(mockApiKey);

      const fakeRecipeJson = JSON.stringify({
        title: 'Kartoffel-Gemüse-Pfanne',
        description: 'Ein schnelles, nachhaltiges Pfannengericht.',
        prepTimeMinutes: 10,
        cookTimeMinutes: 20,
        servings: 2,
        difficulty: 'easy',
        dietaryCategory: ['vegan'],
        ingredients: [
          { name: 'Kartoffeln', amount: 300, unit: 'g', category: 'Gemüse', inStock: true }
        ],
        steps: [
          { stepNumber: 1, instruction: 'Kartoffeln schneiden und anbraten.', durationMinutes: 10, tip: 'Schale dranlassen.' }
        ],
        nutrition: {
          calories: 320,
          protein: 8,
          carbohydrates: 60,
          fat: 4,
          fiber: 6
        },
        ecoScoreGrade: 'a',
        ecoScoreExplanation: 'Regionale Zutaten mit minimalem CO2-Fußabdruck.',
        estimatedCo2Grams: 280
      });

      const mockFetchResponse = {
        ok: true,
        status: 200,
        json: async () => ({
          candidates: [
            {
              content: {
                parts: [{ text: `\`\`\`json\n${fakeRecipeJson}\n\`\`\`` }]
              }
            }
          ]
        })
      };

      global.fetch = jest.fn().mockResolvedValue(mockFetchResponse as unknown as Response);

      const options: RecipeGenerationOptions = {
        availableIngredients: ['Kartoffeln', 'Rosmarin'],
        dietaryPreferences: ['vegan'],
        servings: 2
      };

      const recipe = await geminiService.generateRecipe(options);

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [calledUrl, calledOptions] = (global.fetch as jest.Mock).mock.calls[0];
      expect(calledUrl).toContain('https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent');
      expect(calledUrl).toContain(encodeURIComponent(mockApiKey));
      expect(calledOptions.method).toBe('POST');

      expect(recipe.title).toBe('Kartoffel-Gemüse-Pfanne');
      expect(recipe.difficulty).toBe('easy');
      expect(recipe.ecoScoreGrade).toBe('a');
      expect(recipe.ingredients.length).toBe(1);
    });
  });

  describe('Fehlerbehandlung (400, 403, 429, Netzwerkfehler)', () => {
    beforeEach(() => {
      geminiService.setApiKey(mockApiKey);
    });

    it('sollte bei HTTP 400/403 eine verständliche Fehlermeldung zu ungültigem Schlüssel werfen', async () => {
      global.fetch = jest.fn().mockResolvedValue({
        ok: false,
        status: 403,
        statusText: 'Forbidden',
        json: async () => ({ error: { message: 'API_KEY_INVALID' } })
      } as unknown as Response);

      await expect(
        geminiService.generateRecipe({ availableIngredients: ['Apfel'] })
      ).rejects.toThrow('Ungültiger Gemini API-Schlüssel oder fehlende Berechtigung');
    });

    it('sollte bei HTTP 429 einen Rate-Limit-Fehler werfen', async () => {
      global.fetch = jest.fn().mockResolvedValue({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests',
        json: async () => ({ error: { message: 'Resource exhausted' } })
      } as unknown as Response);

      await expect(
        geminiService.generateRecipe({ availableIngredients: ['Apfel'] })
      ).rejects.toThrow('Rate-Limit überschritten');
    });

    it('sollte bei Netzwerkfehlern eine strukturierte Fehlermeldung liefern', async () => {
      global.fetch = jest.fn().mockRejectedValue(new Error('Connection timeout'));

      await expect(
        geminiService.generateRecipe({ availableIngredients: ['Apfel'] })
      ).rejects.toThrow('Verbindung zur Gemini API fehlgeschlagen: Connection timeout');
    });
  });

  describe('generatePantryMealSuggestions', () => {
    it('sollte Mahlzeitenvorschläge als String-Array zurückgeben', async () => {
      geminiService.setApiKey(mockApiKey);

      const suggestions = ['Kartoffelsuppe mit Kräutern', 'Bratkartoffeln Rustikal'];
      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          candidates: [
            {
              content: {
                parts: [{ text: JSON.stringify(suggestions) }]
              }
            }
          ]
        })
      } as unknown as Response);

      const result = await geminiService.generatePantryMealSuggestions(['Kartoffeln', 'Kräuter']);
      expect(result).toEqual(suggestions);
    });
  });
});
