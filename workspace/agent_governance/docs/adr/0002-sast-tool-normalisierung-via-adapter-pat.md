# SAST-Tool Normalisierung via Adapter-Pattern

Status: Angenommen

## Kontext

Verschiedene SAST-Tools (Bandit, SonarQube) liefern unterschiedliche Output-Formate. Eine Normalisierungsschicht ist notwendig.

## Entscheidung

Einführung einer Adapter-Klasse mit Normalisierungs-Logik pro Tool.

## Konsequenzen

Einheitliches JSON-Format für alle SAST-Tools. Erleichtert die Aggregation im Backend und die Visualisierung im Frontend. Neue Tools erfordern lediglich einen neuen Adapter-Parser.
