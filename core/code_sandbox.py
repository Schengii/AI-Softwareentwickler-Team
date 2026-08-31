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
    def run_command(
        command: list[str],
        cwd: Path | str | None = None,
        timeout_seconds: float = 30.0,
        restrict_env: bool = True,
    ) -> ExecutionResult:
        """
        Führt ein Terminal-Kommando (z. B. pytest oder python -m unittest) sicher aus.

        restrict_env=True (Standard): der Kindprozess bekommt NICHT die volle Prozessumgebung
        dieses Frameworks (siehe _restricted_env()) – keiner der bisherigen Aufrufer (Tests,
        pip/venv-Installation, npm/node) braucht echte API-Keys, um zu funktionieren. Nur für
        einen bewussten Sonderfall auf False setzen, der die volle Umgebung wirklich benötigt.

        Realer Fund: `npm`/`npx`/`yarn` & Co. sind unter Windows keine echten .exe, sondern
        .cmd-Batch-Wrapper – `subprocess.run(["npm", ...], shell=False)` scheitert dort IMMER
        mit `WinError 2` (Datei nicht gefunden), selbst wenn `npm` im PATH steht, weil
        CreateProcess ohne Shell keine .cmd/.bat-Dateien direkt ausführen kann. Löst command[0]
        deshalb vorab über shutil.which() auf DEN TATSÄCHLICHEN, vollständigen Pfad (inkl.
        Endung) auf – unter Linux/macOS bereits ein regulärer Pfad zur echten Binärdatei, daher
        ein no-op. Kein Treffer (Kommando existiert schlicht nicht) fällt auf den rohen Namen
        zurück, damit die Fehlermeldung weiterhin "Datei nicht gefunden" statt eines stillen
        Verhaltensunterschieds bleibt.
        """
        import time
        # Bugfix (Ultrareview-Fund): vorher ein Nested-Ternary mit unerreichbarem "else None"-Zweig
        # (im äußeren else ist restrict_env bereits False, also war "if not restrict_env" dort
        # immer True) - das täuschte einen nie eintretenden env=None-Fallback vor. Vor diesem PR
        # wurde bei restrict_env=False bewusst env=None übergeben (natürliche Vererbung der
        # Elternumgebung); jetzt wird IMMER ein echtes dict gebaut, damit der PYTHONPATH-Prefix
        # unten in beiden Modi greift.
        env = CodeSandbox._restricted_env() if restrict_env else os.environ.copy()
        if cwd:
            cwd_str = str(Path(cwd).resolve())
            existing_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{cwd_str}{os.pathsep}{existing_pp}" if existing_pp else cwd_str
        resolved_command = [shutil.which(command[0]) or command[0], *command[1:]] if command else command
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
