# ADR 001 – UI Framework und Animationsbibliothek

**Titel:** React 17+ + Tailwind CSS + Framer Motion für UI‑Framework und Animationen

**Kontext:**
Das Projekt benötigt ein modernes UI‑Framework für die GUI‑Erweiterung mit animierten Komponenten. Optionen waren:
- React 17+ mit Tailwind CSS vs. Vue 3 mit Vuetify vs. Angular mit Angular Material
- Framer Motion vs. React Spring vs. reine CSS‑Animationen

**Entscheidung:**
Wir wählen **React 17+** kombiniert mit **Tailwind CSS** für Styling und **Framer Motion** für Animationen.

**Begründung:**
- React ist bereits im Projekt als Basis vorhanden und bietet komponentenbasierte Architektur.
- Tailwind ermöglicht schnelles, konsistentes Styling über Utility‑Klassen und lässt sich leicht thematisieren (Light/Dark).
- Framer Motion liefert deklarative, performant‑optimierte Animationen und integriert sich nahtlos in React.
- Alternativen (Vue, Angular) würden einen kompletten Stack‑Wechsel erfordern; React Spring ist weniger ausgereift für komplexe Sequenzen.

**Konsequenzen:**
- Build‑Pipeline muss Node.js, Vite/webpack, Tailwind‑PostCSS‑Plugin und Framer‑Motion‑Package integrieren.
- Entwickler müssen Tailwind‑Konfiguration pflegen und Accessibility‑Checks (WCAG 2.1 AA) für Farbkontraste implementieren.
- Zusätzliche Abhängigkeiten erhöhen Bundle‑Size leicht, jedoch durch Tree‑Shaking minimal.
