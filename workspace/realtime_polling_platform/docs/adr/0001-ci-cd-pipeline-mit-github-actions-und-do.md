# CI/CD Pipeline mit GitHub Actions und Docker-Caching

Status: Angenommen

## Kontext

Notwendigkeit einer robusten CI-Pipeline für FastAPI-Anwendungen mit Fokus auf Qualität und Sicherheit.

## Entscheidung

Einsatz von GitHub Actions mit integriertem Bandit (Security), Flake8/Black (Linting) und Docker Buildx mit Layer-Caching.

## Konsequenzen

Die Pipeline ist modular aufgebaut. Die Trennung von Linting/Testen und Docker-Build spart Ressourcen bei Fehlern in der Code-Qualität. Docker-Caching reduziert Build-Zeiten signifikant.
