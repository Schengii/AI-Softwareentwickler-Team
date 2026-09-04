"""
core/code_sandbox.py – Code Execution & Static Validation Sandbox

Bietet dem KI-Team:
- Statische Syntax- und Typprüfungen für Python, JSON, YAML
- Sichere Code-Validierung vor dem Abspeichern
- Ausführung von Test-Befehlen in geschütztem Subprocess mit Timeout
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# run_command() führt vom Modell ausgewählte pip-/npm-/node-Kommandos aus (siehe
# core/agent_toolbox.py). Ohne explizites `env=` erbt subprocess.run() die KOMPLETTE
# Prozessumgebung – inklusive aller in config.py geladenen API-Keys (GEMINI_API_KEY,
# ANTHROPIC_API_KEY, ...). Ein bösartiges (oder kompromittiertes) Paket könnte über ein
# setup.py-/postinstall-Skript versuchen, diese auszulesen. Dieses Muster filtert alles heraus,
# dessen Variablenname nach einem Secret aussieht, BEVOR der Kindprozess gestartet wird.
_SENSITIVE_ENV_NAME_PATTERN = re.compile(r"(key|token|secret|password|credential)", re.IGNORECASE)


@dataclass
class ValidationResult:
    """Ergebnis einer Datei- oder Code-Prüfung."""
    is_valid: bool
    language: str
    errors: list[str]
    warnings: list[str]


@dataclass
class ExecutionResult:
    """Ergebnis eines Test- oder Ausführungs-Laufs."""
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


class CodeSandbox:
    """
    Validiert generierten Code und führt Tests in geschützter Umgebung aus.
    """

    @staticmethod
    def validate_code(code_string: str, file_path_or_ext: str) -> ValidationResult:
        """
        Prüft Code statisch auf Syntax- und Formatierungsfehler.
        """
        ext = file_path_or_ext.lower().split(".")[-1] if "." in file_path_or_ext else file_path_or_ext.lower()
        errors: list[str] = []
        warnings: list[str] = []

        if ext in ("py", "python"):
            try:
                ast.parse(code_string)
            except SyntaxError as e:
                errors.append(f"Python SyntaxError in Zeile {e.lineno}: {e.msg}")
            except Exception as e:
                errors.append(f"Python Parse-Fehler: {str(e)}")

        elif ext in ("json",):
            try:
                json.loads(code_string)
            except json.JSONDecodeError as e:
                errors.append(f"JSON Parse-Fehler in Zeile {e.lineno}, Spalte {e.colno}: {e.msg}")

        elif ext in ("yaml", "yml"):
            # Einfacher YAML-Check ohne harte PyYAML-Abhängigkeit
            lines = code_string.splitlines()
            for i, line in enumerate(lines, 1):
                if "\t" in line and not line.strip().startswith("#"):
                    warnings.append(f"YAML Warnung Zeile {i}: Tabs anstelle von Leerzeichen gefunden.")

        return ValidationResult(
            is_valid=len(errors) == 0,
            language=ext,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _restricted_env() -> dict[str, str]:
        """Prozessumgebung ohne alles, dessen Name nach einem Secret aussieht (siehe oben)."""
        return {k: v for k, v in os.environ.items() if not _SENSITIVE_ENV_NAME_PATTERN.search(k)}

    @staticmethod
    def get_project_venv(project_dir: Path | str | None) -> Path | None:
        """Sucht nach einer existierenden virtuellen Umgebung im Projektverzeichnis."""
        if not project_dir:
            return None
        pdir = Path(project_dir).resolve()
        for venv_name in (".venv", ".ai_team_venv", "venv"):
            candidate = pdir / venv_name
            if candidate.is_dir():
                return candidate
        return None

    @staticmethod
    def ensure_project_venv(project_dir: Path | str, timeout_seconds: float = 60.0) -> tuple[bool, str]:
        """Erstellt eine isolierte virtuelle Umgebung im Projektverzeichnis, falls nicht vorhanden."""
        pdir = Path(project_dir).resolve()
        target_venv = pdir / ".venv"
        if target_venv.exists():
            return True, f"Virtuelle Umgebung existiert bereits: {target_venv}"

        res = CodeSandbox.run_command(
            [sys.executable, "-m", "venv", str(target_venv)],
            cwd=pdir,
            timeout_seconds=timeout_seconds,
            restrict_env=True,
        )
        if res.exit_code == 0:
            return True, f"Virtuelle Umgebung erfolgreich erstellt: {target_venv}"
        return False, f"Fehler beim Erstellen der venv: {res.stderr or res.stdout}"

    @staticmethod
    def run_command(
        command: list[str],
        cwd: Path | str | None = None,
        timeout_seconds: float = 30.0,
        restrict_env: bool = True,
    ) -> ExecutionResult:
        """
        Führt ein Terminal-Kommando (z. B. pytest oder python -m unittest) sicher aus.

        Priorisiert automatisch projekt-lokale virtuelle Umgebungen (.venv, .ai_team_venv),
        sodass pip-Installationen und Testläufe das Host-System nicht verunreinigen.
        """
        import time

        env = CodeSandbox._restricted_env() if restrict_env else os.environ.copy()
        venv_path = CodeSandbox.get_project_venv(cwd)

        # Falls ein lokales .venv existiert: PATH prependen und VIRTUAL_ENV setzen
        if venv_path and cwd:
            scripts_dir = venv_path / ("Scripts" if sys.platform == "win32" else "bin")
            if scripts_dir.exists():
                existing_path = env.get("PATH", "")
                env["PATH"] = f"{scripts_dir}{os.pathsep}{existing_path}"
                env["VIRTUAL_ENV"] = str(venv_path)

        if cwd:
            cwd_str = str(Path(cwd).resolve())
            existing_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{cwd_str}{os.pathsep}{existing_pp}" if existing_pp else cwd_str

        # Befehls-Auflösung: Prüfe zuerst, ob der Befehl in scripts_dir des Projekt-Venvs existiert
        resolved_bin = None
        if command:
            cmd_name = command[0]
            if venv_path:
                scripts_dir = venv_path / ("Scripts" if sys.platform == "win32" else "bin")
                candidates = [scripts_dir / cmd_name]
                if sys.platform == "win32":
                    candidates.extend([scripts_dir / f"{cmd_name}.exe", scripts_dir / f"{cmd_name}.cmd", scripts_dir / f"{cmd_name}.bat"])
                for cand in candidates:
                    if cand.is_file():
                        resolved_bin = str(cand)
                        break

            if not resolved_bin:
                resolved_bin = shutil.which(cmd_name) or cmd_name

        resolved_command = [resolved_bin, *command[1:]] if command and resolved_bin else command
        start_time = time.monotonic()


        try:
            process = subprocess.run(
                resolved_command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,
                env=env,
            )
            duration = time.monotonic() - start_time
            return ExecutionResult(
                exit_code=process.returncode,
                stdout=process.stdout,
                stderr=process.stderr,
                duration_seconds=duration,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as e:
            duration = time.monotonic() - start_time
            return ExecutionResult(
                exit_code=-1,
                stdout=e.stdout or "",
                stderr=f"Timeout nach {timeout_seconds} Sekunden überschritten.",
                duration_seconds=duration,
                timed_out=True,
            )
        except Exception as e:
            duration = time.monotonic() - start_time
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Fehler bei Befehlsausführung: {str(e)}",
                duration_seconds=duration,
                timed_out=False,
            )
