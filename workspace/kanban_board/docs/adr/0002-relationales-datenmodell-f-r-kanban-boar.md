# Relationales Datenmodell für Kanban-Board

Status: Angenommen

## Kontext

Das Projekt benötigt ein persistentes Datenmodell für ein Kanban-Board. Die Wahl fiel auf ein relationales Modell, um die hierarchische Struktur (Board -> Spalten -> Karten) sauber abzubilden. PostgreSQL ist der Standard für produktive Umgebungen.

## Entscheidung

Einsatz eines relationalen Schemas (PostgreSQL) mit expliziten Fremdschlüsselbeziehungen und Indizes.

## Konsequenzen

Die Verwendung von PostgreSQL bietet ACID-Konformität und robuste Fremdschlüssel-Constraints. Das Schema ist normalisiert (3NF), was Datenredundanz minimiert. Die Indizes auf Fremdschlüssel beschleunigen Joins und Lookups bei Board-Abfragen. SQLite wird als Fallback für lokale Entwicklung unterstützt.
