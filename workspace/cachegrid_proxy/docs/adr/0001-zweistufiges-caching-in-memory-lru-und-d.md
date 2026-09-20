# Zweistufiges Caching (In-Memory LRU und Disk Tiering)

Status: Angenommen

## Kontext

Caching-Anforderungen verlangen schnelle In-Memory LRU-Antwortzeiten, aber auch Kapazitätserweiterung und Persistenz via Disk. Alternativen waren Pure In-Memory oder reine SQLite/KV-DB.

## Entscheidung

Entscheidung für hierarchisches Two-Tier Caching: Hot Data verbleibt im Memory-LRU (OrderedDict/DoublyLinkedList + TTL), bei Eviction oder konfigurierbarem Spillover erfolgt Persistenz auf Disk (File- oder SQLite-basiert).

## Konsequenzen

Vorteile: Sehr niedrige Latenz im Hot-Path (RAM) bei gleichzeitiger Absicherung gegen OOM durch Spillover auf Disk und Neustart-Resilienz. Nachteil: Komplexere Konsistenz und Serialisierungs-Overhead bei Disk-Zugriffen.
