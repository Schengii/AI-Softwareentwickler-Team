"""
core/verifier/completeness.py – CompletenessMixin: check_completeness() erkennt unfertigen
Code, der eine echte Testsuite trotzdem besteht - "Tests grün" heißt nicht "Feature fertig".

Realer Fund (Bestandsaufnahme cloudvault-Projekt, siehe CompletenessReport-Docstring): ein
Datei-Upload-Endpunkt mit dem Kommentar "Hier würde die AES-256-GCM Verschlüsselung ...
erfolgen" bestand die Verifikation als "✅ Vollständig verifiziert & einsatzbereit", weil die
zugehörigen Tests denselben Stub prüften, den der Code tatsächlich liefert - keiner der
bisherigen Checks (Testsuite, Lint, SAST, Coverage) erkennt einen absichtlich unfertig
gelassenen Codepfad, nur einen tatsächlich FALSCHEN. Zusätzlich verwies das README-generierte
`pip install -r requirements.txt` auf eine Datei, die nie erzeugt wurde - ebenfalls von keinem
bisherigen Check erfasst.
"""

from pathlib import Path

from core.verifier.models import (
    _IGNORED_DIRS,
    _README_FILE_REF_RE,
    _STUB_MARKER_RE,
    _STUB_SCAN_EXTENSIONS,
    CompletenessIssue,
    CompletenessReport,
)


class CompletenessMixin:
    """Erkennt Platzhalter-/Stub-Code und fehlende, im README referenzierte Dateien."""

    def check_completeness(self) -> CompletenessReport:
        source_files = [
            f for f in self.project_dir.rglob("*")
            if f.is_file() and f.suffix in _STUB_SCAN_EXTENSIONS
            and not any(part in _IGNORED_DIRS for part in f.relative_to(self.project_dir).parts)
        ]
        if not source_files:
            return CompletenessReport(attempted=False, reason_skipped="Keine Quelldateien zum Prüfen gefunden.")

        issues: list[CompletenessIssue] = [
            issue for f in source_files for issue in self._scan_file_for_stubs(f)
        ]
        issues.extend(self._missing_readme_referenced_files())

        return CompletenessReport(attempted=True, passed=not issues, issues=issues)

    def _scan_file_for_stubs(self, path: Path) -> list[CompletenessIssue]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []
        rel = str(path.relative_to(self.project_dir)).replace("\\", "/")
        found: list[CompletenessIssue] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            match = _STUB_MARKER_RE.search(line)
            if match:
                found.append(CompletenessIssue(
                    file_path=rel, line_number=line_no,
                    message=f"Platzhalter-/Stub-Hinweis im Code: „{line.strip()[:150]}“",
                ))
        return found

    def _missing_readme_referenced_files(self) -> list[CompletenessIssue]:
        readme = next(
            (self.project_dir / name for name in ("README.md", "readme.md") if (self.project_dir / name).exists()),
            None,
        )
        if readme is None:
            return []
        try:
            text = readme.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []

        missing: list[CompletenessIssue] = []
        seen: set[str] = set()
        for match in _README_FILE_REF_RE.finditer(text):
            ref = match.group(1).strip()
            if ref in seen:
                continue
            seen.add(ref)
            if not (self.project_dir / ref).exists():
                missing.append(CompletenessIssue(
                    file_path="README.md",
                    message=f"README referenziert `{ref}` (z.B. per `pip install -r`/`-f`), "
                            f"aber die Datei existiert im Projekt nicht.",
                ))
        return missing
