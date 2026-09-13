import { BarcodeProductInfo, EcoScoreGrade, NutriScoreGrade, PantryItem } from '../models/eco-chef.models';

export interface OpenFoodFactsProductResponse {
  status: number;
  status_verbose?: string;
  code?: string;
  product?: {
    product_name?: string;
    product_name_de?: string;
    generic_name?: string;
    brands?: string;
    quantity?: string;
    categories_tags?: string[];
    ecoscore_grade?: string;
    nutriscore_grade?: string;
    allergens_tags?: string[];
    allergens_hierarchy?: string[];
    image_url?: string;
    image_front_url?: string;
    image_front_small_url?: string;
    ingredients_text?: string;
    ingredients_text_de?: string;
  };
}

export class BarcodeService {
  private static instance: BarcodeService;
  private readonly baseUrl = 'https://world.openfoodfacts.org/api/v2/product';
  private readonly cache = new Map<string, BarcodeProductInfo>();
  private readonly userAgent = 'EcoChefApp - Web/Cordova - Version 1.0 - Contact: info@domain.com';

  private constructor() {}

  public static getInstance(): BarcodeService {
    if (!BarcodeService.instance) {
      BarcodeService.instance = new BarcodeService();
    }
    return BarcodeService.instance;
  }

  /**
   * Bereinigt Barcode (entfernt Leerzeichen & Sonderzeichen)
   */
  public sanitizeBarcode(barcode: string): string {
    return (barcode || '').trim().replace(/[^0-9]/g, '');
  }

  /**
   * Validiert Barcode-Länge und Prüfziffer (EAN-8, EAN-13, UPC-A)
   */
  public isValidBarcode(rawBarcode: string): boolean {
    const code = this.sanitizeBarcode(rawBarcode);
    return code.length >= 8 && code.length <= 14;
  }

  /**
   * Holt Produktdaten von OpenFoodFacts anhand des Barcodes
   */
  public async getProductByBarcode(rawBarcode: string): Promise<BarcodeProductInfo> {
    const barcode = this.sanitizeBarcode(rawBarcode);

    if (!this.isValidBarcode(barcode)) {
      throw new Error(`Ungültiger Barcode: "${rawBarcode}". Erwartet werden 8 bis 14 Ziffern.`);
    }

    if (this.cache.has(barcode)) {
      return this.cache.get(barcode)!;
    }

    const endpoint = `${this.baseUrl}/${barcode}.json`;
    let response: Response;

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 8000);

      response = await fetch(endpoint, {\n        method: 'GET',\n        headers: {\n          'User-Agent': this.userAgent,\n          'Accept': 'application/json'\n        },\n        signal: controller.signal\n      });\n\n      clearTimeout(timeoutId);\n    } catch (err: unknown) {\n      if (err instanceof Error && err.name === 'AbortError') {\n        throw new Error(`Zeitüberschreitung bei der Abfrage von Barcode ${barcode}. Bitte Internetverbindung prüfen.`);\n      }\n      const msg = err instanceof Error ? err.message : 'Netzwerkfehler';\n      throw new Error(`Konnte OpenFoodFacts nicht erreichen: ${msg}`);\n    }\n\n    if (!response.ok) {\n      if (response.status === 404) {\n        throw new Error(`Produkt mit Barcode ${barcode} wurde bei OpenFoodFacts nicht gefunden.`);\n      }\n      throw new Error(`OpenFoodFacts Serverfehler: HTTP ${response.status}`);\n    }\n\n    const data = (await response.json()) as OpenFoodFactsProductResponse;\n\n    if (data.status === 0 || !data.product) {\n      throw new Error(`Produkt mit Barcode ${barcode} existiert nicht in der OpenFoodFacts-Datenbank.`);\n    }\n\n    const parsedInfo = this.mapToProductInfo(barcode, data.product);\n    this.cache.set(barcode, parsedInfo);\n\n    return parsedInfo;\n  }\n\n  /**\n   * Alias für getProductByBarcode zur Abwärtskompatibilität mit bestehenden Tests\n   */\n  public async getProductInfo(rawBarcode: string): Promise<BarcodeProductInfo> {\n    return this.getProductByBarcode(rawBarcode);\n  }\n\n  /**\n   * Wandelt BarcodeProductInfo in ein PantryItem um\n   */\n  public toPantryItem(product: BarcodeProductInfo, defaultAmount = 1, defaultUnit = 'Stück'): PantryItem {\n    return {\n      id: `pantry-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,\n      barcode: product.barcode,\n      name: product.name,\n      quantity: defaultAmount,\n      unit: defaultUnit,\n      category: product.category || 'Lebensmittel',\n      ecoScore: product.ecoScore,\n      nutriScore: product.nutriScore,\n      addedAt: Date.now()\n    };\n  }\n\n  /**\n   * Leert den internen Cache\n   */\n  public clearCache(): void {\n    this.cache.clear();\n  }\n\n  private mapToProductInfo(barcode: string, raw: NonNullable<OpenFoodFactsProductResponse['product']>): BarcodeProductInfo {\n    const name = raw.product_name_de || raw.product_name || raw.generic_name || 'Unbekanntes Lebensmittel';\n    const brand = raw.brands ? raw.brands.split(',')[0].trim() : undefined;\n\n    const rawEco = (raw.ecoscore_grade || 'unknown').toLowerCase();\n    const ecoScore: EcoScoreGrade = ['a', 'b', 'c', 'd', 'e'].includes(rawEco) ? (rawEco as EcoScoreGrade) : 'unknown';\n\n    const rawNutri = (raw.nutriscore_grade || 'unknown').toLowerCase();\n    const nutriScore: NutriScoreGrade = ['a', 'b', 'c', 'd', 'e'].includes(rawNutri)\n      ? (rawNutri as NutriScoreGrade)\n      : 'unknown';\n\n    const categories = (raw.categories_tags || [])\n      .map(cat => cat.replace(/^[a-z]{2}:/, '').replace(/-/g, ' '))\n      .filter(cat => cat.length > 0);\n\n    const allergens = (raw.allergens_tags || raw.allergens_hierarchy || [])\n      .map(all => all.replace(/^[a-z]{2}:/, '').replace(/-/g, ' ').trim())\n      .filter(all => all.length > 0);\n\n    const imageUrl = raw.image_front_url || raw.image_url || raw.image_front_small_url || undefined;\n    const ingredientsText = raw.ingredients_text_de || raw.ingredients_text || undefined;\n\n    return {\n      barcode,\n      name,\n      brand,\n      category: categories.length > 0 ? categories[0] : undefined,\n      ecoScore,\n      nutriScore,\n      allergens: Array.from(new Set(allergens)),\n      imageUrl,\n      ingredients: ingredientsText ? [ingredientsText] : undefined\n    };\n  }\n}\n\nexport const barcodeService = BarcodeService.getInstance();\n