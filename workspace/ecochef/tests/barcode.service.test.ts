import { BarcodeService } from '../ui-src/services/barcode.service';

describe('BarcodeService', () => {
  let service: BarcodeService;

  beforeEach(() => {
    service = BarcodeService.getInstance();
    service.clearCache();
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  it('should fetch product info successfully', async () => {
    const mockResponse = {
      status: 1,
      product: {
        product_name: 'Test Product',
        ecoscore_grade: 'a',
        nutriscore_grade: 'b'
      }
    };

    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => mockResponse
    });

    const product = await service.getProductInfo('123456789');
    expect(product.name).toBe('Test Product');
    expect(product.ecoScore).toBe('a');
    expect(product.nutriScore).toBe('b');
  });

  it('should handle 404 Not Found', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      status: 404
    });

    await expect(service.getProductInfo('000000000'))
      .rejects.toThrow(/wurde bei OpenFoodFacts nicht gefunden/);
  });
});
