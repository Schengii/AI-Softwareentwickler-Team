# State-Management mit @lit/context für Lit 3

Status: Angenommen

## Kontext

Die App benötigt globale Zustände (LRS-Modus, Theme, Vorratskammer, API-Keys), die in vielen tief verschachtelten Komponenten benötigt werden. Prop-Drilling (Data down, Events up) über viele Ebenen wird unübersichtlich.

## Entscheidung

Nutzung von `@lit/context` für das globale State-Management anstelle von reinem Event-Bubbling oder externen Stores wie Redux.

## Konsequenzen

Einfacher, reaktiver Zugriff auf globale Daten (Theme, API-Keys, Zutaten) ohne Prop-Drilling. Erfordert strikte Typisierung der Context-Keys in TypeScript. Lokale UI-Zustände (z.B. Lade-Spinner) verbleiben im lokalen State der Komponenten.
