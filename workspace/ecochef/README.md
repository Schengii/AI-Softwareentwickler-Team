# EcoChef

EcoChef ist dein intelligenter KI-Rezept-Zauberer. Eine Web- und Hybrid-App (Apache Cordova), die dir hilft, nachhaltig zu kochen, Vorräte zu verwalten und Lebensmittelverschwendung zu reduzieren.

## 🚀 Features

- **KI-Rezept-Generierung:** Powered by Google Gemini.
- **Vorratskammer-Management:** Behalte den Überblick über deine Zutaten.
- **Barrierefreiheit:** Spezieller LRS-Modus (Legasthenie-Unterstützung) mit OpenDyslexic-Font und interaktivem Leselineal.
- **Hybrid-Ready:** Optimiert für Web und mobile Endgeräte via Apache Cordova.
- **Datenschutz:** Alle Daten werden lokal auf deinem Gerät gespeichert (`localStorage`).

## 🛠 Tech Stack

- **Framework:** [Lit 3](https://lit.dev/)
- **Sprache:** TypeScript (Strict Mode)
- **Build-System:** Webpack 5
- **Hybrid:** Apache Cordova
- **KI-Integration:** Google Gemini API (`@google/genai`)

## 📦 Installation & Setup

### Voraussetzungen
- Node.js (v18+)
- npm (v9+)
- Apache Cordova CLI (`npm install -g cordova`)

### Entwicklung
1. **Repository klonen & Abhängigkeiten installieren:**
   ```bash
   npm install
   ```
2. **Umgebungsvariablen konfigurieren:**
   Erstelle eine `.env` Datei im Root-Verzeichnis:
   ```env
   GEMINI_API_KEY=dein_api_key_hier
   ```
3. **Entwicklungsserver starten:**
   ```bash
   npm start
   ```
   Die App ist unter `http://localhost:4444` erreichbar.

### Build für Produktion / Cordova
Der Build-Prozess kompiliert die App direkt in das `www/` Verzeichnis, welches von Cordova verwendet wird.
```bash
npm run build
```

## 🏗 Architektur
- **UI:** Lit Web Components (`ui-src/components/`)
- **Services:** Zustandlose Singletons (`ui-src/services/`)
- **State:** Zentraler Controller (`eco-chef.ts`)
- **ADRs:** Dokumentation der Architekturentscheidungen unter `docs/adr/`.

## 📝 Changelog

### [0.1.0] - 2024-05-22
- Initiales Projekt-Setup.
- Webpack 5 Konfiguration mit Cordova-Integration.
- Grundlegende Services (Gemini, Barcode) und Datenmodelle angelegt.
- Accessibility-Grundgerüst (LRS-Modus Vorbereitung).
