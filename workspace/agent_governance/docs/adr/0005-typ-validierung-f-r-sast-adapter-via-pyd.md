# Typ-Validierung für SAST-Adapter via Pydantic-Modelle

Status: Angenommen

## Kontext

Der SASTAdapter gab bisher ein unstrukturiertes Dictionary zurück, was zu Serialisierungsfehlern und fehlender Typ-Validierung führte. Ein einheitliches Schema (SASTReport) ist für die API-Konsistenz zwingend erforderlich.

## Entscheidung

Erzwingung der Nutzung von Pydantic-Modellen (SASTReport) als Rückgabetyp für alle SAST-Adapter-Methoden.

## Konsequenzen

Erhöhte Typ-Sicherheit und Validierung durch Pydantic-Modelle. Verhindert Laufzeitfehler bei der API-Serialisierung. Erfordert Import von Pydantic-Modellen in allen Adapter-Implementierungen.
