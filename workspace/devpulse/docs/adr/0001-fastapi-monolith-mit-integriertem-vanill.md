# FastAPI Monolith mit integriertem Vanilla-JS Frontend

Status: Angenommen

## Kontext

DevPulse benötigt ein modernes Web-Dashboard, soll aber ohne schwere Build-Tools auskommen.

## Entscheidung

Wir nutzen FastAPI als Backend und mounten das Frontend (HTML, Vanilla JS, Vanilla CSS) direkt über StaticFiles.

## Konsequenzen

Einfaches Deployment, keine komplexen CORS-Probleme, Frontend wird direkt vom Backend ausgeliefert. Keine Hot-Reloading-Features von modernen JS-Frameworks, aber ausreichend für MVP.
