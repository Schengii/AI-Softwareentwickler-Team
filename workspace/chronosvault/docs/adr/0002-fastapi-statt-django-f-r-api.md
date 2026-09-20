# FastAPI statt Django für API

Status: Angenommen

## Kontext

Es wird ein Web-Framework für die Bereitstellung der REST-API benötigt. Zur Auswahl standen Django (Batteries-included, aber schwergewichtiger) und FastAPI (modern, asynchron, Pydantic-Integration).

## Entscheidung

Entscheidung für FastAPI in Kombination mit Pydantic v2, da die strikte Validierung von Workflow-Schemas und Payloads essenziell ist und FastAPI hierfür die beste native Unterstützung bietet.

## Konsequenzen

Hohe Performance, automatische OpenAPI-Dokumentation, strikte Typisierung. Erfordert asynchrone Programmierung (async/await) und sorgfältiges Handling von blockierenden I/O-Operationen (wie Datei-Hashes oder synchronen DB-Calls).
