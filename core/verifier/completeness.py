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

Fünfter realer Fund (taskpulse-Projekt, 2026-09-03): `app/main.py` enthielt `from . import
database, models, schemas`, aber `app/models.py` wurde nie angelegt - die App konnte dadurch
gar nicht importiert werden. Der Fund blieb 33 Agenten-Durchläufe (714k Tokens, 23 Minuten) lang
ungelöst, weil KEIN bisheriger Check das prüft: Lint/SAST/Coverage laufen gegen vorhandene
Dateien, die echte Testsuite bricht zwar mit ImportError ab, aber ihr Traceback zeigt oft nur
die importierende Datei (main.py), nicht die fehlende (models.py) - der gezielte Fix-Loop
(agents/orchestrator/verification.py._run_verification_loop) beauftragte deshalb wiederholt den
falschen bzw. einen zu vage instruierten Agenten. _missing_local_python_imports() prüft JEDEN
lokalen Python-Import direkt statisch gegen das Dateisystem, unabhängig davon, ob die Testsuite
je läuft - dieselbe Kategorie wie die fehlende requirements.txt oben, nur für Code-interne statt
externe Referenzen.
"""

import ast
from pathlib import Path

from core.verifier.models import (
    _API_CALL_MARKER_RE,
    _COMPONENT_FILENAME_RE,
    _COMPONENT_TAKES_PROPS_RE,
    _IGNORED_DIRS,
    _IO_CALL_MARKERS,
    _IO_MUTATION_RE,
    _JS_IO_CALL_MARKERS,
    _JS_IO_MUTATION_RE,
    _JS_MODULE_EXTENSIONS,
    _JS_RELATIVE_DYNAMIC_IMPORT_RE,
    _JS_RELATIVE_ES_IMPORT_RE,
    _JS_RELATIVE_REQUIRE_RE,
    _JS_WRITE_ROUTE_CALL_RE,
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
        py_files = [f for f in source_files if f.suffix == ".py"]
        local_top_level = self._local_top_level_names() if py_files else set()
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
                issues.extend(self._missing_local_python_imports(rel, f, text, local_top_level))
            elif f.suffix in (".js", ".jsx", ".ts", ".tsx"):
                issues.extend(self._scan_component_missing_api(rel, text))
                issues.extend(self._missing_local_js_imports(rel, f, text))
                issues.extend(self._scan_js_write_routes_missing_io(rel, text))

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

    def _missing_local_js_imports(self, rel: str, file: Path, text: str) -> list[CompletenessIssue]:
        """JS/TS-Pendant zu _missing_local_python_imports(): prüft relative Importe
        (`import ... from './x'`, `export ... from './x'`, `import('./x')`, `require('./x')`)
        gegen das Dateisystem. Bewusst NUR relative Pfade (beginnend mit "." oder "/") - ein
        npm-Paket-Import ("from 'react'") wird nie geprüft, da dieser Check keine
        node_modules-Auflösung/package.json-Analyse betreibt (siehe _JS_RELATIVE_ES_IMPORT_RE-
        Docstring in core/verifier/models.py für die vollständige Abgrenzung)."""
        specifiers = {
            m.group(1) for pattern in (
                _JS_RELATIVE_ES_IMPORT_RE, _JS_RELATIVE_REQUIRE_RE, _JS_RELATIVE_DYNAMIC_IMPORT_RE,
            )
            for m in pattern.finditer(text)
        }
        issues: list[CompletenessIssue] = []
        for spec in sorted(specifiers):
            candidate = file.parent / spec
            if self._js_module_resolves(candidate):
                continue
            issues.append(CompletenessIssue(
                file_path=rel,
                message=f"Relativer Import „{spec}“ verweist auf keine existierende JS/TS-Datei "
                        f"(geprüft: `{self._relative_or_raw(candidate)}"
                        f"{{{','.join(_JS_MODULE_EXTENSIONS)}}}` bzw. "
                        f"`{self._relative_or_raw(candidate)}/index{{{','.join(_JS_MODULE_EXTENSIONS)}}}`) "
                        f"- der Import schlägt beim Bundling/Ausführen fehl.",
            ))
        return issues

    def _scan_js_write_routes_missing_io(self, rel: str, text: str) -> list[CompletenessIssue]:
        """JS/TS-Pendant zu _scan_write_routes_missing_io() (Python, siehe oben): findet
        schreibende Express/Fastify/Koa-artige Routen-Registrierungen (`app.post(...)`/
        `router.put(...)`/...) MIT INLINE-Handler-Funktion, deren Body keinen erkennbaren
        I/O-Aufruf enthält (DB/Storage/HTTP-Client) - derselbe cloudvault-Fund wie bei Python
        (`return []`/hartcodierte Literale statt echter Persistenz), nur im Node-Backend.

        Bewusst NUR Inline-Handler geprüft: `app.post('/x', createUser)` referenziert eine
        BENANNTE Funktion, deren Body nicht am Fundort steht - eine echte Prüfung bräuchte
        eine zweite Suche nach `function createUser` bzw. `const createUser =` an anderer
        Stelle der Datei, was das Risiko von Fehlzuordnungen deutlich erhöht. Erkennungsregel:
        endet die Registrierung (Semikolon) VOR der nächsten `{`, ist es kein Inline-Handler -
        wird übersprungen statt geraten (dieselbe konservative Grundhaltung wie überall in
        dieser Datei: eine übersehene fehlende I/O-Anbindung ist besser als ein Fehlalarm).

        Endpunkte, deren Pfad eines der exempt-Schlüsselwörter enthält (health/ping/version/
        logout/status, siehe _ROUTE_IO_EXEMPT_NAME_RE), werden wie beim Python-Pendant
        ausgenommen - JS-Handler sind in dieser Konvention oft anonyme Arrow-Functions ohne
        eigenen Funktionsnamen, deshalb wird hier der Routen-PFAD statt eines Funktionsnamens
        geprüft."""
        issues: list[CompletenessIssue] = []
        for m in _JS_WRITE_ROUTE_CALL_RE.finditer(text):
            route_path = m.group(2)
            if _ROUTE_IO_EXEMPT_NAME_RE.search(route_path):
                continue

            semi_idx = text.find(";", m.end())
            brace_idx = text.find("{", m.end())
            if brace_idx == -1 or (semi_idx != -1 and semi_idx < brace_idx):
                continue  # kein Inline-Handler an dieser Stelle - siehe Docstring

            close_idx = self._find_matching_js_brace(text, brace_idx)
            if close_idx is None:
                continue  # unausgewogene Klammern (z.B. String mit "{" drin) - nicht sicher prüfbar
            body = text[brace_idx:close_idx + 1]

            has_io = any(marker in body for marker in _JS_IO_CALL_MARKERS) or _JS_IO_MUTATION_RE.search(body)
            if not has_io:
                line_no = text.count("\n", 0, m.start()) + 1
                issues.append(CompletenessIssue(
                    file_path=rel, line_number=line_no,
                    message=f"Schreibender Routen-Handler „{route_path}“ ohne erkennbaren I/O-"
                            f"Aufruf (DB/Storage/HTTP-Client) - evtl. nur eine Literal-Rückgabe "
                            f"statt echter Persistenz.",
                ))
        return issues

    def _find_matching_js_brace(self, text: str, open_idx: int) -> int | None:
        """Findet die zu `text[open_idx]` (muss "{" sein) passende schließende Klammer per
        einfacher Tiefenzählung - bewusst kein echter JS-Parser (String-/Kommentar-Inhalte mit
        "{"/"}" können die Zählung verfälschen), aber für die kurzen, unverschachtelten
        Route-Handler-Bodies dieses Checks ausreichend robust; ein Fehlschlag (None) führt nur
        dazu, dass DIESER eine Fund übersprungen wird, kein Crash."""
        depth = 0
        for i in range(open_idx, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        return None

    def _js_module_resolves(self, candidate: Path) -> bool:
        """Node/Bundler-typische Modulauflösung, best-effort: exakter Pfad (falls der Import
        bereits eine Endung trägt), sonst `<pfad>.<ext>` für jede _JS_MODULE_EXTENSIONS-Endung,
        sonst `<pfad>/index.<ext>` (Verzeichnis-Import) - dieselbe Reihenfolge, in der Node/
        Bundler ein extensionsloses Modul auflösen. Ein Import mit einer NICHT-JS-Endung (z.B.
        `.css`, `.svg`, `.json`) gilt IMMER als aufgelöst (siehe _JS_MODULE_EXTENSIONS-Docstring
        - Bundler-Loader-abhängig, nicht zuverlässig ohne Bundler-Konfiguration prüfbar)."""
        if candidate.suffix:
            if candidate.suffix not in _JS_MODULE_EXTENSIONS:
                return True
            return candidate.exists()
        if any(candidate.with_suffix(ext).exists() for ext in _JS_MODULE_EXTENSIONS):
            return True
        return any((candidate / f"index{ext}").exists() for ext in _JS_MODULE_EXTENSIONS)

    def _collect_third_party_imports(self, text: str) -> set[str]:
        names: set[str] = set()
        for m in _PY_IMPORT_RE.finditer(text):
            mod = m.group(1)
            if mod not in _STDLIB_MODULES:
                names.add(mod)
        return names

    def _local_top_level_names(self) -> set[str]:
        """Namen der im Projekt selbst definierten Top-Level-Python-Module/-Pakete (z.B. "app"
        für ein Projekt mit app/main.py) - dieselbe Bestimmung wie in
        _missing_dependency_manifest(), hier als eigene Methode, weil auch
        _missing_local_python_imports() sie braucht, um ABSOLUTE lokale Importe (`from app
        import models`, im Gegensatz zu relativen `from . import models`) von echten
        Drittanbieter-Paketen zu unterscheiden."""
        try:
            return {
                p.stem for p in self.project_dir.iterdir() if p.is_file() and p.suffix == ".py"
            } | {
                p.name for p in self.project_dir.iterdir() if p.is_dir() and p.name not in _IGNORED_DIRS
            }
        except OSError:
            return set()

    def _local_module_exists(self, module_path: Path) -> bool:
        """Prüft, ob `module_path` (ohne Endung) als Python-Modul (`<pfad>.py`) oder als Paket
        (`<pfad>/__init__.py` ODER ein reines Namespace-Package-Verzeichnis ohne __init__.py,
        PEP 420) existiert."""
        return module_path.with_suffix(".py").exists() or module_path.is_dir()

    def _missing_local_python_imports(
        self, rel: str, file: Path, text: str, local_top_level: set[str],
    ) -> list[CompletenessIssue]:
        """Prüft JEDEN lokalen Python-Import statisch gegen das Dateisystem - unabhängig davon,
        ob/wann die echte Testsuite läuft und ob ihr Traceback die tatsächlich fehlende Datei
        überhaupt nennt (siehe Docstring oben, taskpulse-Fund: `from . import database, models,
        schemas` bei fehlender `models.py`). Nutzt `ast.parse()` statt Regex für die
        Import-Extraktion (anders als die übrigen, bewusst regex-basierten Checks in dieser
        Datei) - Import-Syntax hat zu viele Formen (Mehrfach-Importe, `as`-Aliase, verschachtelte
        Klammern), um sie robust per Regex zu erfassen, und `ast.parse()` ist für eine einzelne
        Quelldatei günstig genug, um sie für jede .py-Datei im Projekt aufzurufen. Best-effort
        wie der Rest dieser Datei: ein SyntaxError-Fund (kaputte Datei) wird hier NICHT erneut
        gemeldet - das übernimmt bereits ein separater Check (Testsuite/Lint), doppelte Meldung
        wäre nur Rauschen.
        """
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return []

        issues: list[CompletenessIssue] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level >= 1:
                    # Relativer Import ("from . import X" / "from .core.config import Y") -
                    # level=1 ist das Paket der aktuellen Datei selbst, jede weitere Ebene geht
                    # ein Verzeichnis höher (PEP 328-Semantik).
                    base = file.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    issues.extend(self._check_import_from(node, base, rel))
                elif node.module and node.module.split(".")[0] in local_top_level:
                    # Absoluter Import eines projekteigenen Top-Level-Pakets ("from app import
                    # models") - nur geprüft, wenn der Name bereits als lokales Modul/Paket
                    # bekannt ist (siehe local_top_level), sonst wäre jeder normale
                    # Drittanbieter-Import ("from fastapi import ...") ein Fehlalarm.
                    issues.extend(self._check_import_from(node, self.project_dir, rel))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in local_top_level:
                        continue
                    module_path = self.project_dir / Path(*alias.name.split("."))
                    if not self._local_module_exists(module_path):
                        issues.append(CompletenessIssue(
                            file_path=rel, line_number=node.lineno,
                            message=f"Import „import {alias.name}“ verweist auf ein nicht "
                                    f"existierendes lokales Modul (`{alias.name.replace('.', '/')}"
                                    f".py`) - der Import schlägt beim Start fehl.",
                        ))
        return issues

    def _check_import_from(self, node: ast.ImportFrom, base: Path, rel: str) -> list[CompletenessIssue]:
        """Prüft eine einzelne `from <base+module> import <names>`-Anweisung: zuerst, ob das
        Zwischenmodul selbst existiert (z.B. `core.config` in `from .core.config import
        settings`) - fehlt es komplett, ist das der einzige Fund. Existiert es als PAKET
        (Verzeichnis, z.B. `app` in `from app import models` oder das implizite Basisverzeichnis
        bei `from . import models`), prüft _check_ambiguous_names() zusätzlich jeden importierten
        Namen einzeln, weil er dort entweder ein Submodul (models.py) oder ein in __init__.py
        (re-)exportiertes Symbol sein könnte. Löst sich `module_path` dagegen zu einer einzelnen
        .py-DATEI auf (kein Paket), bleiben die importierten Namen unbeprüft - eine
        verlässliche Symbol-in-Datei-Prüfung bräuchte eine zweite AST-Analyse dieser Datei und
        wäre wegen dynamischer Attribute/Re-Exporte fehlalarmanfällig."""
        dotted = "." * node.level + (node.module or "")
        if node.module:
            module_path = base / Path(*node.module.split("."))
            if not self._local_module_exists(module_path):
                return [CompletenessIssue(
                    file_path=rel, line_number=node.lineno,
                    message=f"Import „from {dotted} import ...“ verweist auf ein nicht "
                            f"existierendes lokales Modul/Paket "
                            f"(`{self._relative_or_raw(module_path)}.py`) - der Import schlägt "
                            f"beim Start fehl.",
                )]
            if not module_path.is_dir():
                return []  # einzelne .py-Datei, keine Namens-Ambiguität - siehe Docstring
            base = module_path

        return self._check_ambiguous_names(node, base, dotted, rel)

    def _check_ambiguous_names(self, node: ast.ImportFrom, base: Path, dotted: str, rel: str) -> list[CompletenessIssue]:
        """Prüft jeden importierten Namen bei "from <paket> import X, Y, Z" einzeln: X/Y/Z
        KÖNNTEN Submodule sein (dann muss z.B. models.py existieren) ODER ganz normale, in
        `__init__.py` (re-)exportierte Symbole (Funktionen/Variablen/Klassen) - letzteres ist
        KEIN Fehler. Bewusst konservativ: nur melden, wenn der Name im Verzeichnis WEDER als
        Submodul existiert NOCH (falls ein __init__.py vorhanden ist) dort textuell auftaucht -
        dieselbe tolerante, auf Vermeidung von Fehlalarmen bedachte Haltung wie beim
        Stub-Marker-Scan."""
        init_file = base / "__init__.py"
        init_text = ""
        if init_file.exists():
            try:
                init_text = init_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
        issues: list[CompletenessIssue] = []
        for alias in node.names:
            if alias.name == "*":
                continue
            if self._local_module_exists(base / alias.name):
                continue
            if init_text and alias.name in init_text:
                continue
            issues.append(CompletenessIssue(
                file_path=rel, line_number=node.lineno,
                message=f"Import „from {dotted} import {alias.name}“ verweist auf kein "
                        f"existierendes lokales Submodul (`{self._relative_or_raw(base / alias.name)}.py`) "
                        f"und wird auch nicht in `{self._relative_or_raw(init_file)}` (re-)exportiert - "
                        f"der Import schlägt vermutlich beim Start fehl.",
            ))
        return issues

    def _relative_or_raw(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.project_dir)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

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
