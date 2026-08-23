"""
core/project_profiler.py – Automatische Erkennung und Profilierung bestehender Codebases (Brownfield-Scan)

Ermöglicht dem KI-Entwicklerteam, sich sofort in beliebigen bestehenden Projekten
(Python, Node/TS, Java, C#, Go, Rust, PHP, Dart/Flutter) zurechtzufinden.

Funktionen:
- Erkennt primäre Programmiersprachen und Frameworks
- Identifiziert Paketmanager und Build-Tools (pnpm, poetry, maven, gradle, cargo, etc.)
- Findet vorhandene Test-Frameworks und Konventionen
- Erkennt Monorepo- und Architekturstrukturen
- Generiert einen kompakten Kontext-Block für Planning Lead, Architect und Entwickler
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectProfile:
    """Strukturiertes Profil einer analysierten Codebase."""
    project_dir: str
    is_brownfield: bool = False
    primary_languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    test_frameworks: list[str] = field(default_factory=list)
    linters: list[str] = field(default_factory=list)
    architecture_style: str = "Standard"
    is_monorepo: bool = False
    sub_packages: list[str] = field(default_factory=list)
    total_source_files: int = 0
    conventions: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "is_brownfield": self.is_brownfield,
            "primary_languages": self.primary_languages,
            "frameworks": self.frameworks,
            "package_managers": self.package_managers,
            "test_frameworks": self.test_frameworks,
            "linters": self.linters,
            "architecture_style": self.architecture_style,
            "is_monorepo": self.is_monorepo,
            "sub_packages": self.sub_packages,
            "total_source_files": self.total_source_files,
            "conventions": self.conventions,
            "summary": self.summary,
        }


# Typische Build- und Manifest-Dateien zur Erkennung
_MANIFEST_MAP: list[tuple[str, str, str, str]] = [
    # (Dateimuster, Sprache, Paketmanager, Standard-Testrunner)
    ("pyproject.toml", "Python", "poetry/pip", "pytest"),
    ("requirements.txt", "Python", "pip", "pytest"),
    ("Pipfile", "Python", "pipenv", "pytest"),
    ("setup.py", "Python", "setuptools", "pytest"),
    ("package.json", "JavaScript/TypeScript", "npm", "npm test"),
    ("pnpm-lock.yaml", "JavaScript/TypeScript", "pnpm", "pnpm test"),
    ("yarn.lock", "JavaScript/TypeScript", "yarn", "yarn test"),
    ("Cargo.toml", "Rust", "cargo", "cargo test"),
    ("go.mod", "Go", "go", "go test"),
    ("pom.xml", "Java", "maven", "mvn test"),
    ("build.gradle", "Java/Kotlin", "gradle", "gradle test"),
    ("build.gradle.kts", "Kotlin", "gradle", "gradle test"),
    ("*.csproj", "C# / .NET", "dotnet/nuget", "dotnet test"),
    ("*.sln", "C# / .NET", "dotnet/nuget", "dotnet test"),
    ("composer.json", "PHP", "composer", "phpunit"),
    ("pubspec.yaml", "Dart / Flutter", "flutter/pub", "flutter test"),
]

# Erweiterungs-Zähler für Spracherkennung
_SOURCE_EXTENSIONS: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".vue": "Vue.js",
    ".svelte": "Svelte",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".php": "PHP",
    ".dart": "Dart",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".rb": "Ruby",
    ".swift": "Swift",
}


class ProjectProfiler:
    """Analysiert ein bestehendes Projektverzeichnis und erstellt ein ProjectProfile."""

    @staticmethod
    def profile_directory(project_dir: Path | str) -> ProjectProfile:
        root = Path(project_dir).resolve()
        if not root.exists() or not root.is_dir():
            return ProjectProfile(project_dir=str(root), summary="Verzeichnis existiert nicht oder ist leer.")

        profile = ProjectProfile(project_dir=str(root))
        lang_counts: dict[str, int] = {}
        frameworks: set[str] = set()
        package_managers: set[str] = set()
        test_frameworks: set[str] = set()
        linters: set[str] = set()
        conventions: list[str] = []

        # 1. Zähle Quelldateien und ignoriere Standard-Build-Ordner
        ignored_dirs = {
            ".git", "__pycache__", "node_modules", "venv", ".venv",
            "target", "build", "dist", ".pytest_cache", ".ruff_cache",
            ".idea", ".vscode", "vendor", "bin", "obj",
        }

        total_files = 0
        all_relative_paths: list[Path] = []

        for p in root.rglob("*"):
            if p.is_dir():
                continue
            # Prüfe ob Teil eines ignorierten Verzeichnisses
            if any(part in ignored_dirs for part in p.parts):
                continue

            all_relative_paths.append(p.relative_to(root))
            ext = p.suffix.lower()
            if ext in _SOURCE_EXTENSIONS:
                lang = _SOURCE_EXTENSIONS[ext]
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
                total_files += 1

        profile.total_source_files = total_files
        profile.is_brownfield = total_files > 3

        # Sortiere erkannte Sprachen nach Häufigkeit
        sorted_langs = sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)
        profile.primary_languages = [lang_item[0] for lang_item in sorted_langs[:4]]

        # 2. Manifeste und Paketmanager prüfen
        for pattern, _lang, pkg_mgr, test_runner in _MANIFEST_MAP:
            matches = list(root.glob(pattern))
            if matches:
                package_managers.add(pkg_mgr)
                test_frameworks.add(test_runner)

        # 3. Spezifische Framework-Erkennung durch Dateiinhalte / Konfig-Dateien
        package_json_path = root / "package.json"
        if package_json_path.exists():
            try:
                pkg_data = json.loads(package_json_path.read_text(encoding="utf-8", errors="replace"))
                deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
                if "react" in deps or "next" in deps:
                    frameworks.add("React" if "next" not in deps else "Next.js")
                if "vue" in deps or "nuxt" in deps:
                    frameworks.add("Vue" if "nuxt" not in deps else "Nuxt.js")
                if "svelte" in deps or "@sveltejs/kit" in deps:
                    frameworks.add("Svelte")
                if "express" in deps:
                    frameworks.add("Express.js")
                if "@nestjs/core" in deps:
                    frameworks.add("NestJS")
                if "vitest" in deps:
                    test_frameworks.add("vitest")
                elif "jest" in deps:
                    test_frameworks.add("jest")
                if "eslint" in deps:
                    linters.add("eslint")
                if "typescript" in deps or (root / "tsconfig.json").exists():
                    linters.add("tsc")
            except Exception:
                pass

        # Python Frameworks
        pyproject_path = root / "pyproject.toml"
        requirements_path = root / "requirements.txt"
        py_text = ""
        if pyproject_path.exists():
            py_text += pyproject_path.read_text(encoding="utf-8", errors="replace") + "\n"
        if requirements_path.exists():
            py_text += requirements_path.read_text(encoding="utf-8", errors="replace") + "\n"

        if py_text:
            py_text_lower = py_text.lower()
            if "fastapi" in py_text_lower:
                frameworks.add("FastAPI")
            if "django" in py_text_lower:
                frameworks.add("Django")
            if "flask" in py_text_lower:
                frameworks.add("Flask")
            if "pytest" in py_text_lower:
                test_frameworks.add("pytest")
            if "ruff" in py_text_lower or (root / "ruff.toml").exists():
                linters.add("ruff")
            if "mypy" in py_text_lower:
                linters.add("mypy")

        # Java / C# / PHP / Flutter Frameworks
        if (root / "pom.xml").exists() or (root / "build.gradle").exists():
            pom_txt = (root / "pom.xml").read_text(encoding="utf-8", errors="replace") if (root / "pom.xml").exists() else ""
            if "spring-boot" in pom_txt.lower() or "springframework" in pom_txt.lower():
                frameworks.add("Spring Boot")
            test_frameworks.add("JUnit")

        if list(root.glob("*.csproj")) or list(root.glob("*.sln")):
            frameworks.add("ASP.NET / .NET Core")
            test_frameworks.add("dotnet test (xUnit/NUnit)")
            linters.add("dotnet format")

        if (root / "composer.json").exists():
            composer_txt = (root / "composer.json").read_text(encoding="utf-8", errors="replace")
            if "laravel" in composer_txt.lower():
                frameworks.add("Laravel")
            elif "symfony" in composer_txt.lower():
                frameworks.add("Symfony")
            test_frameworks.add("PHPUnit")

        if (root / "pubspec.yaml").exists():
            frameworks.add("Flutter / Dart")
            test_frameworks.add("flutter test")
            linters.add("dart analyze")

        # 4. Monorepo Erkennung
        monorepo_markers = [
            root / "pnpm-workspace.yaml",
            root / "lerna.json",
            root / "nx.json",
            root / "turbo.json",
        ]
        sub_packages = []
        if any(m.exists() for m in monorepo_markers):
            profile.is_monorepo = True
        else:
            # Prüfe ob apps/ oder packages/ Unterordner existieren
            for candidate in ["apps", "packages", "services", "modules"]:
                c_dir = root / candidate
                if c_dir.exists() and c_dir.is_dir():
                    profile.is_monorepo = True
                    for sub in c_dir.iterdir():
                        if sub.is_dir() and not sub.name.startswith("."):
                            sub_packages.append(f"{candidate}/{sub.name}")

        profile.sub_packages = sub_packages

        # 5. Konventionen & Architektur
        if (root / "src").exists():
            conventions.append("Code liegt in src/")
        if (root / "tests").exists() or (root / "test").exists():
            conventions.append("Tests liegen in tests/ bzw. test/")
        if (root / "docs").exists() or (root / "docs" / "adr").exists():
            conventions.append("Dokumentation/ADRs in docs/")
        if (root / "Dockerfile").exists() or (root / "docker-compose.yml").exists():
            conventions.append("Docker/Containerisierung vorhanden")

        # Architektur-Stil Schätzung
        if profile.is_monorepo:
            profile.architecture_style = "Monorepo / Multi-Package"
        elif any("clean" in p.name.lower() or "domain" in p.name.lower() for p in all_relative_paths):
            profile.architecture_style = "Clean Architecture / DDD"
        elif (root / "app").exists() and (root / "app" / "models.py").exists():
            profile.architecture_style = "MVC / Layered Architecture"
        elif any(f in frameworks for f in ["FastAPI", "Express.js", "Spring Boot"]):
            profile.architecture_style = "RESTful Service / API"

        profile.frameworks = sorted(frameworks)
        profile.package_managers = sorted(package_managers)
        profile.test_frameworks = sorted(test_frameworks)
        profile.linters = sorted(linters)
        profile.conventions = conventions

        # 6. Kompakte Zusammenfassung
        parts = []
        if profile.is_brownfield:
            parts.append(f"Bestehendes Projekt ({profile.total_source_files} Quelldateien)")
        else:
            parts.append("Neues / Frisches Projekt")

        if profile.primary_languages:
            parts.append(f"Sprachen: {', '.join(profile.primary_languages)}")
        if profile.frameworks:
            parts.append(f"Frameworks: {', '.join(profile.frameworks)}")
        if profile.package_managers:
            parts.append(f"Paketmanager: {', '.join(profile.package_managers)}")
        if profile.test_frameworks:
            parts.append(f"Tests: {', '.join(profile.test_frameworks)}")

        profile.summary = " | ".join(parts)
        return profile


def format_profile_for_agents(profile: ProjectProfile) -> str:
    """Formatiert das Profil als Markdown-Hinweisblock für System-Prompts."""
    if not profile.is_brownfield and not profile.primary_languages:
        return ""

    lines = [
        "## 🔍 Projekt-Kontext & Erkannte Architektur (Brownfield-Profil)",
        f"- **Status**: {'Bestehende Codebase (Brownfield)' if profile.is_brownfield else 'Neues Projekt'}",
        f"- **Primäre Sprachen**: {', '.join(profile.primary_languages) if profile.primary_languages else 'Automatisch'}",
    ]
    if profile.frameworks:
        lines.append(f"- **Erkannte Frameworks**: {', '.join(profile.frameworks)}")
    if profile.package_managers:
        lines.append(f"- **Paketmanager / Build**: {', '.join(profile.package_managers)}")
    if profile.test_frameworks:
        lines.append(f"- **Test-Infrastruktur**: {', '.join(profile.test_frameworks)}")
    if profile.linters:
        lines.append(f"- **Linters & Formatierer**: {', '.join(profile.linters)}")
    if profile.architecture_style:
        lines.append(f"- **Architektur-Stil**: {profile.architecture_style}")
    if profile.is_monorepo and profile.sub_packages:
        lines.append(f"- **Monorepo-Module**: {', '.join(profile.sub_packages)}")
    if profile.conventions:
        lines.append(f"- **Konventionen**: {', '.join(profile.conventions)}")

    lines.append(
        "\n> ⚠️ **WICHTIG**: Halte dich strikt an die erkannten Konventionen, Paketmanager und Teststrukturen dieses Projekts. "
        "Erfinde keine neuen inkompatiblen Dateistrukturen, sondern füge neue Funktionen nahtlos in den bestehenden Code ein."
    )
    return "\n".join(lines)
