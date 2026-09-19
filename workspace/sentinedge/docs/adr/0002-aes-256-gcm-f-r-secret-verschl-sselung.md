# AES-256-GCM für Secret-Verschlüsselung

Status: Angenommen

## Kontext

Secrets müssen sicher gespeichert werden. Es wird eine starke, authentifizierte Verschlüsselung benötigt, um sowohl Vertraulichkeit als auch Integrität der Secrets zu gewährleisten.

## Entscheidung

Verwendung von AES-256-GCM (via 'cryptography' Fernet/AESGCM) für die Verschlüsselung der Secret-Werte in der Datenbank.

## Konsequenzen

Erfordert die sichere Verwaltung eines Master-Keys (z.B. via Umgebungsvariable). Hohe Sicherheit durch Authenticated Encryption. Die 'cryptography'-Bibliothek muss als Abhängigkeit hinzugefügt werden.
