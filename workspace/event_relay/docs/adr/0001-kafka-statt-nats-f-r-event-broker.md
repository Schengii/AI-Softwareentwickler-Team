# Kafka statt NATS für Event-Broker

Status: Angenommen

## Kontext

Das System muss hohe Durchsatz, Persistenz und Partitionierung für Event-Streaming unterstützen.

## Entscheidung

Apache Kafka wurde als primärer Event-Broker gewählt, weil es bewährte Persistenz, Skalierbarkeit und breites Ökosystem bietet.

## Konsequenzen

Erfordert Zookeeper (oder KRaft) Management, höhere Betriebskomplexität, aber ermöglicht langlebige Topics und Replay-Fähigkeit. NATS wäre einfacher, aber ohne Persistenz.
