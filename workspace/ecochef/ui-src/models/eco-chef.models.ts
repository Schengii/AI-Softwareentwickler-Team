/**
 * eco-chef.models.ts
 * Datenmodelle und Schnittstellen für Eco-Chef
 */

export type EcoScoreGrade = 'a' | 'b' | 'c' | 'd' | 'e' | 'unknown';
export type NutriScoreGrade = 'a' | 'b' | 'c' | 'd' | 'e' | 'unknown';
export type DifficultyLevel = 'easy' | 'medium' | 'hard';

export interface NutritionInfo {
  calories?: number;
  protein?: number;
  carbohydrates?: number;
  fat?: number;
  fiber?: number;
}

export interface RecipeIngredient {
  name: string;
  amount: number;
  unit: string;
  category?: string;
  inStock?: boolean;
}

export interface RecipeStep {
  stepNumber: number;
  instruction: string;
  durationMinutes?: number;
  tip?: string;
}

export interface Recipe {
  id?: string;
  title: string;
  description?: string;
  prepTimeMinutes?: number;
  cookTimeMinutes?: number;
  servings?: number;
  difficulty: DifficultyLevel;
  dietaryCategory?: string[];
  ingredients: RecipeIngredient[];
  steps: RecipeStep[];
  nutrition?: NutritionInfo;
  ecoScoreGrade: EcoScoreGrade;
  ecoScoreExplanation?: string;
  estimatedCo2Grams?: number;
  imageUrl?: string;
  createdAt?: number | string;
}

export interface RecipeGenerationOptions {
  availableIngredients: (string | { name: string; amount: number; unit: string })[];
  dietaryPreferences?: string[];
  allergensToAvoid?: string[];
  servings?: number;
  maxPrepTimeMinutes?: number;
  maxCookingTimeMinutes?: number;
  targetDifficulty?: DifficultyLevel;
  extraWishes?: string;
  cuisineType?: string;
  apiKey?: string;
}

export interface BarcodeProductInfo {
  barcode?: string;
  name: string;
  brand?: string;
  ecoScore: EcoScoreGrade;
  nutriScore: NutriScoreGrade;
  imageUrl?: string;
  ingredients?: string[];
  allergens?: string[];
  category?: string;
}

export interface PantryItem {
  id: string;
  name: string;
  quantity: number;
  unit: string;
  expirationDate?: string | Date;
  category?: string;
  ecoScore?: EcoScoreGrade;
  nutriScore?: NutriScoreGrade;
  barcode?: string;
  addedAt?: number | Date;
}

export interface RecipeRequest {
  ingredients: string[];
  dietaryRestrictions: string[];
  mealType: 'breakfast' | 'lunch' | 'dinner' | 'snack';
}

export interface RecipeResponse {
  id: string;
  title: string;
  instructions: string[];
  ingredients: string[];
  imageUrl?: string;
  timestamp: number;
}

export interface GeminiServiceConfig {
  apiKey: string;
  model: 'gemini-2.0-flash' | 'gemini-1.5-flash' | 'imagen-3.0';
}
