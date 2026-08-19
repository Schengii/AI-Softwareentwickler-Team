"""
core/tool_registry.py – Werkzeug- & Tooling-Registry für Agenten

Ermöglicht Agenten den Zugriff auf standardisierte Tools:
- Dateisystem-Operationen (Lesen, Suchen, Schreiben)
- Statische Code-Analyse & Syntax-Check
- Web-Recherche / Dokumentations-Abfrage
- MCP-kompatibles Schnittstellen-Design
"""

import os
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Optional
from pathlib import Path

from core.code_sandbox import CodeSandbox
from core.workspace import WorkspaceManager


@dataclass
class ToolDefinition:
    """Metadaten und Ausführungsfunktion eines Tools."""
    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: Callable[..., Coroutine[Any, Any, Any]]


class ToolRegistry:
    """
    Zentrale Registry für agentenfähige Werkzeuge (Tools).
    """

    def __init__(self, workspace_manager: Optional[WorkspaceManager] = None):
        self._tools: dict[str, ToolDefinition] = {}
        self.workspace = workspace_manager or WorkspaceManager()
        self._register_default_tools()

    def register(self, tool: ToolDefinition) -> None:
        """Registriert ein neues Tool."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        """Gibt eine Liste aller Tool-Definitionen zurück."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters_schema,
            }
            for t in self._tools.values()
        ]

    def _register_default_tools(self) -> None:
        """Registriert integrierte Kern-Tools."""

        # Tool: Code-Syntax validieren
        async def validate_syntax_handler(code: str, file_type: str) -> dict:
            res = CodeSandbox.validate_code(code, file_type)
            return {
                "is_valid": res.is_valid,
                "language": res.language,
                "errors": res.errors,
                "warnings": res.warnings,
            }

        self.register(
            ToolDefinition(
                name="validate_syntax",
                description="Validiert Python, JSON oder YAML Code auf Syntaxfehler.",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Der zu prüfende Quellcode"},
                        "file_type": {"type": "string", "description": "Dateiendung wie py, json, yml"},
                    },
                    "required": ["code", "file_type"],
                },
                handler=validate_syntax_handler,
            )
        )

        # Tool: Workspace-Dateien auflisten
        async def list_workspace_files_handler(project_name: str) -> list[dict]:
            return self.workspace.list_project_files(project_name)

        self.register(
            ToolDefinition(
                name="list_workspace_files",
                description="Listet alle generierten Projektdateien eines Projekts auf.",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {"type": "string", "description": "Name des Projekts"},
                    },
                    "required": ["project_name"],
                },
                handler=list_workspace_files_handler,
            )
        )
