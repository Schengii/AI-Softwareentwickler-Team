"""
tests/test_workspace_hygiene.py – Tests für die smarte Workspace-Hygiene (Option 1).
"""

import os
import time
from pathlib import Path

from core.workspace_hygiene import (
    PRUNABLE_DIR_NAMES,
    prune_project_artifacts,
    run_workspace_hygiene,
)


def test_prunable_dirs_contains_expected_artifacts():
    assert ".ai_team_venv" in PRUNABLE_DIR_NAMES
    assert "node_modules" in PRUNABLE_DIR_NAMES
    assert ".pytest_cache" in PRUNABLE_DIR_NAMES
    assert "dist" in PRUNABLE_DIR_NAMES


def test_recent_project_is_not_pruned(tmp_path: Path):
    project_dir = tmp_path / "active_project"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("print('hello')", encoding="utf-8")
    venv_dir = project_dir / ".ai_team_venv"
    venv_dir.mkdir()
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin", encoding="utf-8")

    # Projekt wurde gerade eben angelegt -> jünger als 7 Tage
    result = prune_project_artifacts(project_dir, max_age_days=7.0, dry_run=False)

    assert result.removed_dirs == []
    assert result.freed_bytes == 0
    assert venv_dir.exists()
    assert (project_dir / "main.py").exists()


def test_old_project_prunes_artifacts_but_keeps_source(tmp_path: Path):
    project_dir = tmp_path / "old_project"
    project_dir.mkdir()
    source_file = project_dir / "main.py"
    source_file.write_text("print('core code')", encoding="utf-8")

    venv_dir = project_dir / ".ai_team_venv"
    venv_dir.mkdir()
    (venv_dir / "dummy.txt").write_text("x" * 1000, encoding="utf-8")

    node_dir = project_dir / "node_modules"
    node_dir.mkdir()
    (node_dir / "package.json").write_text("y" * 2000, encoding="utf-8")

    # Setze mtime von Projekt und Quellcode auf 10 Tage in die Vergangenheit
    old_time = time.time() - (10 * 86400.0)
    os.utime(project_dir, (old_time, old_time))
    os.utime(source_file, (old_time, old_time))

    result = prune_project_artifacts(project_dir, max_age_days=7.0, dry_run=False)

    assert set(result.removed_dirs) == {".ai_team_venv", "node_modules"}
    assert result.freed_bytes == 3000
    assert not venv_dir.exists()
    assert not node_dir.exists()
    # Quellcode bleibt IMMER erhalten
    assert source_file.exists()


def test_keep_file_protects_old_project(tmp_path: Path):
    project_dir = tmp_path / "protected_project"
    project_dir.mkdir()
    source_file = project_dir / "main.py"
    source_file.write_text("print('protected')", encoding="utf-8")
    (project_dir / ".keep").write_text("", encoding="utf-8")

    venv_dir = project_dir / ".ai_team_venv"
    venv_dir.mkdir()
    (venv_dir / "dummy.txt").write_text("x" * 500, encoding="utf-8")

    old_time = time.time() - (15 * 86400.0)
    os.utime(project_dir, (old_time, old_time))
    os.utime(source_file, (old_time, old_time))

    result = prune_project_artifacts(project_dir, max_age_days=7.0, dry_run=False)

    assert result.removed_dirs == []
    assert venv_dir.exists()


def test_dry_run_does_not_delete_files(tmp_path: Path):
    project_dir = tmp_path / "dry_run_project"
    project_dir.mkdir()
    source_file = project_dir / "app.py"
    source_file.write_text("print('app')", encoding="utf-8")

    cache_dir = project_dir / ".pytest_cache"
    cache_dir.mkdir()
    (cache_dir / "cache_file.txt").write_text("cache content", encoding="utf-8")

    old_time = time.time() - (10 * 86400.0)
    os.utime(project_dir, (old_time, old_time))
    os.utime(source_file, (old_time, old_time))

    result = prune_project_artifacts(project_dir, max_age_days=7.0, dry_run=True)

    assert result.removed_dirs == [".pytest_cache"]
    assert result.freed_bytes > 0
    # Im Dry-Run darf nichts physisch gelöscht werden!
    assert cache_dir.exists()


def test_run_workspace_hygiene_scans_multiple_projects(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Projekt 1: Neu -> wird ignoriert
    p1 = workspace / "p1_fresh"
    p1.mkdir()
    (p1 / "main.py").write_text("code", encoding="utf-8")

    # Projekt 2: Alt -> bereinigt venv
    p2 = workspace / "p2_old"
    p2.mkdir()
    p2_code = p2 / "main.py"
    p2_code.write_text("code", encoding="utf-8")
    p2_venv = p2 / ".ai_team_venv"
    p2_venv.mkdir()
    (p2_venv / "file.txt").write_text("bytes", encoding="utf-8")

    old_time = time.time() - (12 * 86400.0)
    os.utime(p2, (old_time, old_time))
    os.utime(p2_code, (old_time, old_time))

    report = run_workspace_hygiene(workspace_dir=workspace, max_age_days=7.0, dry_run=False)

    assert report.scanned_projects == 2
    assert report.pruned_projects == 1
    assert not p2_venv.exists()
    assert "Workspace-Hygiene" in report.format_summary()
