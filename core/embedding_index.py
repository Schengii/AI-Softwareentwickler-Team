"""
core/embedding_index.py – Echtes Embedding-basiertes RAG statt reinem BM25-Keyword-Matching

Vorher (core/vector_store.py::CodeVectorIndex) war die Codesuche reines TF-IDF/BM25 auf
Wort-Overlap – findet "authenticate" nicht, wenn nach "Login-Logik" gesucht wird, und wird
bei JEDEM Aufruf komplett neu aus dem Dateisystem aufgebaut (teuer bei großen Projekten,
besonders da core/agent_toolbox.py's search_code-Werkzeug während eines agentischen Loops
mehrfach pro Aufgabe aufgerufen werden kann).

Diese Datei ersetzt das durch echte semantische Suche über Gemini-Embeddings
(gemini-embedding-001, 768 Dimensionen), MIT persistentem Cache pro Projekt
(workspace/<projekt>/.ai_team_rag/index.json): Nur neu hinzugekommene oder geänderte
Dateien (SHA-256-Hash-Vergleich) werden neu eingebettet, nicht das gesamte Projekt bei
jedem Aufruf – wichtig sowohl für Tokenverbrauch/Kosten als auch Latenz.

Fällt automatisch auf die bestehende BM25-Suche zurück, wenn kein GEMINI_API_KEY vorhanden
ist oder ein Embedding-Aufruf fehlschlägt (core/vector_store.py bleibt deshalb bestehen).
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from config import GEMINI_API_KEY

CACHE_DIRNAME = ".ai_team_rag"
CACHE_FILENAME = "index.json"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
CHUNK_LINES = 40
EMBED_BATCH_SIZE = 50
MAX_CHARS_PER_CHUNK = 6000  # Sicherheitsnetz gegen die Token-Obergrenze der Embedding-API

VALID_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".yml", ".yaml", ".sql", ".html", ".css"}
IGNORED_DIR_PARTS = {".venv", "venv", ".ai_team_venv", CACHE_DIRNAME, "__pycache__", ".git", "node_modules", "dist", "build"}


@dataclass
class SemanticChunk:
    file: str
    line_start: int
    text: str
    embedding: list[float] = field(default_factory=list)


class EmbeddingCodeIndex:
    """
    Persistenter, echter Embedding-Index für semantische Codesuche EINES Projektverzeichnisses.
    """

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()
        self.cache_dir = self.project_dir / CACHE_DIRNAME
        self.cache_file = self.cache_dir / CACHE_FILENAME
        self._file_entries: dict[str, dict] = {}  # rel_path -> {"hash": ..., "chunks": [...]}
        self._loaded = False

    # ── Persistenz ──────────────────────────────────────────────

    def _load_cache(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.cache_file.exists():
            return
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            if data.get("model") == EMBEDDING_MODEL and data.get("dimensionality") == EMBEDDING_DIM:
                self._file_entries = data.get("files", {})
        except Exception:
            self._file_entries = {}

    def _save_cache(self) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {"model": EMBEDDING_MODEL, "dimensionality": EMBEDDING_DIM, "files": self._file_entries}
            self.cache_file.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass  # Cache ist reine Performance-Optimierung – ein Schreibfehler darf die Suche nicht blockieren

    @staticmethod
    def _hash_content(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()

    # ── Indexierung (nur geänderte Dateien) ──────────────────────

    def sync(self) -> int:
        """
        Gleicht den Cache mit dem aktuellen Dateisystemstand ab: neue/geänderte Dateien werden
        neu eingebettet, gelöschte Dateien aus dem Cache entfernt, unveränderte Dateien
        übersprungen (Hash-Vergleich). Gibt die Anzahl NEU eingebetteter Chunks zurück.
        """
        self._load_cache()
        if not GEMINI_API_KEY:
            return 0

        current_files = self._collect_files()
        pending: dict[str, list[SemanticChunk]] = {}
        chunks_to_embed: list[SemanticChunk] = []

        for rel_path, content in current_files.items():
            file_hash = self._hash_content(content)
            existing = self._file_entries.get(rel_path)
            if existing and existing.get("hash") == file_hash:
                continue  # Datei unverändert -> überspringen, keine erneute Einbettung
            new_chunks = self._chunk_text(rel_path, content)
            pending[rel_path] = new_chunks
            chunks_to_embed.extend(new_chunks)

        removed = set(self._file_entries.keys()) - set(current_files.keys())
        for rel_path in removed:
            del self._file_entries[rel_path]

        if not chunks_to_embed:
            if removed:
                self._save_cache()
            return 0

        embedded_count = 0
        for batch_start in range(0, len(chunks_to_embed), EMBED_BATCH_SIZE):
            batch = chunks_to_embed[batch_start: batch_start + EMBED_BATCH_SIZE]
            try:
                vectors = self._embed_batch([c.text for c in batch], task_type="RETRIEVAL_DOCUMENT")
            except Exception:
                continue  # Diese Batch bleibt uneingebettet -> wird beim nächsten sync() erneut versucht
            # strict=True: Chunk- und Vektor-Liste MÜSSEN gleich lang sein (1 Embedding pro
            # Chunk) – bei Längen-Mismatch lieber laut scheitern (semantic_search() faengt
            # das ab und faellt auf BM25 zurueck), statt Chunks still mit falschen Vektoren
            # zu verknuepfen.
            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector
                embedded_count += 1

        for rel_path, chunks in pending.items():
            embedded_chunks = [c for c in chunks if c.embedding]
            if embedded_chunks:
                self._file_entries[rel_path] = {
                    "hash": self._hash_content(current_files[rel_path]),
                    "chunks": [
                        {"line_start": c.line_start, "text": c.text, "embedding": c.embedding}
                        for c in embedded_chunks
                    ],
                }
            # Schlägt die Einbettung komplett fehl, bleibt rel_path außerhalb von _file_entries ->
            # wird beim nächsten sync()-Aufruf automatisch erneut als "neu" behandelt.

        self._save_cache()
        return embedded_count

    def _collect_files(self) -> dict[str, str]:
        file_map: dict[str, str] = {}
        if not self.project_dir.exists():
            return file_map
        for p in self.project_dir.rglob("*"):
            if p.is_file() and p.suffix in VALID_EXTENSIONS and not any(part in IGNORED_DIR_PARTS for part in p.parts):
                try:
                    file_map[str(p.relative_to(self.project_dir)).replace("\\", "/")] = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
        return file_map

    @staticmethod
    def _chunk_text(rel_path: str, content: str) -> list[SemanticChunk]:
        lines = content.splitlines()
        chunks = []
        for i in range(0, max(len(lines), 1), CHUNK_LINES):
            text = "\n".join(lines[i: i + CHUNK_LINES]).strip()[:MAX_CHARS_PER_CHUNK]
            if text:
                chunks.append(SemanticChunk(file=rel_path, line_start=i + 1, text=text))
        return chunks

    @staticmethod
    def _embed_batch(texts: list[str], task_type: str) -> list[list[float]]:
        from google.genai import types as genai_types

        from core.llm_factory import _gemini_client  # bereits initialisierter globaler Client

        if not _gemini_client:
            raise RuntimeError("Gemini-Client nicht initialisiert (kein GEMINI_API_KEY).")
        response = _gemini_client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=texts,
            config=genai_types.EmbedContentConfig(task_type=task_type, output_dimensionality=EMBEDDING_DIM),
        )
        return [list(e.values) for e in response.embeddings]

    # ── Suche ─────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Synct den Index (nur geänderte Dateien) und sucht dann semantisch."""
        self.sync()

        all_chunks = [
            {"file": rel_path, "line_start": c["line_start"], "text": c["text"], "embedding": c["embedding"]}
            for rel_path, entry in self._file_entries.items()
            for c in entry.get("chunks", [])
        ]
        if not all_chunks or not GEMINI_API_KEY:
            return []

        try:
            query_vector = self._embed_batch([query], task_type="RETRIEVAL_QUERY")[0]
        except Exception:
            return []

        scored = [(self._cosine_similarity(query_vector, c["embedding"]), c) for c in all_chunks]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"file": c["file"], "line_start": c["line_start"], "chunk": c["text"], "score": round(score, 4)}
            for score, c in scored[:top_k]
            if score > 0
        ]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=True))  # Längen oben bereits geprüft
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)


