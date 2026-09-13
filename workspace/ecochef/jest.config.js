  // Team-Goal (20260913, Aufgabe 3): `lit` (>= v3) liefert nur noch ESM-Pakete aus - ohne
  // eigenen Transform lief `import ... from 'lit'` in node_modules ungetranspiliert direkt in
  // Jests CommonJS-Runtime und schlug mit "Cannot use import statement outside a module" fehl.
  // Fix: ts-jest transpiliert (isolatedModules, ohne vollen Typecheck) zusätzlich die
  // Lit-Pakete selbst; `transformIgnorePatterns` nimmt genau diese vom Standard-node_modules-
  // Ausschluss aus.
  module.exports = {
    preset: 'ts-jest',
    testEnvironment: 'jsdom',
    roots: ['<rootDir>/ui-src', '<rootDir>/tests'],
    moduleFileExtensions: ['ts', 'js', 'json'],
    transform: {
      // Eigener Code: normaler ts-jest-Transform mit vollem Typecheck (wie zuvor).
      '^.+\\.ts$': 'ts-jest',
      // Nur die freigegebenen ESM-node_modules (s.u.): schneller, ungetypter Transform reicht.
      '^.+\\.js$': ['ts-jest', { isolatedModules: true }]
    },
    transformIgnorePatterns: [
      '/node_modules/(?!(lit|@lit|lit-html|lit-element)/)'
    ]
  };
