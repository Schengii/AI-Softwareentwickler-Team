# Pong Game

Ein klassisches Pong-Spiel, implementiert mit Vanilla JavaScript und HTML5 Canvas.

## Projektstruktur
- `index.html`: Grundstruktur mit verschiedenen Spiel-Screens (Lade-, Start-, Spiel-, Gewinn-Screen).
- `style.css`: Responsive Gestaltung und UI-Layout.
- `game.js`: Spiellogik, Kollisionserkennung, KI-Verhalten und Timer-Steuerung.

## Funktionen
- **Spielphasen:** Ladebildschirm, Startanleitung, aktives Spiel, Gewinnbildschirm.
- **UI:** Anzeige von Spielstand und Zeit.
- **KI:** Einfacher KI-Gegner.

## Installation & Start
Da es sich um ein reines Frontend-Projekt handelt, sind keine Build-Schritte erforderlich.

1. Klone das Repository.
2. Öffne die Datei `index.html` direkt in deinem Webbrowser.

## Architektur-Entscheidungen
- **Vanilla JS/Canvas:** Gewählt für maximale Performance und minimale Abhängigkeiten.
- **Zustandsbasierte UI:** Umschalten von CSS-Klassen (`hidden`) zur Steuerung der Spielphasen.

## Tests
Das Projekt ist aktuell als Prototyp konzipiert. Für automatisierte Tests (z.B. mit Jest oder Cypress) müsste eine Testumgebung für das DOM/Canvas-Rendering konfiguriert werden.

## Changelog
### [1.0.0] - 2023-10-27
- Initiales Release des Pong-Spiels.
- Implementierung von Spiellogik, KI und UI-Zustandsmanagement.
