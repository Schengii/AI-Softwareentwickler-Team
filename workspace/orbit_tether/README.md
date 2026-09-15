# Orbit Tether

"Orbit Tether" (auch bekannt als "Chroma Orbit") ist ein minimalistisches, hochperformantes Mobile-Geschicklichkeitsspiel, entwickelt mit HTML5 Canvas und TypeScript.

## 🎮 Spielkonzept
Ein Lichtpartikel navigiert durch dynamische Hindernisparcours.
- **Steuerung:** One-Touch.
  - **Berühren:** Dockt an den nächsten Gravitations-Ankerpunkt an und rotiert.
  - **Loslassen:** Katapultiert den Partikel tangential weiter.
- **Ziel:** Timing und Schwung nutzen, um Hindernisse und Farb-Tore zu überwinden.

## 🛠️ Technische Architektur
- **Engine:** Native HTML5 Canvas 2D API (siehe [ADR 0001](docs/adr/0001-html5-canvas-2d-api-statt-webgl-framewor.md)).
- **Stack:** TypeScript, Vite.
- **Cross-Platform:** Capacitor (iOS/Android).

## 🚀 Setup & Entwicklung

### Voraussetzungen
- Node.js (v18+)
- npm oder pnpm

### Installation
```bash
npm install
```

### Entwicklung starten
```bash
npm run dev
```

## 📱 Mobile Build (Capacitor)

### Vorbereitung
Stelle sicher, dass die Plattformen hinzugefügt wurden:
```bash
npx cap add ios
npx cap add android
```

### Build & Deployment
1. Projekt bauen:
   ```bash
   npm run build
   ```
2. Capacitor-Assets synchronisieren:
   ```bash
   npx cap sync
   ```
3. In IDE öffnen:
   ```bash
   npx cap open ios
   npx cap open android
   ```

## ♿ Barrierefreiheit
Das Spiel ist für Screenreader optimiert:
- Canvas ist als `role="application"` markiert.
- HUD-Elemente nutzen `aria-live` für Echtzeit-Feedback.

## 📝 Changelog

### [0.1.0] - 2023-10-27
- Initiales Projekt-Setup.
- Dokumentation erstellt.
- Capacitor-Integration konfiguriert.
