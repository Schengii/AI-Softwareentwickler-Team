# Entkopplung der Pong-Spiellogik vom Canvas-Rendering für deterministisches Testing

Status: Angenommen

## Kontext

Das Pong-Spiel muss auf Bewegungslogik, Kollisionen und Punktestände automatisiert getestet werden. Direkte Canvas- und DOM-Kopplung erschwert isolierte Tests.

## Entscheidung

Trennung von reiner Spiellogik (gameLogic.ts) und UI/Rendering (main.ts). Game-Loop ruft pure Funktionen für Zustandsaktualisierungen auf.

## Konsequenzen

Hohe Testabdeckung ohne DOM/Canvas-Mocking; Logik ist rein funktional/zustandsorientiert und präzise in Unit- und Integrationstests überprüfbar. UI-Schicht (main.ts) übernimmt rein das Rendering und Input-Forwarding.
