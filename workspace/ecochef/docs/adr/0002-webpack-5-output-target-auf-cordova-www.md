# Webpack 5 Output-Target auf Cordova www-Ordner

Status: Angenommen

## Kontext

Apache Cordova erwartet die Web-Assets zwingend im `www/`-Verzeichnis. Ein separater Build- und Kopier-Schritt ist fehleranfällig und verlangsamt die DX (Developer Experience).

## Entscheidung

Webpack 5 wird so konfiguriert, dass der `output.path` im Produktions-Build direkt auf das `www/`-Verzeichnis des Cordova-Projekts zeigt.

## Konsequenzen

Der Build-Prozess ist nahtlos in Cordova integriert. Entwickler müssen sicherstellen, dass `www/` in `.gitignore` liegt, da es ein generiertes Verzeichnis ist. Der Webpack Dev-Server (Port 4444) bedient weiterhin aus dem RAM für schnelle Web-Entwicklung.
