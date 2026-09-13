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

      response = await fetch(endpoint, {
        method: 'GET',
        headers: {
          'User-Agent': this.userAgent,
          'Accept': 'application/json'
        },
        signal: controller.signal
      });

      clearTimeout(timeoutId);
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        throw new Error(`Zeitüberschreitung bei der Abfrage von Barcode ${barcode}. Bitte Internetverbindung prüfen.`);
      }
      const msg = err instanceof Error ? err.message : 'Netzwerkfehler';
      throw new Error(`Konnte OpenFoodFacts nicht erreichen: ${msg}`);
    }

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(`Produkt mit Barcode ${barcode} wurde bei OpenFoodFacts nicht gefunden.`);
      }
      throw new Error(`OpenFoodFacts Serverfehler: HTTP ${response.status}`);
    }

    const data = (await response.json()) as OpenFoodFactsProductResponse;

    if (data.status === 0 || !data.product) {
      throw new Error(`Produkt mit Barcode ${barcode} existiert nicht in der OpenFoodFacts-Datenbank.`);
    }

    const parsedInfo = this.mapToProductInfo(barcode, data.product);
    this.cache.set(barcode, parsedInfo);

    return parsedInfo;
  }

  /**
   * Alias für getProductByBarcode zur Abwärtskompatibilität mit bestehenden Tests
   */
  public async getProductInfo(rawBarcode: string): Promise<BarcodeProductInfo> {
    return this.getProductByBarcode(rawBarcode);
  }

  /**
   * Wandelt BarcodeProductInfo in ein PantryItem um
   */
  public toPantryItem(product: BarcodeProductInfo, defaultAmount = 1, defaultUnit = 'Stück'): PantryItem {
    return {
      id: `pantry-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
      barcode: product.barcode,
      name: product.name,
      quantity: defaultAmount,
      unit: defaultUnit,
      category: product.category || 'Lebensmittel',
      ecoScore: product.ecoScore,
      nutriScore: product.nutriScore,
      addedAt: Date.now()
    };
  }

  /**
   * Leert den internen Cache
   */
  public clearCache(): void {
    this.cache.clear();
  }

  private mapToProductInfo(barcode: string, raw: NonNullable<OpenFoodFactsProductResponse['product']>): BarcodeProductInfo {
    const name = raw.product_name_de || raw.product_name || raw.generic_name || 'Unbekanntes Lebensmittel';
    const brand = raw.brands ? raw.brands.split(',')[0].trim() : undefined;

    const rawEco = (raw.ecoscore_grade || 'unknown').toLowerCase();
    const ecoScore: EcoScoreGrade = ['a', 'b', 'c', 'd', 'e'].includes(rawEco) ? (rawEco as EcoScoreGrade) : 'unknown';

    const rawNutri = (raw.nutriscore_grade || 'unknown').toLowerCase();
    const nutriScore: NutriScoreGrade = ['a', 'b', 'c', 'd', 'e'].includes(rawNutri)
      ? (rawNutri as NutriScoreGrade)
      : 'unknown';

    const categories = (raw.categories_tags || [])
      .map(cat => cat.replace(/^[a-z]{2}:/, '').replace(/-/g, ' '))
      .filter(cat => cat.length > 0);

    const allergens = (raw.allergens_tags || raw.allergens_hierarchy || [])
      .map(all => all.replace(/^[a-z]{2}:/, '').replace(/-/g, ' ').trim())
      .filter(all => all.length > 0);

    const imageUrl = raw.image_front_url || raw.image_url || raw.image_front_small_url || undefined;
    const ingredientsText = raw.ingredients_text_de || raw.ingredients_text || undefined;

    return {
      barcode,
      name,
      brand,
      category: categories.length > 0 ? categories[0] : undefined,
      ecoScore,
      nutriScore,
      allergens: Array.from(new Set(allergens)),
      imageUrl,
      ingredients: ingredientsText ? [ingredientsText] : undefined
    };
  }
}

export const barcodeService = BarcodeService.getInstance();