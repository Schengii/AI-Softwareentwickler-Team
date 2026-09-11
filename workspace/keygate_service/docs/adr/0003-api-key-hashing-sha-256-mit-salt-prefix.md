# API-Key-Hashing: SHA-256 mit Salt + Prefix-Lookup statt Klartext-Vergleich oder bcrypt

Status: Angenommen

## Kontext

API-Keys dürfen nicht im Klartext gespeichert werden (OWASP). Für die Verifikation bei jedem /verify-Request muss der Lookup performant sein (Hunderte Requests/Sekunde). bcrypt/argon2 sind für Passwort-Hashing mit absichtlich hoher Rechenkosten konzipiert, was bei High-Frequency-API-Key-Checks zu Latenzproblemen führen würde. Klartext-Speicherung ist inakzeptabel. Reines "SHA-256 über alle Keys iterieren" skaliert nicht (O(n) Lookup).

## Entscheidung

API-Key-Format: `kg_{prefix}_{secret}` wobei prefix ein 8-Zeichen-öffentlicher Identifier (indiziert, für O(1)-DB-Lookup) und secret ein 32-Byte-URL-safe-Zufallswert (secrets.token_urlsafe) ist. Gespeichert wird: key_prefix (indiziert, Klartext, dient nur dem schnellen Lookup), salt (16 Byte, pro Key zufällig), key_hash = SHA-256(salt + secret) als Hex. Verifikation: 1) Prefix aus Header extrahieren, 2) DB-Row per Prefix-Index laden (O(1)), 3) SHA-256(salt+secret) berechnen und mit hmac.compare_digest gegen key_hash prüfen (Timing-Attack-Schutz). Der volle Key wird NUR einmal bei Erstellung in der POST /keys-Response zurückgegeben, danach nie wieder.

## Konsequenzen

Vorteil: O(1)-Lookup via indizierten Prefix statt Vollscan, SHA-256 ist schnell genug für High-Frequency-Verification (kein bcrypt-Overhead pro Request), hmac.compare_digest verhindert Timing-Angriffe, Salt verhindert Rainbow-Table-Angriffe. Nachteil: SHA-256 ist schneller brute-forcebar als bcrypt falls DB kompromittiert wird - das wird durch hohe Entropie des Secrets (32 Byte = 256 Bit Zufall) kompensiert, ein Offline-Bruteforce ist praktisch unmöglich. Konsequenz für Entwickler: key_hash und salt dürfen NIE über API-Schemas (schemas.py) exponiert werden.
