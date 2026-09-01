"""
tests/test_mcp_server_extended.py – Tests für erweiterte MCP-Tools und MCP-Ressourcen
"""

from unittest.mock import patch

import pytest

from interface.mcp_server import MCPServer


@pytest.mark.anyio
async def test_mcp_server_tools_list():
    server = MCPServer()
    resp = await server.handle_request({"id": 1, "method": "tools/list"})
    assert resp["id"] == 1
    tool_names = [t["name"] for t in resp["result"]["tools"]]
    assert "ai_team_develop" in tool_names
    assert "ai_team_list_projects" in tool_names
    assert "ai_team_rag_search" in tool_names
    assert "ai_team_run_tests" in tool_names
    assert "ai_team_explain_symbol" in tool_names
    assert "ai_team_get_backlog" in tool_names


@pytest.mark.anyio
async def test_mcp_server_resources_list_and_read():
    server = MCPServer()
    resp_list = await server.handle_request({"id": 2, "method": "resources/list"})
    assert resp_list["id"] == 2
    uris = [r["uri"] for r in resp_list["result"]["resources"]]
    assert "ki-team://backlog" in uris
    assert "ki-team://projects" in uris

    with patch("core.backlog_store.list_tickets") as mock_tickets:
        from core.backlog_store import Ticket
        mock_t = Ticket(id="ticket-1", title="Test Ticket", source="mcp", status="todo", created_at="2026-08-29T10:00:00Z", updated_at="2026-08-29T10:00:00Z")
        mock_tickets.return_value = [mock_t]
        resp_read = await server.handle_request({
            "id": 3,
            "method": "resources/read",
            "params": {"uri": "ki-team://backlog"},
        })
        assert resp_read["id"] == 3
        assert "Test Ticket" in resp_read["result"]["contents"][0]["text"]


@pytest.mark.anyio
async def test_mcp_server_explain_symbol(tmp_path):
    server = MCPServer()
    py_file = tmp_path / "calc.py"
    py_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    with patch("core.workspace.WorkspaceManager.get_project_dir", return_value=tmp_path):
        resp = await server.handle_request({
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "ai_team_explain_symbol",
                "arguments": {"project": "test-calc", "symbol": "add"},
            },
        })
        assert resp["id"] == 4
        text = resp["result"]["content"][0]["text"]
        assert "add" in text
        assert "Definiert in `calc.py`" in text
