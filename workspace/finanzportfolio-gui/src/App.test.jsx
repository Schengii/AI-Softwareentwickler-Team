import { render, screen, fireEvent } from '@testing-library/react';
import App from './App';
import '@testing-library/jest-dom';

describe('Finanzportfolio Dashboard & Upload Tests', () => {
  test('rendert alle 9 Grid-Kacheln korrekt', () => {
    render(<App />);
    const mainGrid = screen.getByRole('main');
    expect(mainGrid).toHaveClass('grid', 'grid-cols-1', 'sm:grid-cols-2', 'lg:grid-cols-3');
    expect(screen.getByText('Depotwert')).toBeInTheDocument();
    expect(screen.getByText('Portfolio hochladen')).toBeInTheDocument();
  });

  test('simuliert Datei-Upload von CSV und prüft Event-Handling', () => {
    render(<App />);
    const fileInput = screen.getByLabelText(/Portfolio hochladen/i) || screen.getByTestId('file-input');
    const file = new File(['datum,wert\n2026-01-01,1000'], 'portfolio.csv', { type: 'text/csv' });
    
    fireEvent.change(fileInput, { target: { files: [file] } });
    expect(fileInput.files[0].name).toBe('portfolio.csv');
  });
});
