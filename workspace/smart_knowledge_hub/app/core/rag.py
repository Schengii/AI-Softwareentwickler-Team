import math
import re
from typing import Any

from app.core.vault import VaultManager


class BM25SearchEngine:
    """Lokale BM25 Search Engine mit Texttokenisierung und Relevanz-Scoring."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus: list[dict[str, Any]] = []
        self.doc_lengths: list[int] = []
        self.avg_doc_len: float = 0.0
        self.doc_freqs: dict[str, int] = {}
        self.idf: dict[str, float] = {}

    def _tokenize(self, text: str) -> list[str]:
        """Einfache Tokenisierung: Kleinbuchstaben und alphanumerische Wörter."""
        return re.findall(r"\w+", (text or "").lower())

    def index(self, documents: list[dict[str, Any]]) -> None:
        """Indiziert eine Liste von Dokumenten (müssen 'path' und 'content' bzw. 'snippet' haben)."""
        self.corpus = documents
        self.doc_lengths = []
        self.doc_freqs = {}
        self.idf = {}

        n_docs = len(documents)
        if n_docs == 0:
            self.avg_doc_len = 0.0
            return

        total_len = 0
        for doc in documents:
            text = f"{doc.get('title', '')} {doc.get('content', '')} {' '.join(doc.get('tags', []))}"
            tokens = self._tokenize(text)
            self.doc_lengths.append(len(tokens))
            total_len += len(tokens)

            unique_terms = set(tokens)
            for term in unique_terms:
                self.doc_freqs[term] = self.doc_freqs.get(term, 0) + 1

        self.avg_doc_len = total_len / n_docs if n_docs > 0 else 0.0

        for term, df in self.doc_freqs.items():
            self.idf[term] = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Berechnet BM25 Scores für den Such-Query und liefert die Top-K Treffer."""
        if not self.corpus:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores: list[float] = [0.0] * len(self.corpus)

        for i, doc in enumerate(self.corpus):
            doc_len = self.doc_lengths[i]
            if doc_len == 0:
                continue

            text = f"{doc.get('title', '')} {doc.get('content', '')} {' '.join(doc.get('tags', []))}"
            tokens = self._tokenize(text)
            term_counts: dict[str, int] = {}
            for t in tokens:
                term_counts[t] = term_counts.get(t, 0) + 1

            doc_score = 0.0
            for term in query_tokens:
                if term not in term_counts:
                    continue
                tf = term_counts[term]
                idf_val = self.idf.get(term, 0.0)
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / (self.avg_doc_len or 1.0)))
                doc_score += idf_val * (numerator / denominator)

            scores[i] = doc_score

        ranked_indices = sorted(
            [idx for idx, s in enumerate(scores) if s > 0],
            key=lambda idx: scores[idx],
            reverse=True,
        )

        results: list[dict[str, Any]] = []
        for idx in ranked_indices[:top_k]:
            doc = self.corpus[idx]
            results.append({
                "path": doc.get("path"),
                "title": doc.get("title", doc.get("path")),
                "score": round(scores[idx], 4),
                "snippet": doc.get("content", "")[:200] if doc.get("content") else doc.get("title", ""),
                "frontmatter": doc.get("frontmatter", {}),
            })

        return results


class RAGEngine:
    """RAG-Engine mit BM25-Retrieval und Kontext-Synthese."""

    def __init__(self, vault_manager: VaultManager):
        self.vault_manager = vault_manager
        self.search_engine = BM25SearchEngine()

    async def refresh_index(self) -> None:
        """Holt alle Notizen asynchron aus dem Vault und baut den BM25-Index auf."""
        notes = await self.vault_manager.list_notes()
        full_docs = []
        for n in notes:
            try:
                full_note = await self.vault_manager.get_note(n["path"])
                full_docs.append(full_note)
            except Exception:  # noqa: BLE001
                full_docs.append(n)
        self.search_engine.index(full_docs)

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Findet relevante Notizen per BM25."""
        await self.refresh_index()
        return self.search_engine.search(query=query, top_k=top_k)

    async def generate_answer(self, query: str, top_k: int = 3) -> dict[str, Any]:
        """Synthetisiert eine Antwort basierend auf dem abgerufenen Kontext."""
        retrieved_docs = await self.retrieve(query=query, top_k=top_k)
        if not retrieved_docs:
            return {
                "query": query,
                "answer": "Keine relevanten Notizen im Vault gefunden, um die Frage zu beantworten.",
                "context": [],
            }

        context_blocks = []
        for d in retrieved_docs:
            context_blocks.append(f"### Notiz: {d['title']}\n{d['snippet']}")

        combined_context = "\n\n".join(context_blocks)
        answer = (
            f"Basierend auf {len(retrieved_docs)} relevanten Dokumenten im Wissens-Hub:\n\n"
            f"Zusammenfassender Kontext:\n{combined_context}"
        )

        return {
            "query": query,
            "answer": answer,
            "context": retrieved_docs,
        }