def semantic_search(project_dir: str | Path, query: str, top_k: int = 5) -> list[dict]:
    """
    Zentraler Haupteinstiegspunkt für Codesuche im ganzen Team: versucht echte Embedding-
    Suche und fällt automatisch auf BM25-Keyword-Suche (core/vector_store.py) zurück,
    wenn kein GEMINI_API_KEY vorhanden ist, die Embedding-API fehlschlägt, oder keine
    Treffer über einem Mindest-Ähnlichkeitswert gefunden wurden.
    """
    if GEMINI_API_KEY:
        try:
            results = EmbeddingCodeIndex(project_dir).search(query, top_k=top_k)
            if results:
                return results
        except Exception:
            pass  # BM25-Fallback unten

    from core.vector_store import CodeVectorIndex

    project_path = Path(project_dir).resolve()
    file_map: dict[str, str] = {}
    if project_path.exists():
        for p in project_path.rglob("*"):
            if p.is_file() and p.suffix in VALID_EXTENSIONS and not any(part in IGNORED_DIR_PARTS for part in p.parts):
                try:
                    file_map[str(p.relative_to(project_path)).replace("\\", "/")] = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

    if not file_map:
        return []

    bm25 = CodeVectorIndex()
    bm25.index_files(file_map)
    return bm25.search(query, top_k=top_k)
