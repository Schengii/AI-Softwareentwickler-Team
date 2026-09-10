# Locust als Load-Testing-Framework für VaultGuard-Endpunkte

Status: Angenommen

## Kontext

Für VaultGuard wird ein aus aussagekräftiger Lasttest für 5 Kern-Endpunkte (Health Check, Auth/Token, Secret Create, Secret Fetch, Leak Scan) bei 50-100 gleichzeitigen Nutzern benötigt.

## Entscheidung

Verwendung von Locust (tests/load/locustfile.py) mit HttpUser, gewichteten Tasks (@task), On-Start Authentifizierung/Token-Generierung und isolierten Endpunkt-Aufrufen ohne hartcodierte Host-URLs.

## Konsequenzen

Nahtlose Integration in Python-Test-Pipelines; einfaches Scripting von komplexen User-Flows (z.B. Auth -> Secret erfassen -> Scan ausführen); verifizierbar durch die automatische Testumgebung.
