# Lokale RAG-Engine mit BM25-Fallback und Vektor-Indexierung

Status: Angenommen

## Kontext

Die Notizen und Code-Snippets sollen semantisch und nach Schlüsselwörtern durchsucht werden (RAG). Externe Cloud-Embeddings (OpenAI) erfordern API-Keys und Internetverbindung; reine Volltextsuche erfasst keine Synonyme.

## Entscheidung

Hybride RAG-Architektur: BM25/TF-IDF Volltext- und Rangordnungssuche kombiniert mit lokaler Vektorähnlichkeit (Cosine Similarity über lokale Embeddings oder BM25-Fallback).

## Konsequenzen

Vorteile: Null externe API-Kosten, 100% offline-fähig, geringe Latenz, keine Abhängigkeit von OpenAI/Cloud Keys. Bei Verfügbarkeit lokaler Embeddings (z.B. sentence-transformers / lightweight embeddings) wird semantische Vektorsuche aktiviert, bei Nichtverfügbarkeit springt BM25 ein.
