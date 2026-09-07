# Integration von CORSMiddleware zur API-Sicherung

Status: Angenommen

## Kontext

Die API war anfällig für unautorisierte Cross-Origin-Anfragen, da CORSMiddleware fehlte.

## Entscheidung

Integration von `CORSMiddleware` in `app/core/security.py` mit Konfiguration über `app/core/config.py`.

## Konsequenzen

Ermöglicht CORS-geschützte API-Aufrufe vom Frontend. Erhöht die Sicherheit gegen CSRF/XSS-Angriffe. Erfordert Konfiguration der erlaubten Origins in den Settings.
