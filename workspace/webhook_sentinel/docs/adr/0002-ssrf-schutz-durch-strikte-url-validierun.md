# SSRF-Schutz durch strikte URL-Validierung

Status: Angenommen

## Kontext

Das System nimmt URLs von Benutzern entgegen, an die Webhooks gesendet werden. Dies birgt das Risiko von Server-Side Request Forgery (SSRF), bei dem der Service missbraucht wird, um interne Netzwerke (z.B. 127.0.0.1, 10.0.0.0/8) zu scannen oder anzugreifen.

## Entscheidung

Strikte URL-Validierung bei der Subscription-Registrierung und vor dem Versand, die private und Loopback-IP-Adressbereiche blockiert.

## Konsequenzen

Interne Test-Systeme auf localhost oder in privaten Subnetzen können nicht ohne Weiteres als Webhook-Ziele registriert werden. Dies erhöht die Sicherheit signifikant, erfordert aber für lokale Tests ggf. Mock-Server mit öffentlichen IPs oder eine explizite Override-Konfiguration für die Testumgebung.
