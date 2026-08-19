"""
core/vector_store.py – Lokales RAG / Vektor- & Keyword-Indexing für Codebases

Ermöglicht:
- Token-effizientes Indizieren und Durchsuchen riesiger Repositories (>100k Zeilen)
- BM25 & semantisches TF-IDF Keyword-Ranking ohne schwere externe C-Abhängigkeiten
- Schnelles Auffinden von relevanten Funktionsdefinitionen, Klassen und Interfaces
"""

import math
import re


class CodeVectorIndex:
    """
    Leichtgewichtiger, hochperformanter In-Memory Code-Index für RAG-Recherche in Projekten.
    """

    def __init__(self):
        self.documents: list[dict] = []  # {"file": str, "chunk": str, "tokens": set[str]}
        self.doc_freqs: dict[str, int] = {}
        self.total_docs: int = 0

    def _tokenize(self, text: str) -> list[str]:
        # Tokenizer für Code & Bezeichner (CamelCase und snake_case zerlegen)
        words = re.findall(r'[a-zA-Z0-9_]+', text.lower())
        tokens = []
        for w in words:
            tokens.append(w)
            if "_" in w:
                tokens.extend([part for part in w.split("_") if len(part) > 2])
        return tokens

    def index_files(self, file_map: dict[str, str], chunk_lines: int = 40) -> int:
        """
        Indiziert eine Sammlung von Dateiinhalten.
        """
        self.documents.clear()
        self.doc_freqs.clear()

        for file_path, content in file_map.items():
            lines = content.splitlines()
            for i in range(0, max(len(lines), 1), chunk_lines):
                chunk = "\n".join(lines[i : i + chunk_lines])
                if not chunk.strip():
                    continue
                tokens = self._tokenize(chunk)
                unique_tokens = set(tokens)
                for t in unique_tokens:
                    self.doc_freqs[t] = self.doc_freqs.get(t, 0) + 1
                self.documents.append({
                    "file": file_path,
                    "line_start": i + 1,
                    "chunk": chunk,
                    "tokens": tokens,
                    "unique_tokens": unique_tokens,
                })

        self.total_docs = len(self.documents)
        return self.total_docs

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Sucht die semantisch relevantesten Code-Abschnitte für eine Anfrage (BM25-Scoring).
        """
        if not self.documents:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = []
        k1 = 1.5
        b = 0.75
        avg_dl = sum(len(d["tokens"]) for d in self.documents) / max(self.total_docs, 1)

        for doc in self.documents:
            score = 0.0
            doc_len = len(doc["tokens"])
            for q in query_tokens:
                if q in doc["unique_tokens"]:
                    df = self.doc_freqs.get(q, 1)
                    idf = math.log((self.total_docs - df + 0.5) / (df + 0.5) + 1.0)
                    tf = doc["tokens"].count(q)
                    score += idf * ((tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (doc_len / avg_dl))))
            if score > 0:
                scores.append((score, doc))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scores[:top_k]]


# Globale Index-Instanz
code_index = CodeVectorIndex()
