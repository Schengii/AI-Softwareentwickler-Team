import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import ReportsOverview from '../../src/components/ReportsOverview';
import { apiClient } from '../../src/api/client';

// Mock des API-Clients
jest.mock('../../src/api/client', () => ({
  apiClient: {
    get: jest.fn(),
  },
}));

describe('ReportsOverview Komponente', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('zeigt Ladezustand an', () => {
    (apiClient.get as jest.Mock).mockReturnValue(new Promise(() => {})); // Hängt im Loading
    render(<ReportsOverview />);
    expect(screen.getByText(/Lade Berichtsdaten.../i)).toBeInTheDocument();
  });

  test('zeigt Daten nach erfolgreichem API-Call korrekt an', async () => {
    const mockData = { total_revenue: 1250.5, total_duration_hours: 45.2 };
    (apiClient.get as jest.Mock).mockResolvedValue({ data: mockData });

    render(<ReportsOverview />);

    await waitFor(() => {
      expect(screen.getByText('1250.50 €')).toBeInTheDocument();
      expect(screen.getByText('45.2 Std.')).toBeInTheDocument();
    });
  });

  test('zeigt Fehlermeldung bei API-Fehlschlag an', async () => {
    const errorMessage = 'API Fehler';
    (apiClient.get as jest.Mock).mockRejectedValue({
      response: { data: { detail: errorMessage } },
    });

    render(<ReportsOverview />);

    await waitFor(() => {
      expect(screen.getByText(`Fehler: ${errorMessage}`)).toBeInTheDocument();
    });
  });
});
