"""
tests/test_embedding_index.py – Testet das persistente Embedding-RAG (core/embedding_index.py)

Der echte Gemini-Embedding-Aufruf wird gemockt (deterministische Fake-Vektoren via
Feature-Hashing), damit die Tests schnell, kostenlos und ohne API-Key laufen – geprüft
wird die eigentliche Logik: inkrementelles Sync (nur geänderte Dateien neu einbetten),
Persistenz über mehrere Instanzen hinweg, und der BM25-Fallback ohne API-Key.
"""

import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.embedding_index import EMBEDDING_DIM, EmbeddingCodeIndex, semantic_search

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def _fake_embed(texts: list[str], task_type: str) -> list[list[float]]:
    """Deterministisches Feature-Hashing statt echtem API-Aufruf: Texte mit gemeinsamen
    Wörtern (Wortgrenzen per Regex statt naivem .split(), damit z.B. 'jwt_token(x)' auch
    auf die Query 'jwt token' matcht) bekommen ähnliche Vektoren – reicht, um die
    Ranking-Logik zu testen, ohne echte Semantik zu brauchen."""
    vectors = []
    for text in texts:
        vec = [0.0] * EMBEDDING_DIM
        for word in _WORD_RE.findall(text.lower()):
            vec[hash(word) % EMBEDDING_DIM] += 1.0
        vectors.append(vec)
    return vectors


class TestEmbeddingCodeIndex(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        self.embed_patcher = patch.object(EmbeddingCodeIndex, "_embed_batch", side_effect=_fake_embed)
        self.mock_embed = self.embed_patcher.start()
        self.addCleanup(self.embed_patcher.stop)
        self.key_patcher = patch("core.embedding_index.GEMINI_API_KEY", "fake-key-for-tests")
        self.key_patcher.start()
        self.addCleanup(self.key_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write(self, rel_path: str, content: str) -> None:
        p = self.project_dir / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def test_sync_embeds_new_files(self):
        self._write("auth.py", "def authenticate_user(username, password):\n    return verify_jwt(username)\n")
        index = EmbeddingCodeIndex(self.project_dir)
        embedded = index.sync()
        self.assertGreater(embedded, 0)
        self.assertIn("auth.py", index._file_entries)

    def test_sync_skips_unchanged_files_on_second_call(self):
        self._write("auth.py", "def authenticate_user():\n    pass\n")
        index = EmbeddingCodeIndex(self.project_dir)
        index.sync()
        call_count_after_first = self.mock_embed.call_count

        index.sync()  # nichts geändert -> darf NICHT erneut embedden
        self.assertEqual(self.mock_embed.call_count, call_count_after_first)

    def test_sync_reembeds_changed_file_only(self):
        self._write("auth.py", "def authenticate_user():\n    pass\n")
        self._write("db.py", "def connect():\n    pass\n")
        index = EmbeddingCodeIndex(self.project_dir)
        index.sync()
        calls_after_first = self.mock_embed.call_count

        self._write("auth.py", "def authenticate_user():\n    return True\n")  # nur diese Datei ändert sich
        index.sync()
        self.assertGreater(self.mock_embed.call_count, calls_after_first)

    def test_sync_removes_deleted_files_from_cache(self):
        self._write("temp.py", "x = 1\n")
        index = EmbeddingCodeIndex(self.project_dir)
        index.sync()
        self.assertIn("temp.py", index._file_entries)

        (self.project_dir / "temp.py").unlink()
        index.sync()
        self.assertNotIn("temp.py", index._file_entries)

    def test_cache_persists_across_instances(self):
        self._write("auth.py", "def authenticate_user():\n    pass\n")
        EmbeddingCodeIndex(self.project_dir).sync()

        # Neue Instanz auf demselben Verzeichnis -> muss den Cache von der Platte laden,
        # nicht erneut embedden.
        fresh_index = EmbeddingCodeIndex(self.project_dir)
        fresh_index.sync()
        self.assertIn("auth.py", fresh_index._file_entries)
        cache_file = self.project_dir / ".ai_team_rag" / "index.json"
        self.assertTrue(cache_file.exists())

    def test_search_ranks_relevant_chunk_higher(self):
        self._write("auth.py", "def authenticate_user(username, password):\n    verify_jwt_token(username)\n")
        self._write("unrelated.py", "def calculate_shipping_cost(weight, distance):\n    return weight * distance\n")
        index = EmbeddingCodeIndex(self.project_dir)
        results = index.search("authenticate jwt token", top_k=2)
        self.assertTrue(results)
        self.assertEqual(results[0]["file"], "auth.py")

    def test_semantic_search_falls_back_to_bm25_without_api_key(self):
        self._write("auth.py", "def authenticate_user():\n    pass\n")
        with patch("core.embedding_index.GEMINI_API_KEY", ""):
            results = semantic_search(self.project_dir, "authenticate", top_k=3)
        # BM25-Fallback muss trotzdem einen Treffer liefern, ganz ohne Embedding-Aufruf.
        self.assertTrue(any(r["file"] == "auth.py" for r in results))
        self.mock_embed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
