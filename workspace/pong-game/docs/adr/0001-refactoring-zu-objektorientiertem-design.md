# Refactoring zu objektorientiertem Design mit Dependency Injection

Status: Angenommen

## Kontext

Das Spiel war als loses Skript mit globalen DOM-Abhängigkeiten implementiert, was Tests verhinderte und Wartung erschwerte.

## Entscheidung

Refactoring in eine ES6-Klasse 'PongGame' mit Dependency Injection für DOM-Elemente und Canvas. Trennung von Spiellogik (update/draw) und UI-Manipulation.

## Konsequenzen

Verbesserte Testbarkeit durch Dependency Injection, klare Trennung von UI und Logik, Vermeidung von Memory Leaks durch zentrales Intervall-Management. Erfordert beim Instanziieren die Übergabe aller DOM-Elemente.
