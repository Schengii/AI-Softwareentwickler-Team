# SHA256 Consistent Hashing für Percentage Rollouts

Status: Angenommen

## Kontext

Anforderung nach deterministischem Percentage-Rollout für Canary-Deployments und A/B-Tests basierend auf Flag-Key und User-/Entity-ID.

## Entscheidung

Nutzung von SHA256-basiertem Consistent Hashing über (flag_key + ':' + entity_id), skaliert auf den Wertebereich 0..99.99 (bzw. 0..100%).

## Konsequenzen

Deterministische Rollouts ohne Server-State bei Auswertungen. Hohe Performance, kein Session-Stickiness-Speicher nötig. Alle Nodes evaluieren identisch.
