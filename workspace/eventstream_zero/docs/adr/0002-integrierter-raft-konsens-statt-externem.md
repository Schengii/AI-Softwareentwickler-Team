# Integrierter Raft-Konsens statt externem Zookeeper

Status: Angenommen

## Kontext

Verteilte Systeme benötigen Konsens für Leader-Election und Metadaten-Replikation. Historisch wurde oft Apache Zookeeper genutzt (wie bei älteren Kafka-Versionen), was jedoch die Systemarchitektur verkompliziert (zusätzlicher Service).

## Entscheidung

Eigenständige Implementierung des Raft-Konsens-Algorithmus direkt im Python-Kern von EventStream-Zero (ähnlich Kafka KRaft).

## Konsequenzen

Vereinfachtes Deployment und Betrieb (keine Zookeeper-Abhängigkeit). Erhöht jedoch die Komplexität der Kernentwicklung erheblich, da Leader-Election, Log-Replication und Split-Brain-Handling selbst in Python implementiert werden müssen.
