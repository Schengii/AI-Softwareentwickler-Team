"""
tests/test_advanced_features.py – Unit-Tests für RAG-Indexing, MCP-Server & Web-Dashboard
"""

import asyncio
import unittest

from core.vector_store import CodeVectorIndex
from interface.mcp_server import MCPServer


class TestAdvancedFeatures(unittest.TestCase):
    """Testet VectorStore, MCP-Server und Web-Dashboard API."""

    def test_vector_store_indexing_and_search(self):
        index = CodeVectorIndex()
        file_map = {
            "auth/service.py": "def authenticate_user(username, password):\n    # Verify JWT token\n    return token",
            "db/models.py": "class User(BaseModel):\n    id: int\n    username: str\n    email: str",
            "api/routes.py": "async def get_items():\n    return {'items': []}"
        }
        count = index.index_files(file_map, chunk_lines=10)
        self.assertGreaterEqual(count, 3)

        results = index.search("authenticate JWT", top_k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["file"], "auth/service.py")

    def test_mcp_server_tools_list(self):
        server = MCPServer()
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        res = asyncio.run(server.handle_request(req))
        self.assertEqual(res["id"], 1)
        tools = res["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("ai_team_develop", tool_names)
        self.assertIn("ai_team_rag_search", tool_names)
        self.assertIn("ai_team_list_projects", tool_names)


if __name__ == "__main__":
    unittest.main()
