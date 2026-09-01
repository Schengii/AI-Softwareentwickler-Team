from core.project_status import (
    STATE_MD_FILENAME,
    STATUS_FILENAME,
    format_context_for_agents,
    generate_project_state_md,
    read_project_state_md,
    read_status,
    save_project_checkpoint,
)


def test_generate_project_state_md_basic(tmp_path):
    # Create sample files in tmp_path
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "models.py").write_text("class Poll: pass", encoding="utf-8")
    
    state_md = generate_project_state_md(
        project_dir=str(tmp_path),
        task_summary="FastAPI Backend implementiert",
        verification_ok=True,
        next_steps=["Frontend anbinden", "Docker testen"],
    )
    
    assert tmp_path.name in state_md
    assert "✅ Vollständig verifiziert" in state_md
    assert "FastAPI Backend implementiert" in state_md
    assert "`main.py`" in state_md
    assert "`models.py`" in state_md
    assert "1. Frontend anbinden" in state_md
    assert "2. Docker testen" in state_md

def test_save_and_read_project_checkpoint(tmp_path):
    (tmp_path / "app.py").write_text("import fastapi", encoding="utf-8")
    
    save_project_checkpoint(
        project_dir=str(tmp_path),
        task_summary="WebSocket Handler hinzugefügt",
        verification_ok=False,
        budget_aborted=True,
        files_written_count=1,
        files_written=["app.py"],
        next_steps=["Tests reparieren"],
    )
    
    state_path = tmp_path / STATE_MD_FILENAME
    status_path = tmp_path / STATUS_FILENAME
    
    assert state_path.exists()
    assert status_path.exists()
    
    content = read_project_state_md(str(tmp_path))
    assert "🚫 Lauf-Budget erreicht" in content
    assert "WebSocket Handler hinzugefügt" in content
    assert "1. Tests reparieren" in content
    
    history = read_status(str(tmp_path))
    assert len(history) == 1
    assert history[0]["task_summary"] == "WebSocket Handler hinzugefügt"
    assert history[0]["budget_aborted"] is True

def test_format_context_for_agents_uses_state_md(tmp_path):
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    save_project_checkpoint(
        project_dir=str(tmp_path),
        task_summary="Init Projekt",
        verification_ok=True,
    )
    
    agent_context = format_context_for_agents(str(tmp_path))
    assert f"## 📌 Aktueller Projekt-Checkpoint (`{STATE_MD_FILENAME}`):" in agent_context
    assert tmp_path.name in agent_context
    assert "✅ Vollständig verifiziert" in agent_context

def test_read_project_state_md_nonexistent(tmp_path):
    assert read_project_state_md(str(tmp_path / "nonexistent")) == ""
