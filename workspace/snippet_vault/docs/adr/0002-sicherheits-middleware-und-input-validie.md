# Sicherheits-Middleware und Input-Validierung für FastAPI API

Status: Angenommen

## Kontext

Das Backend fehlte jegliche Sicherheits-Middleware und Input-Validierung, was es anfällig für CSRF, unkontrollierte Cross-Origin-Anfragen und fehlerhafte Daten-Eingaben machte.

## Entscheidung

Implementierung von `CORSMiddleware` und Nutzung von Pydantic `Field`-Constraints zur Validierung der API-Eingaben.

## Konsequenzen

Erhöht die Sicherheit durch CORS-Kontrolle und Pydantic-Validierung. Die `allow_origins=["*"]` ist für das MVP akzeptabel, sollte aber für Produktion auf die spezifische Frontend-URL eingeschränkt werden. Die Pydantic-Validierung verhindert einfache Buffer-Overflow-ähnliche Angriffe durch zu große Eingaben.
