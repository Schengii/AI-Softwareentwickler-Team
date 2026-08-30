"""
interface/mcp_server.py – Model Context Protocol (MCP) Server für das KI-Team

Ermöglicht:
- Direkte Integration in Cursor, Windsurf, Antigravity und Claude Desktop
- Bereitstellung von Tools:
  - `ai_team_develop`: Startet den 32-Agenten-Workflow für eine beliebige Aufgabe
  - `ai_team_list_projects`: Listet alle Workspace-Projekte auf
  - `ai_team_rag_search`: Durchsucht den Codebase-Index semantisch
"""

import asyncio
import json
import sys
from typing import Any


class MCPServer:
    """
    Standard-konformer JSON-RPC 2.0 MCP-Server über stdin/stdout.
    """

    def __init__(self):
        self.tools = [
            {
                "name": "ai_team_develop",
                "description": "Führt das 33-köpfige autonome KI-Entwicklerteam aus, um Software, Module oder Refactorings zu erstellen.",
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
            },
            {
                "name": "ai_team_run_tests",
                "description": "Führt die automatisierte Testsuite für ein Workspace-Projekt isoliert aus.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Name des Projekts im Workspace."
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "ai_team_explain_symbol",
                "description": "Nutzt den AST-Code-Graph, um Definition, Aufrufe und Auswirkungsanalyse eines Code-Symbols zu ermitteln.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Name des Projekts im Workspace."
                        },
                        "symbol": {
                            "type": "string",
                            "description": "Name der Klasse, Funktion oder Methode."
                        }
                    },
                    "required": ["project", "symbol"]
                }
            },
            {
                "name": "ai_team_get_backlog",
                "description": "Liefert alle aktuellen Kanban-Tickets aus dem zentralen Backlog-Store.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
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

        elif method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "resources": [
                        {
                            "uri": "ki-team://backlog",
                            "name": "Zentraler Backlog-Store",
                            "mimeType": "application/json",
                        },
                        {
                            "uri": "ki-team://projects",
                            "name": "Workspace-Projekte",
                            "mimeType": "application/json",
                        }
                    ]
                }
            }

        elif method == "resources/read":
            params = request.get("params", {})
            uri = params.get("uri", "")
            if uri == "ki-team://backlog":
                from dataclasses import asdict, is_dataclass

                from core.backlog_store import list_tickets
                tickets = [asdict(t) if is_dataclass(t) else dict(vars(t)) for t in list_tickets()]
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(tickets, indent=2, ensure_ascii=False)}]
                    }
                }
            elif uri == "ki-team://projects":
                from core.workspace import WorkspaceManager
                projects = WorkspaceManager().list_projects()
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(projects, indent=2)}]
                    }
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Resource '{uri}' nicht gefunden"}
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

            elif name == "ai_team_get_backlog":
                from dataclasses import asdict, is_dataclass

                from core.backlog_store import list_tickets
                tickets = [asdict(t) if is_dataclass(t) else dict(vars(t)) for t in list_tickets()]
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(tickets, indent=2, ensure_ascii=False)}]
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

            elif name == "ai_team_explain_symbol":
                from core.code_graph import CodebaseGraph
                from core.workspace import WorkspaceManager
                project = arguments.get("project", "")
                symbol = arguments.get("symbol", "")
                project_dir = WorkspaceManager().get_project_dir(project) if project else None
                if not project_dir or not project_dir.exists():
                    return {
                        "jsonrpc": "2.0", "id": req_id,
                        "result": {"content": [{"type": "text", "text": f"Projekt '{project}' nicht gefunden."}]}
                    }
                graph = CodebaseGraph(project_dir)
                impact = graph.analyze_impact(symbol)
                defs = graph.find_definition(symbol)
                def_str = "\n".join([f"Definiert in `{d.file_path}` (Zeile {d.line_number}): {d.signature}" for d in defs]) or "Keine explizite Definition gefunden."
                exp_text = (
                    f"### Symbol-Analyse: `{symbol}`\n\n"
                    f"**Definition:**\n{def_str}\n\n"
                    f"**Referenzierende Dateien ({len(impact.referencing_files)}):**\n"
                    f"{', '.join(impact.referencing_files) if impact.referencing_files else 'Keine'}\n\n"
                    f"**Aufrufende Symbole ({len(impact.calling_symbols)}):**\n"
                    f"{', '.join(impact.calling_symbols) if impact.calling_symbols else 'Keine'}"
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": exp_text}]
                    }
                }

            elif name == "ai_team_run_tests":
                from core.verifier import ProjectVerifier
                from core.workspace import WorkspaceManager
                project = arguments.get("project", "")
                project_dir = WorkspaceManager().get_project_dir(project) if project else None
                if not project_dir or not project_dir.exists():
                    return {
                        "jsonrpc": "2.0", "id": req_id,
                        "result": {"content": [{"type": "text", "text": f"Projekt '{project}' nicht gefunden."}]}
                    }
                verifier = ProjectVerifier(project_dir)
                res = await verifier.verify()
                out_text = f"Status: {'✅ Bestanden' if res.tests_passed else '❌ Fehlgeschlagen'}\n\n{res.summary()}"
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": out_text}]
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
