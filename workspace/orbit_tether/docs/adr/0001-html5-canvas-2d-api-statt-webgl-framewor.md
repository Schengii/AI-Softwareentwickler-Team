# HTML5 Canvas 2D API statt WebGL-Frameworks

Status: Angenommen

## Kontext

Das Spiel benötigt eine performante Rendering-Engine für einfache geometrische Formen (Kreise, Linien) auf mobilen Geräten. Optionen waren Phaser.js, Pixi.js (WebGL) oder die native HTML5 Canvas 2D API.

## Entscheidung

Wir nutzen die native HTML5 Canvas 2D API ohne zusätzliches Framework.

## Konsequenzen

Sehr hohe Performance, minimale Bundle-Size, keine externen Abhängigkeiten für das Rendering. Erfordert jedoch die manuelle Implementierung von Kollisionserkennung und Vektor-Mathematik.
