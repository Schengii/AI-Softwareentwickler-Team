import { Recipe, RecipeGenerationOptions, EcoScoreGrade, DifficultyLevel } from '../models/eco-chef.models';
import { RECIPE_SYSTEM_PROMPT, PANTRY_SUGGESTIONS_PROMPT } from '../prompts/gemini.prompts';

declare const process: { env?: { GEMINI_API_KEY?: string } } | undefined;

export class GeminiService {
  private static instance: GeminiService;
  private userApiKey: string | null = null;
  private defaultBaseUrl = 'https://generativelanguage.googleapis.com/v1beta/models';
  private modelName = 'gemini-1.5-flash';

  private constructor() {}

  public static getInstance(): GeminiService {
    if (!GeminiService.instance) {
      GeminiService.instance = new GeminiService();
    }
    return GeminiService.instance;
  }

  public setApiKey(key: string): void {
    this.userApiKey = key.trim();
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.setItem('_ec_ak', btoa(this.userApiKey + '|ecochef'));
    }
  }

  public getApiKey(): string | null {
    if (this.userApiKey && this.userApiKey.length > 0) {
      return this.userApiKey;
    }
    if (typeof window !== 'undefined' && window.localStorage) {
      const stored = window.localStorage.getItem('_ec_ak');
      if (stored) {
        try {
          const decoded = atob(stored);
          if (decoded.endsWith('|ecochef')) {
            this.userApiKey = decoded.replace('|ecochef', '');
            return this.userApiKey;
          }
        } catch { /* ignore */ }
      }
    }
    try {
      if (typeof process !== 'undefined' && process.env && process.env.GEMINI_API_KEY) {
        return process.env.GEMINI_API_KEY;
      }
    } catch {
      // Ignore process reference errors in non-node envs
    }

    if (typeof window !== 'undefined' && (window as unknown as { GEMINI_API_KEY?: string }).GEMINI_API_KEY) {
      return (window as unknown as { GEMINI_API_KEY?: string }).GEMINI_API_KEY || null;
    }

    return null;
  }

  public hasValidApiKey(): boolean {
    const key = this.getApiKey();
    return !!key && key.trim().length > 10;
  }

  /**
   * Generiert ein vollständiges Rezept basierend auf Vorratszutaten und Kriterien
   */
  public async generateRecipe(options: RecipeGenerationOptions): Promise<Recipe> {
    const apiKey = options.apiKey || this.getApiKey();
    if (!apiKey) {
      throw new Error('Kein Gemini API-Key vorhanden. Bitte hinterlege einen API-Key in den Einstellungen.');
    }

    const ingredientsList = options.availableIngredients
      .map(item => (typeof item === 'string' ? item : `${item.amount} ${item.unit} ${item.name}`))
      .join(', ');

    const dietaryStr = options.dietaryPreferences?.length
      ? `Ernährungsweise: ${options.dietaryPreferences.join(', ')}`
      : '';
    const allergensStr = options.allergensToAvoid?.length
      ? `Zu meidende Allergene/Ausschlüsse: ${options.allergensToAvoid.join(', ')}`
      : '';
    const maxTimeStr = options.maxCookingTimeMinutes ? `Maximale Zubereitungszeit: ${options.maxCookingTimeMinutes} Minuten` : '';
    const servingsStr = options.servings ? `Portionen: ${options.servings}` : 'Portionen: 2';
    const difficultyStr = options.targetDifficulty ? `Schwierigkeitsgrad: ${options.targetDifficulty}` : '';
    const extraStr = options.extraWishes ? `Zusatzwünsche: ${options.extraWishes}` : '';

    const prompt = `${RECIPE_SYSTEM_PROMPT}\n\nVerfügbare Zutaten:\n${ingredientsList || 'Frische saisonale Zutaten'}\n\nKriterien:\n${dietaryStr}\n${allergensStr}\n${maxTimeStr}\n${servingsStr}\n${difficultyStr}\n${extraStr}`;

    const rawResponse = await this.callGeminiApi(prompt, apiKey);
    return this.parseRecipeResponse(rawResponse);
  }

  /**
   * Generiert Rezeptideen / Titel für gegebene Zutaten
   */
  public async generatePantryMealSuggestions(ingredients: string[], apiKeyOverride?: string): Promise<string[]> {
    const apiKey = apiKeyOverride || this.getApiKey();
    if (!apiKey) {
      throw new Error('Kein Gemini API-Key konfiguriert.');
    }

    const prompt = PANTRY_SUGGESTIONS_PROMPT.replace('{ingredients}', ingredients.join(', '));

    const rawResponse = await this.callGeminiApi(prompt, apiKey);
    try {
      const cleanJson = this.sanitizeJsonString(rawResponse);
      const parsed = JSON.parse(cleanJson);
      if (Array.isArray(parsed)) {
        return parsed.map(item => String(item).trim());
      }
    } catch {
      // Fallback: Zeilenweises Parsen
      return rawResponse
        .split('\n')
        .map(line => line.replace(/^[-*0-9.\s"]+|[",]+$/g, '').trim())
        .filter(line => line.length > 3);
    }
    return [];
  }

  private async callGeminiApi(prompt: string, apiKey: string): Promise<string> {
    const url = `${this.defaultBaseUrl}/${this.modelName}:generateContent?key=${encodeURIComponent(apiKey)}`;
    let response: Response;

    try {
      response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          contents: [
            {
              parts: [{ text: prompt }]
            }
          ],
          generationConfig: {
            temperature: 0.7,
            responseMimeType: 'application/json'
          }
        })
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Netzwerkfehler';
      throw new Error(`Verbindung zur Gemini API fehlgeschlagen: ${msg}`);
    }

    if (!response.ok) {
      if (response.status === 400 || response.status === 403) {
        throw new Error('Ungültiger Gemini API-Schlüssel oder fehlende Berechtigung');
      }
      if (response.status === 429) {
        throw new Error('Rate-Limit überschritten');
      }
      throw new Error(`Gemini API Serverfehler: HTTP ${response.status}`);
    }

    const data = await response.json();
    const candidateText = data?.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!candidateText) {
      throw new Error('Keine Textantwort erhalten.');
    }

    return candidateText;
  }

  private sanitizeJsonString(raw: string): string {
    let sanitized = raw.trim();
    if (sanitized.startsWith('```json')) {
      sanitized = sanitized.substring(7);
    } else if (sanitized.startsWith('```')) {
      sanitized = sanitized.substring(3);
    }
    if (sanitized.endsWith('```')) {
      sanitized = sanitized.substring(0, sanitized.length - 3);
    }
    return sanitized.trim();
  }

  private parseRecipeResponse(rawJson: string): Recipe {
    const clean = this.sanitizeJsonString(rawJson);
    let parsed: Partial<Recipe>;
    try {
      parsed = JSON.parse(clean);
    } catch {
      throw new Error('Gemini lieferte kein valides JSON-Format für das Rezept.');
    }

    const validDifficulty: DifficultyLevel =
      parsed.difficulty === 'medium' || parsed.difficulty === 'hard' ? parsed.difficulty : 'easy';
    const validEcoScore: EcoScoreGrade =
      parsed.ecoScoreGrade && ['a', 'b', 'c', 'd', 'e'].includes(parsed.ecoScoreGrade.toLowerCase())
        ? (parsed.ecoScoreGrade.toLowerCase() as EcoScoreGrade)
        : 'a';

    const recipe: Recipe = {
      id: parsed.id || `recipe-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
      title: parsed.title || 'Nachhaltiges EcoChef Gericht',
      description: parsed.description || 'Ein leckeres, ressourcenschonendes Gericht.',
      prepTimeMinutes: Number(parsed.prepTimeMinutes) || 15,
      cookTimeMinutes: Number(parsed.cookTimeMinutes) || 20,
      servings: Number(parsed.servings) || 2,
      difficulty: validDifficulty,
      dietaryCategory: Array.isArray(parsed.dietaryCategory) ? parsed.dietaryCategory : ['vegetarian'],
      ingredients: Array.isArray(parsed.ingredients)
        ? parsed.ingredients.map((ing) => ({
            name: ing.name || 'Zutat',
            amount: Number(ing.amount) || 1,
            unit: ing.unit || 'Stück',
            category: ing.category || 'Allgemein',
            inStock: ing.inStock ?? true
          }))
        : [],
      steps: Array.isArray(parsed.steps)
        ? parsed.steps.map((st, idx) => ({
            stepNumber: Number(st.stepNumber) || idx + 1,
            instruction: st.instruction || '',
            durationMinutes: st.durationMinutes ? Number(st.durationMinutes) : undefined,
            tip: st.tip
          }))
        : [],
      nutrition: {
        calories: Number(parsed.nutrition?.calories) || 400,
        protein: Number(parsed.nutrition?.protein) || 15,
        carbohydrates: Number(parsed.nutrition?.carbohydrates) || 50,
        fat: Number(parsed.nutrition?.fat) || 12,
        fiber: Number(parsed.nutrition?.fiber) || 6
      },
      ecoScoreGrade: validEcoScore,
      ecoScoreExplanation: parsed.ecoScoreExplanation || 'Geringer CO2-Fußabdruck durch pflanzliche und regionale Zutaten.',
      estimatedCo2Grams: Number(parsed.estimatedCo2Grams) || 350,
      createdAt: parsed.createdAt || new Date().toISOString()
    };

    return recipe;
  }
}

export const geminiService = GeminiService.getInstance();
