# Performance-Optimierung für Abrechnungsabfragen durch Indizierung

Status: Angenommen

## Kontext

Die Abrechnungslogik muss häufig TimeEntries filtern, die noch nicht abgerechnet wurden (is_billed=False). Ohne Index würde dies bei wachsender Datenmenge zu Full Table Scans führen.

## Entscheidung

Hinzufügen von Indizes auf is_billed und invoice_id in der TimeEntry-Tabelle.

## Konsequenzen

Die Indizierung von is_billed und invoice_id verbessert die Performance bei der Abrechnungsberechnung und Rechnungsabfrage erheblich, erhöht jedoch minimal den Speicherplatzbedarf für Indizes.
