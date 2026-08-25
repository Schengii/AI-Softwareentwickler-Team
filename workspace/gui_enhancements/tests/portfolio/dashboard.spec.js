describe('Dashboard E2E Tests', () => {
  beforeEach(() => {
    cy.visit('/');
  });

  it('should display the main content area', () => {
    cy.get('main').should('exist');
  });

  it('should validate graph data binding (mocked)', () => {
    // Annahme: Es gibt ein Element mit der ID 'data-graph'
    // Dies dient als Platzhalter für die E2E-Validierung
    cy.get('[data-testid="graph-container"]').should('be.visible');
  });

  it('should trigger modal on card click', () => {
    cy.get('.cursor-pointer').first().click();
    cy.get('.fixed').should('be.visible');
  });
});
