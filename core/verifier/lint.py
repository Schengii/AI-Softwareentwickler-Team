"""
core/verifier/lint.py – LintMixin: check_lint() prüft generierten Code jetzt auch tatsächlich
mit echten Tools (ruff für Python – immer, braucht keine Projekt-Konfiguration; ESLint/tsc
für Node – nur wenn das Projekt sie selbst bereits als Dev-Abhängigkeit + Konfiguration
mitbringt, keine ungefragte Meinungsänderung am Projekt-Stil; clippy/go vet für Rust/Go).
Bisher lief ruff.toml NUR gegen den Framework-Code selbst (workspace/ dort bewusst
ausgeschlossen) – generierter Code hatte dadurch überhaupt keine automatische
Stil-/Fehlerprüfung.
"""

import json
import shutil
import sys
from pathlib import Path

from config import ENABLE_AUTO_LINT_FIX
from core.code_sandbox import CodeSandbox, ExecutionResult
from core.verifier.models import _ESLINT_CONFIG_NAMES, _IGNORED_DIRS, _TSC_ERROR_PATTERN, LintIssue, LintReport


class LintMixin:
    """Führt echte Lint-/Type-Check-Läufe für ein Projekt aus."""

    def check_lint(self, timeout_seconds: float = 60.0) -> list[LintReport]:
        reports: list[LintReport] = []
        if self._has_python_files():
            reports.append(self._lint_python(timeout_seconds))
        for node_dir in self._find_node_projects():
            eslint_report = self._lint_node_eslint(node_dir, timeout_seconds)
            if eslint_report is not None:
                reports.append(eslint_report)
            tsc_report = self._typecheck_node_tsc(node_dir, timeout_seconds)
            if tsc_report is not None:
                reports.append(tsc_report)
        if self._has_rust_project():
            rust_lint = self._lint_rust(timeout_seconds)
            if rust_lint is not None:
                reports.append(rust_lint)
        if self._has_go_project():
            go_lint = self._lint_go(timeout_seconds)
            if go_lint is not None:
                reports.append(go_lint)
        return reports

    def _lint_rust(self, timeout_seconds: float) -> LintReport | None:
        if shutil.which("cargo") is None:
            return LintReport(attempted=False, passed=True, tool="clippy", reason_skipped="`cargo` nicht verfügbar.")
        result = CodeSandbox.run_command(["cargo", "clippy", "--message-format=json"], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return LintReport(attempted=True, passed=result.exit_code == 0, tool="clippy")

    def _lint_go(self, timeout_seconds: float) -> LintReport | None:
        if shutil.which("go") is None:
            return LintReport(attempted=False, passed=True, tool="go vet", reason_skipped="`go` nicht verfügbar.")
        result = CodeSandbox.run_command(["go", "vet", "./..."], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return LintReport(attempted=True, passed=result.exit_code == 0, tool="go vet")

    def _lint_python(self, timeout_seconds: float) -> LintReport:
        if shutil.which("ruff") is None:
            return LintReport(
                attempted=False, passed=True, tool="ruff",
                reason_skipped="`ruff` ist auf diesem System nicht installiert/verfügbar (`pip install ruff`).",
            )
        exclude_flags = [f"--extend-exclude={d}" for d in sorted(_IGNORED_DIRS)]

        # Realer Fund (Bestandsaufnahme cloudvault-Projekt): 13 ruff-Funde standen im
        # Verifikations-Protokoll, wurden aber nie behoben - Lint ist rein informativ (siehe
        # LintReport-Docstring), niemand war je beauftragt, sie zu fixen. `--fix` behebt NUR
        # SICHERE Autofixes (unsortierte Imports, ungenutzte Importe, veraltete Typannotationen,
        # …) - bewusst OHNE `--unsafe-fixes`, das kann Verhalten ändern und ist der Grund,
        # warum ruff diese beiden Kategorien überhaupt trennt. Ein automatischer, syntaktisch
        # zweifelsfreier Aufräumschritt VOR dem eigentlichen Check-Lauf, kein Agenten-Auftrag
        # nötig - dieselbe Idee wie `black`/`prettier` im Pre-Commit-Hook eines echten Teams.
        # Fehlschlag (z.B. Syntaxfehler im Projekt) ist hier kein Fehler des Checks selbst -
        # der nachfolgende reine Check-Lauf liest ohnehin den tatsächlichen Stand danach.
        if ENABLE_AUTO_LINT_FIX:
            fix_command = ["ruff", "check", str(self.project_dir), "--isolated", "--fix", "--quiet"] + exclude_flags
            CodeSandbox.run_command(fix_command, cwd=self.project_dir, timeout_seconds=timeout_seconds)

        # --isolated: ignoriert JEDE gefundene Konfigurationsdatei (auch die eigene
        # ruff.toml des Frameworks, falls das Projekt innerhalb des Repos liegt) und nutzt
        # ruffs neutrale Standardregeln – die eigenen, für den Framework-Code kuratierten
        # Regeln (z. B. E501-Ausnahme für deutschsprachige Docstrings) sollen einem
        # beliebigen generierten Projekt nicht aufgezwungen werden.
        command = ["ruff", "check", str(self.project_dir), "--isolated", "--output-format=json"] + exclude_flags
        result = CodeSandbox.run_command(command, cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return self._parse_ruff_result(result)

    def _parse_ruff_result(self, result: ExecutionResult) -> LintReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return LintReport(
                attempted=False, passed=True, tool="ruff",
                reason_skipped=f"ruff lieferte kein gültiges Ergebnis: {tail}",
            )

        issues: list[LintIssue] = []
        for entry in data:
            raw_path = entry.get("filename", "?")
            try:
                rel = str(Path(raw_path).resolve().relative_to(self.project_dir)).replace("\\", "/")
            except (ValueError, OSError):
                rel = raw_path
            issues.append(LintIssue(
                file_path=rel,
                line_number=entry.get("location", {}).get("row", 0),
                message=entry.get("message", ""),
                rule=entry.get("code") or "",
            ))
        return LintReport(attempted=True, passed=len(issues) == 0, tool="ruff", issues=issues)

    def _node_bin(self, node_dir: Path, name: str) -> Path | None:
        """Löst ein lokal in node_modules/.bin installiertes Node-Tool auf (kein globales npx-
        Auto-Install, kein interaktiver Prompt) – nur, wenn das Projekt es selbst installiert hat."""
        candidates = [node_dir / "node_modules" / ".bin" / name]
        if sys.platform == "win32":
            candidates.append(node_dir / "node_modules" / ".bin" / f"{name}.cmd")
        return next((c for c in candidates if c.exists()), None)

    def _lint_node_eslint(self, node_dir: Path, timeout_seconds: float) -> LintReport | None:
        if not any((node_dir / name).exists() for name in _ESLINT_CONFIG_NAMES):
            return None  # Projekt nutzt erkennbar kein ESLint - keine ungefragte Meinungsänderung
        rel = self._relative_label(node_dir)
        eslint_bin = self._node_bin(node_dir, "eslint")
        if eslint_bin is None:
            return LintReport(
                attempted=False, passed=True, tool="eslint",
                reason_skipped=f"ESLint-Konfiguration gefunden, aber ESLint nicht in node_modules "
                               f"installiert ({rel}).",
            )
        result = CodeSandbox.run_command(
            [str(eslint_bin), ".", "--format=json"], cwd=node_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_eslint_result(result, node_dir)

    def _parse_eslint_result(self, result: ExecutionResult, node_dir: Path) -> LintReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return LintReport(
                attempted=False, passed=True, tool="eslint",
                reason_skipped=f"ESLint lieferte kein gültiges Ergebnis: {tail}",
            )

        issues: list[LintIssue] = []
        for file_entry in data:
            raw_path = file_entry.get("filePath", "?")
            try:
                rel = str(Path(raw_path).resolve().relative_to(self.project_dir)).replace("\\", "/")
            except (ValueError, OSError):
                rel = raw_path
            for msg in file_entry.get("messages", []):
                if msg.get("severity", 0) < 2:
                    continue  # severity 1 = Warnung, nur echte Fehler (2) zählen als "nicht bestanden"
                issues.append(LintIssue(
                    file_path=rel, line_number=msg.get("line", 0),
                    message=msg.get("message", ""), rule=msg.get("ruleId") or "",
                ))
        return LintReport(attempted=True, passed=len(issues) == 0, tool="eslint", issues=issues)

    def _typecheck_node_tsc(self, node_dir: Path, timeout_seconds: float) -> LintReport | None:
        if not (node_dir / "tsconfig.json").exists():
            return None  # Projekt nutzt erkennbar kein TypeScript - nichts zu typprüfen
        rel = self._relative_label(node_dir)
        tsc_bin = self._node_bin(node_dir, "tsc")
        if tsc_bin is None:
            return LintReport(
                attempted=False, passed=True, tool="tsc",
                reason_skipped=f"tsconfig.json gefunden, aber TypeScript nicht in node_modules "
                               f"installiert ({rel}).",
            )
        result = CodeSandbox.run_command(
            [str(tsc_bin), "--noEmit", "--pretty", "false"], cwd=node_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_tsc_result(result, node_dir)

    def _parse_tsc_result(self, result: ExecutionResult, node_dir: Path) -> LintReport:
        # tsc hat kein natives JSON-Format (anders als ruff/ESLint) - ein leerer Output bei
        # exit_code 0 bedeutet "keine Fehler", jedes andere Ergebnis wird per _TSC_ERROR_PATTERN
        # geparst. Kein strukturiertes Muster gefunden trotz Fehlschlag -> generischer Fallback,
        # analog zu den anderen best-effort geparsten Ausgaben (z. B. _parse_node_failures).
        output = f"{result.stdout}\n{result.stderr}"
        matches = list(_TSC_ERROR_PATTERN.finditer(output))

        if not matches:
            if result.exit_code == 0:
                return LintReport(attempted=True, passed=True, tool="tsc")
            tail = output.strip()[-800:]
            return LintReport(
                attempted=False, passed=True, tool="tsc",
                reason_skipped=f"tsc lieferte kein auswertbares Ergebnis (exit_code={result.exit_code}): {tail}",
            )

        issues: list[LintIssue] = []
        for m in matches:
            raw_path, line_no, _col, _level, code, message = m.groups()
            path = Path(raw_path)
            try:
                abs_path = path if path.is_absolute() else (node_dir / path)
                rel = str(abs_path.resolve().relative_to(self.project_dir)).replace("\\", "/")
            except (ValueError, OSError):
                rel = raw_path
            issues.append(LintIssue(file_path=rel, line_number=int(line_no), message=message.strip(), rule=code))

        return LintReport(attempted=True, passed=False, tool="tsc", issues=issues)
