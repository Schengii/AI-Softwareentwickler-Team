import { render, screen } from '@testing-library/react';
import { DashboardDemo } from '../pages/DashboardDemo';

test('rendert alle 9 Kacheln', () => {
  render(<DashboardDemo />);
  const kacheln = [
    "Depotwert", "Performance", "Asset-Verteilung",
    "Top Performer", "Transaktionen", "Dividenden",
    "Risiko-Analyse", "Markt-News", "Einstellungen"
  ];
  
  kacheln.forEach(titel => {
    expect(screen.getByText(titel)).toBeInTheDocument();
  });
});
