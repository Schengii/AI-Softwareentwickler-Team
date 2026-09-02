# FastAPI als API-Gateway Framework

Status: Angenommen

## Kontext

Wahl des Frameworks für das API-Gateway. Alternativen: Flask (nicht nativ async), Django (zu schwergewichtig), Go/Kong (höhere Performance, aber komplexere Integration in Python-Ökosystem).

## Entscheidung

Einsatz von FastAPI als Kern-Framework.

## Konsequenzen

FastAPI bietet hohe Performance und native asynchrone Unterstützung, was für ein I/O-lastiges Gateway ideal ist. Die Integration mit Pydantic sorgt für robuste Validierung. Als Nachteil gegenüber Go-basierten Gateways (wie Kong) ist die Performance bei extrem hohen Lasten geringer, was durch horizontale Skalierung kompensiert werden muss.
