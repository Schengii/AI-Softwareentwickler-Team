# Layered Architecture mit FastAPI und async Endpunkten

Status: Angenommen

## Kontext

Das Knowledge Hub muss Markdown-Dateien verwalten, parsen, indizieren und über eine API bereitstellen. Es galt zu entscheiden, wie der Code strukturiert wird (Layered Architecture vs. flacher Monolith).

## Entscheidung

Schichtenarchitektur (API / Service / Domain / Infrastructure) mit FastAPI als ASGI-Backend unter workspace/app bzw. workspace/core. Alle Schichten greifen über wohldefinierte Schnittstellen (exports.py) zu.

## Konsequenzen

Vorteile: Klare Separation of Concerns, einfache Testbarkeit der einzelnen Schichten (Storage, Watcher, Parsing, RAG, Graph), Austauschbarkeit einzelner Provider. Nachteil: Etwas mehr Boilerplate als ein monolithisches Skript.
