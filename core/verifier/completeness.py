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
    _API_CALL_MARKER_RE,
    _COMPONENT_FILENAME_RE,
    _COMPONENT_TAKES_PROPS_RE,
    _IGNORED_DIRS,
    _IO_CALL_MARKERS,
    _IO_MUTATION_RE,
    _JSX_RETURN_RE,
    _MANIFEST_FILENAMES,
    _PY_IMPORT_RE,
    _PY_ROUTE_DEF_RE,
    _PY_WRITE_ROUTE_DECORATOR_RE,
    _README_FILE_REF_RE,
    _ROUTE_IO_EXEMPT_NAME_RE,
    _STDLIB_MODULES,
    _STUB_MARKER_RE,
    _STUB_SCAN_EXTENSIONS,
    CompletenessIssue,
    CompletenessReport,
)


class CompletenessMixin:
    """Erkennt Platzhalter-/Stub-Code, hartcodierte Fake-Daten statt echter Anbindung und
    fehlende, im README referenzierte oder implizit benötigte Dateien (Dependency-Manifest)."""

    def check_completeness(self) -> CompletenessReport:
        source_files = [
            f for f in self.project_dir.rglob("*")
            if f.is_file() and f.suffix in _STUB_SCAN_EXTENSIONS
            and not any(part in _IGNORED_DIRS for part in f.relative_to(self.project_dir).parts)
        ]
        if not source_files:
            return CompletenessReport(attempted=False, reason_skipped="Keine Quelldateien zum Prüfen gefunden.")

        issues: list[CompletenessIssue] = []
        py_import_names: set[str] = set()
        for f in source_files:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = str(f.relative_to(self.project_dir)).replace("\\", "/")
            issues.extend(self._scan_text_for_stubs(rel, text))
            if f.suffix == ".py":
                issues.extend(self._scan_write_routes_missing_io(rel, text))
                py_import_names.update(self._collect_third_party_imports(text))
            elif f.suffix in (".js", ".jsx", ".ts", ".tsx"):
                issues.extend(self._scan_component_missing_api(rel, text))

        issues.extend(self._missing_readme_referenced_files())
        issues.extend(self._missing_dependency_manifest(py_import_names))

        return CompletenessReport(attempted=True, passed=not issues, issues=issues)

    def _scan_text_for_stubs(self, rel: str, text: str) -> list[CompletenessIssue]:
        found: list[CompletenessIssue] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            match = _STUB_MARKER_RE.search(line)
            if match:
                found.append(CompletenessIssue(
                    file_path=rel, line_number=line_no,
                    message=f"Platzhalter-/Stub-Hinweis im Code: „{line.strip()[:150]}“",
                ))
        return found

    def _scan_write_routes_missing_io(self, rel: str, text: str) -> list[CompletenessIssue]:
        """Findet schreibende Routen-Handler (POST/PUT/PATCH/DELETE) ohne erkennbaren I/O-
        Aufruf im Funktionskörper - real beobachtet bei `list_files()`/`get_tags()`
        (cloudvault), die hartcodierte Literale statt echter Daten lieferten, ohne dass ein
        Stub-Kommentar das verraten hätte."""
        lines = text.splitlines()
        found: list[CompletenessIssue] = []
        for i, line in enumerate(lines):
            if not _PY_WRITE_ROUTE_DECORATOR_RE.search(line):
                continue
            # Weitere Dekoratoren überspringen, dann die eigentliche def-Zeile finden.
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith("@"):
                j += 1
            if j >= len(lines):
                continue
            def_match = _PY_ROUTE_DEF_RE.match(lines[j])
            if not def_match:
                continue
            func_name = def_match.group(1)
            if _ROUTE_IO_EXEMPT_NAME_RE.search(func_name):
                continue
            body: list[str] = []
            k = j + 1
            while k < len(lines) and (lines[k].strip() == "" or lines[k].startswith((" ", "\t"))):
                body.append(lines[k])
                k += 1
            body_joined = "\n".join(body)
            body_text = body_joined.lower()
            has_io = any(marker in body_text for marker in _IO_CALL_MARKERS) or _IO_MUTATION_RE.search(body_joined)
            if body and not has_io:
                found.append(CompletenessIssue(
                    file_path=rel, line_number=j + 1,
                    message=f"Schreibender Routen-Handler „{func_name}“ ohne erkennbaren I/O-"
                            f"Aufruf (DB/Storage/HTTP-Client) - evtl. nur eine Literal-Rückgabe "
                            f"statt echter Persistenz.",
                ))
        return found

    def _scan_component_missing_api(self, rel: str, text: str) -> list[CompletenessIssue]:
        """Findet datenanzeigende React-Komponenten (Dashboard/List/Table/...) ohne Props und
        ohne eigenen API-Aufruf - real beobachtet bei `Dashboard.js` (cloudvault), das
        hartcodierte Fake-Werte statt geladener Daten zeigte."""
        if not _COMPONENT_FILENAME_RE.search(rel):
            return []
        if not _JSX_RETURN_RE.search(text):
            return []
        if _API_CALL_MARKER_RE.search(text):
            return []
        if _COMPONENT_TAKES_PROPS_RE.search(text):
            return []
        return [CompletenessIssue(
            file_path=rel,
            message=f"Komponente „{Path(rel).name}“ nimmt weder Props entgegen noch lädt sie "
                    f"selbst Daten (kein fetch/axios/useEffect) - wirkt an keine echte "
                    f"Datenquelle angebunden, evtl. rein hartcodierte Anzeigedaten.",
        )]

    def _collect_third_party_imports(self, text: str) -> set[str]:
        names: set[str] = set()
        for m in _PY_IMPORT_RE.finditer(text):
            mod = m.group(1)
            if mod not in _STDLIB_MODULES:
                names.add(mod)
        return names

    def _missing_dependency_manifest(self, third_party_imports: set[str]) -> list[CompletenessIssue]:
        """Prüft, ob ein Projekt mit erkennbaren Drittanbieter-Python-Importen (z.B. `fastapi`,
        `pydantic`) überhaupt ein Dependency-Manifest mitliefert - real beobachtet bei
        cloudvault, dessen main.py `fastapi`/`pydantic` importierte, ohne dass je eine
        requirements.txt erzeugt wurde (der bisherige README-Referenz-Check erfasst das nur,
        wenn das README diese Datei überhaupt namentlich erwähnt)."""
        if not third_party_imports:
            return []
        if any((self.project_dir / name).exists() for name in _MANIFEST_FILENAMES):
            return []
        # Lokale, im Projekt selbst definierte Top-Level-Module/-Pakete sind keine
        # Drittanbieter-Abhängigkeiten (z.B. "from app.main import app" -> "app").
        try:
            local_names = {
                p.stem for p in self.project_dir.iterdir() if p.is_file() and p.suffix == ".py"
            } | {
                p.name for p in self.project_dir.iterdir() if p.is_dir() and p.name not in _IGNORED_DIRS
            }
        except OSError:
            local_names = set()
        real_third_party = sorted(third_party_imports - local_names)
        if not real_third_party:
            return []
        return [CompletenessIssue(
            file_path=".",
            message=f"Projekt importiert Drittanbieter-Pakete ({', '.join(real_third_party[:8])}), "
                    f"liefert aber kein Dependency-Manifest (requirements.txt/pyproject.toml/"
                    f"Pipfile) - Installation beim Nutzer schlägt fehl.",
        )]

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
