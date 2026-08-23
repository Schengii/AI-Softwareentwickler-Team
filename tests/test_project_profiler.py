"""
tests/test_project_profiler.py – Tests für die automatische Brownfield- und Multi-Projekt-Erkennung
"""

import json
from pathlib import Path

from core.project_profiler import ProjectProfile, ProjectProfiler, format_profile_for_agents


def test_profiler_empty_directory(tmp_path: Path):
    profile = ProjectProfiler.profile_directory(tmp_path)
    assert isinstance(profile, ProjectProfile)
    assert not profile.is_brownfield
    assert profile.total_source_files == 0


def test_profiler_python_fastapi_project(tmp_path: Path):
    # Erstelle Fake FastAPI Projekt
    (tmp_path / "requirements.txt").write_text("fastapi==0.110.0\nuvicorn\npytest\nruff", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()", encoding="utf-8")
    (tmp_path / "src" / "models.py").write_text("class Item: pass", encoding="utf-8")
    (tmp_path / "src" / "routes.py").write_text("def get_items(): return []", encoding="utf-8")
    (tmp_path / "src" / "db.py").write_text("def get_db(): pass", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_app(): assert True", encoding="utf-8")

    profile = ProjectProfiler.profile_directory(tmp_path)
    assert profile.is_brownfield
    assert "Python" in profile.primary_languages
    assert "FastAPI" in profile.frameworks
    assert "pip" in profile.package_managers
    assert "pytest" in profile.test_frameworks
    assert "ruff" in profile.linters
    assert "Code liegt in src/" in profile.conventions

    formatted = format_profile_for_agents(profile)
    assert "Projekt-Kontext & Erkannte Architektur" in formatted
    assert "FastAPI" in formatted


def test_profiler_nodejs_react_monorepo(tmp_path: Path):
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "my-monorepo",
        "dependencies": {"react": "^18.2.0", "typescript": "^5.0.0"},
        "devDependencies": {"vitest": "^1.0.0", "eslint": "^8.0.0"}
    }), encoding="utf-8")
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'", encoding="utf-8")
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "App.tsx").write_text("export const App = () => <div>Hello</div>;", encoding="utf-8")
    (tmp_path / "apps" / "web" / "index.ts").write_text("console.log('init')", encoding="utf-8")
    (tmp_path / "apps" / "web" / "utils.ts").write_text("export const add = (a, b) => a + b;", encoding="utf-8")
    (tmp_path / "apps" / "web" / "api.ts").write_text("export const fetcher = () => {};", encoding="utf-8")

    profile = ProjectProfiler.profile_directory(tmp_path)
    assert profile.is_monorepo
    assert "TypeScript (React)" in profile.primary_languages or "TypeScript" in profile.primary_languages
    assert "React" in profile.frameworks
    assert "vitest" in profile.test_frameworks
    assert "eslint" in profile.linters
    assert "Monorepo" in profile.architecture_style


def test_profiler_polyglot_detection(tmp_path: Path):
    # Rust + Cargo
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'test-rs'\nversion = '0.1.0'", encoding="utf-8")
    # Java + Maven
    (tmp_path / "pom.xml").write_text("<project><dependencies><dependency><groupId>org.springframework.boot</groupId></dependency></dependencies></project>", encoding="utf-8")
    # C#
    (tmp_path / "App.csproj").write_text("<Project Sdk=\"Microsoft.NET.Sdk\"></Project>", encoding="utf-8")
    # Flutter
    (tmp_path / "pubspec.yaml").write_text("name: flutter_app\ndependencies:\n  flutter:\n    sdk: flutter", encoding="utf-8")

    profile = ProjectProfiler.profile_directory(tmp_path)
    assert "cargo" in profile.package_managers
    assert "maven" in profile.package_managers
    assert "dotnet/nuget" in profile.package_managers
    assert "flutter/pub" in profile.package_managers
    assert "Spring Boot" in profile.frameworks
    assert "Flutter / Dart" in profile.frameworks
