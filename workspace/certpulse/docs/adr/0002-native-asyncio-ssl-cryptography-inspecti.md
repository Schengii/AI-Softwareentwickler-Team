# Native asyncio SSL Cryptography Inspection für Zertifikate

Status: Angenommen

## Kontext

Für den TLS/SSL-Zertifikatscheck muss das Ablaufdatum, die TLS-Version, CA/Issuer und SAN-Einträge aus Remote-Sockets ausgelesen werden. Option 1: CLI-Tool-Wrapper (OpenSSL/curl), Option 2: Native asyncio + ssl / cryptography Python-Module.

## Entscheidung

Nutzung der nativen Python-Bibliotheken `ssl`, `socket` und `cryptography` in Kombination mit `asyncio.to_thread` / `asyncio.open_connection` für asynchrone TLS-Handshakes und Zertifikatsanalyse.

## Konsequenzen

Keine externen CLI-Abhängigkeiten (wie OpenSSL binary) erforderlich; direkte asynchrone Socket-Verbindung via Python asyncio und SSLContext/Cryptography SDK. Präzise Extraktion von SANs, Ablaufdaten, Issuer und TLS-Versionen.
