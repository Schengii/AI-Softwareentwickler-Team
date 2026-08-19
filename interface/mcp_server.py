"""
interface/mcp_server.py – Model Context Protocol (MCP) Server für das KI-Team

Ermöglicht:
- Direkte Integration in Cursor, Windsurf, Antigravity und Claude Desktop
- Bereitstellung von Tools:
  - `ai_team_develop`: Startet den 32-Agenten-Workflow für eine beliebige Aufgabe
  - `ai_team_list_projects`: Listet alle Workspace-Projekte auf
  - `ai_team_rag_search`: Durchsucht den Codebase-Index semantisch
"""

import json
import sys
import asyncio
from typing import Any


class MCPServer:
    """
    Standard-konformer JSON-RPC 2.0 MCP-Server über stdin/stdout.
    """

    def __init__(self):
        self.tools = [
            {
                "name": "ai_team_develop",
                "description": "Führt das 32-köpfige autonome KI-Entwicklerteam aus, um Software, Module oder Refactorings zu erstellen.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Die Aufgabenbeschreibung oder das Feature für das KI-Team."
                        }
                    },
                    "required": ["prompt"]
                }
            },
            {
                "name": "ai_team_list_projects",
                "description": "Listet alle existierenden Projekte im Workspace des KI-Entwicklerteams auf.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "ai_team_rag_search",
                "description": "Durchsucht ein Projekt im Workspace semantisch (echte Gemini-Embeddings mit BM25-Fallback) nach relevanten Codeabschnitten.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Name des Projekts im Workspace (siehe ai_team_list_projects)."
                        },
                        "query": {
                            "type": "string",
                            "description": "Suchbegriff oder Code-Funktion."
                        }
                    },
                    "required": ["project", "query"]
                }
            }
        ]

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        req_id = request.get("id")
        method = request.get("method")

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.tools}
            }

        elif method == "tools/call":
            params = request.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})

            if name == "ai_team_list_projects":
                from core.workspace import WorkspaceManager
                ws = WorkspaceManager()
                projects = ws.list_projects()
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Vorhandene Projekte: {', '.join(projects) if projects else 'Keine'}"}]
                    }
                }

            elif name == "ai_team_rag_search":
                from core.embedding_index import semantic_search
                from core.workspace import WorkspaceManager
                project = arguments.get("project", "")
                query = arguments.get("query", "")
                project_dir = WorkspaceManager().get_project_dir(project) if project else None
                results = semantic_search(project_dir, query, top_k=3) if project_dir else []
                res_text = "\n\n".join([f"Datei: {r['file']} (Zeile {r['line_start']}):\n{r['chunk']}" for r in results]) or "Keine Treffer gefunden."
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": res_text}]
                    }
                }

            elif name == "ai_team_develop":
                from agents.orchestrator import Orchestrator
                prompt = arguments.get("prompt", "")
                orch = Orchestrator()
                output = await orch.process(prompt)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": output}]
                    }
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Tool '{name}' nicht gefunden"}
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32600, "message": "Ungültige Anfrage"}
        }

    async def run_stdio(self):
        """Startet den Server im Stdio-Modus für IDE-Kopplungen."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                data = json.loads(line.decode("utf-8"))
                response = await self.handle_request(data)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
            except Exception as e:
                err_resp = {"jsonrpc": "2.0", "error": {"code": -32700, "message": str(e)}}
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    server = MCPServer()
    asyncio.run(server.run_stdio())
