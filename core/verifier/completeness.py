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
import re
from pathlib import Path

from core.verifier.models import (
    _API_CALL_MARKER_RE,
    _COMPONENT_FILENAME_RE,
    _COMPONENT_TAKES_PROPS_RE,
    _IGNORED_DIRS,
    _IMPORT_TO_PACKAGE_NAME,
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
    _KNOWN_PACKAGE_NAMES,
    _LOCAL_DIR_THIRDPARTY_NAME_COLLISIONS,
    _MANIFEST_FILENAMES,
    _PY_IMPORT_RE,
    _PY_ROUTE_DEF_RE,
    _PY_WRITE_ROUTE_DECORATOR_RE,
    _PYTEST_ASYNC_TEST_RE,
    _README_FILE_REF_RE,
    _ROUTE_IO_EXEMPT_NAME_RE,
    _SQLA_ASYNC_ENGINE_RE,
    _SQLA_DECLARATIVE_BASE_RE,
    _SQLA_SYNC_ENGINE_RE,
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
        py_texts: dict[str, str] = {}
        has_async_pytest_marks = False
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
                py_texts[rel] = text
                if _PYTEST_ASYNC_TEST_RE.search(text):
                    has_async_pytest_marks = True
            elif f.suffix in (".js", ".jsx", ".ts", ".tsx"):
                issues.extend(self._scan_component_missing_api(rel, text))
                issues.extend(self._missing_local_js_imports(rel, f, text))
                issues.extend(self._scan_js_write_routes_missing_io(rel, text))

        issues.extend(self._missing_readme_referenced_files())
        issues.extend(self._missing_dependency_manifest(py_import_names))
        issues.extend(self._corrupted_dependency_manifests())
        real_third_party = py_import_names - local_top_level
        issues.extend(self._missing_known_packages_in_manifest(real_third_party))
        if has_async_pytest_marks:
            issues.extend(self._missing_async_test_dependencies())
        issues.extend(self._conflicting_sqlalchemy_config(py_texts))
        issues.extend(self._double_router_prefix(py_texts))

        return CompletenessReport(attempted=True, passed=not issues, issues=issues)

    def _corrupted_dependency_manifests(self) -> list[CompletenessIssue]:
        """Prüft vorhandene Dependency-Manifeste (requirements.txt, package.json, ...) auf
        Merge-/Diff-Korruption – siehe core/manifest_guard.py für den realen Fund. Ergänzt die
        Schreibzeit-Prüfung in core/agent_toolbox.py/core/workspace.py als zweite
        Verteidigungslinie: erkennt auch Korruption, die auf einem anderen Weg (z.B. manuelles
        Kopieren, ältere Läufe vor dieser Prüfung) ins Projekt gelangt ist."""
        from core.manifest_guard import _JSON_MANIFESTS, _PYTHON_REQUIREMENTS_MANIFESTS, detect_corrupted_manifest

        issues: list[CompletenessIssue] = []
        for name in _PYTHON_REQUIREMENTS_MANIFESTS | _JSON_MANIFESTS:
            candidate = self.project_dir / name
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            message = detect_corrupted_manifest(name, text)
            if message:
                issues.append(CompletenessIssue(file_path=name, message=message))
        return issues

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
                p.name for p in self.project_dir.iterdir()
                if p.is_dir() and p.name not in _IGNORED_DIRS
                and p.name not in _LOCAL_DIR_THIRDPARTY_NAME_COLLISIONS
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
        .py-DATEI auf (kein Paket), prüft _check_symbols_in_module_file() konservativ, ob jeder
        importierte Name dort tatsächlich definiert/re-exportiert wird (siehe dort für die
        Fehlalarm-Vorkehrungen)."""
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
                return self._check_symbols_in_module_file(node, module_path.with_suffix(".py"), dotted, rel)
            base = module_path

        return self._check_ambiguous_names(node, base, dotted, rel)

    def _check_symbols_in_module_file(
        self, node: ast.ImportFrom, module_file: Path, dotted: str, rel: str,
    ) -> list[CompletenessIssue]:
        """
        Team-Optimierung (Retrospektive 2026-09-04, sechster realer Fund): `_check_import_from()`
        ließ ein Zielmodul, das sich zu einer einzelnen .py-DATEI auflöst, bisher komplett
        unbeprüft (siehe dortiger Docstring) - real beobachtet an `zeiterfassung_app`: `app/
        main.py` importierte `from .middleware.rate_limit import RateLimitMiddleware`, aber die
        Klasse in `app/middleware/rate_limit.py` hieß tatsächlich `SimpleRateLimiter` - ein
        garantierter `ImportError` beim Start. Weder die Testsuite (blieb aus anderen Gründen
        bereits rot, siehe MAX_VERIFICATION_ITERATIONS) noch dieser Check bisher fingen das ab -
        erst ein SPÄTERER Governance-Review-Lauf per Code-Lesen fand es, einen ganzen Lauf
        später als nötig.

        Bewusst konservativ (dieselbe Fehlalarm-Vorsicht wie _check_ambiguous_names()): meldet
        NUR, wenn
        - die Zieldatei syntaktisch parsbar ist (ein SyntaxError wird bereits vom Testlauf/Lint
          gemeldet, keine doppelte Meldung hier),
        - sie KEINEN Wildcard-Import (`from x import *`) und KEINE dynamische Namens-Erzeugung
          (`globals()[...] = `, `setattr(sys.modules[...], ...)`, `__getattr__`) enthält - beides
          kann Namen zur Laufzeit erzeugen, die eine rein statische AST-Analyse nie sehen kann,
        und der importierte Name dort weder als Funktion/Klasse/Variable/Alias auf Modulebene
        NOCH via `__all__` auftaucht.
        """
        try:
            text = module_file.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text)
        except (OSError, SyntaxError, ValueError):
            return []

        defined: set[str] = set()
        has_dynamic_names = False
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(stmt.name)
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        defined.add(target.id)
                    elif isinstance(target, ast.Tuple):
                        defined.update(elt.id for elt in target.elts if isinstance(elt, ast.Name))
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                defined.add(stmt.target.id)
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                if isinstance(stmt, ast.ImportFrom) and any(a.name == "*" for a in stmt.names):
                    has_dynamic_names = True  # Wildcard-Import kann beliebige Namen einführen
                    break
                for alias in stmt.names:
                    defined.add((alias.asname or alias.name).split(".")[0])
        if has_dynamic_names:
            return []
        # Modulweite dynamische Namens-Erzeugung außerhalb von Top-Level-Statements (z.B. in
        # einem `if`-Block oder per globals()/setattr) - grob per Volltextsuche statt vollem
        # Kontrollfluss-Tracking, bewusst lieber einen echten Fund verpassen als einen
        # Fehlalarm riskieren.
        if "__getattr__" in text or "globals()[" in text or "setattr(sys.modules" in text:
            return []

        issues: list[CompletenessIssue] = []
        for alias in node.names:
            if alias.name == "*" or alias.name in defined:
                continue
            issues.append(CompletenessIssue(
                file_path=rel, line_number=node.lineno,
                message=f"Import „from {dotted} import {alias.name}“ verweist auf kein "
                        f"in `{self._relative_or_raw(module_file)}` definiertes/importiertes "
                        f"Symbol - der Import schlägt vermutlich beim Start mit ImportError fehl "
                        f"(Namens-Tippfehler oder die Datei wurde umbenannt, ohne alle "
                        f"Importstellen anzupassen?).",
            ))
        return issues

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

    def _read_manifest_texts(self) -> str:
        """Liest den kombinierten Inhalt aller vorhandenen Python-Dependency-Manifeste roh als
        einen Textblock (kleingeschrieben, "_" durch "-" normalisiert) - Grundlage für die
        einfache Token-Prüfung in _missing_known_packages_in_manifest()/
        _missing_async_test_dependencies() unten. Bewusst kein echter TOML-/Requirements-Parser
        (dieselbe konservative Grundhaltung wie der Rest dieser Datei) - reicht, um zu prüfen,
        ob ein Paketname überhaupt irgendwo im Manifest auftaucht."""
        names = ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile")
        chunks: list[str] = []
        for name in names:
            candidate = self.project_dir / name
            if candidate.exists() and candidate.is_file():
                try:
                    chunks.append(candidate.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    pass
        return "\n".join(chunks).lower().replace("_", "-")

    def _manifest_has_package(self, manifest_text: str, package_name: str) -> bool:
        token_re = re.compile(rf"(?<![a-z0-9.-]){re.escape(package_name)}(?![a-z0-9.-])")
        return bool(token_re.search(manifest_text))

    def _missing_known_packages_in_manifest(self, third_party_imports: set[str]) -> list[CompletenessIssue]:
        """Siebter realer Fund (siehe _IMPORT_TO_PACKAGE_NAME-Docstring in
        core/verifier/models.py, logpulse-Projekt): _missing_dependency_manifest() oben prüft
        nur, ob IRGENDEIN Manifest existiert - nicht, ob es die tatsächlich importierten Pakete
        auch auflistet. Prüft deshalb zusätzlich, für eine kuratierte Allowlist bekannter,
        eindeutiger Pakete (_KNOWN_PACKAGE_NAMES), ob der jeweilige Paketname im Manifest-Text
        auftaucht. Läuft NUR, wenn überhaupt ein Manifest existiert - fehlt es komplett, meldet
        das bereits _missing_dependency_manifest(), eine zweite Meldung wäre nur Rauschen."""
        manifest_text = self._read_manifest_texts()
        if not manifest_text:
            return []
        issues: list[CompletenessIssue] = []
        for import_name in sorted(third_party_imports):
            package_name = _IMPORT_TO_PACKAGE_NAME.get(import_name, import_name.replace("_", "-"))
            if package_name not in _KNOWN_PACKAGE_NAMES:
                continue
            if self._manifest_has_package(manifest_text, package_name):
                continue
            issues.append(CompletenessIssue(
                file_path=".",
                message=f"Projekt importiert `{import_name}` (erwartetes PyPI-Paket "
                        f"`{package_name}`), aber kein Dependency-Manifest listet es auf - "
                        f"`pip install` installiert die tatsächlich benötigten Pakete dann "
                        f"unvollständig, ein Import-/Testlauf schlägt fehl.",
            ))
        return issues

    def _missing_async_test_dependencies(self) -> list[CompletenessIssue]:
        """Zweiter Teil desselben logpulse-Funds: Testdateien nutzten `@pytest.mark.asyncio`,
        aber weder `pytest-asyncio` noch `anyio` waren im Manifest gelistet - jeder so markierte
        Test bricht dann mit einem Fixture-/Marker-Fehler ab, unabhängig vom eigentlichen
        Testcode. Läuft nur, wenn check_completeness() zuvor mindestens eine async-Testfunktion
        gefunden hat (_PYTEST_ASYNC_TEST_RE), siehe dortiger Aufrufer."""
        manifest_text = self._read_manifest_texts()
        if not manifest_text:
            return []
        if self._manifest_has_package(manifest_text, "pytest-asyncio"):
            return []
        if self._manifest_has_package(manifest_text, "anyio"):
            return []  # anyio-Plugin kann denselben Zweck erfüllen, kein Fehlalarm
        return [CompletenessIssue(
            file_path=".",
            message="Testdateien enthalten `@pytest.mark.asyncio`/`async def test_...`, aber "
                    "weder `pytest-asyncio` noch `anyio` sind im Dependency-Manifest gelistet - "
                    "jeder async Test schlägt beim Ausführen mit einem Fixture-/Marker-Fehler "
                    "fehl (fehlendes pytest-Plugin).",
        )]

    def _conflicting_sqlalchemy_config(self, py_texts: dict[str, str]) -> list[CompletenessIssue]:
        """Erster Teil desselben logpulse-Funds: `app/database.py` definierte eine asynchrone
        Engine (`create_async_engine`), `app/models.py` daneben eine eigene synchrone Engine
        (`create_engine`) samt eigener `Base = declarative_base()` - zwei parallele,
        inkompatible Metadata-Registries im selben Projekt. Rein regelbasiert: die bloße
        Koexistenz beider Engine-Arten bzw. mehrerer `declarative_base()`-Definitionen im
        selben Projekt ist so gut wie nie beabsichtigt.

        Fehlalarm-Korrektur (Live-Abgleich gegen alle workspace/-Projekte, Team-Retrospektive
        2026-09-05, real beobachtet an `fastapi-task-mgmt`): Alembic-Migrationsskripte
        (`alembic/env.py`) verwenden IDIOMATISCH eine SYNCHRONE `create_engine()` für den
        Migrationslauf, selbst wenn die eigentliche Anwendung durchgehend async ist (Alembic
        selbst unterstützt Async-Engines nur eingeschränkt, das offizielle Cookiecutter-Template
        wandelt die DSN dafür extra auf ein synchrones Schema um) - das ist kein Bug, sondern
        Standardpraxis, und wird deshalb aus dieser Prüfung ausgenommen."""
        py_texts = {
            rel: text for rel, text in py_texts.items()
            if "alembic" not in Path(rel).parts and "migrations" not in Path(rel).parts
        }
        issues: list[CompletenessIssue] = []
        sync_files = sorted(rel for rel, text in py_texts.items() if _SQLA_SYNC_ENGINE_RE.search(text))
        async_files = sorted(rel for rel, text in py_texts.items() if _SQLA_ASYNC_ENGINE_RE.search(text))
        if sync_files and async_files:
            issues.append(CompletenessIssue(
                file_path=", ".join(sorted(set(sync_files) | set(async_files))),
                message=f"Projekt mischt synchrones SQLAlchemy (`create_engine()` in "
                        f"{', '.join(sync_files)}) mit asynchronem (`create_async_engine()` in "
                        f"{', '.join(async_files)}) - typischerweise ein Fehler (zwei parallele "
                        f"DB-Engines/Base-Registries statt einer konsistenten async- oder "
                        f"sync-Anbindung).",
            ))

        base_files = sorted(rel for rel, text in py_texts.items() if _SQLA_DECLARATIVE_BASE_RE.search(text))
        if len(base_files) > 1:
            issues.append(CompletenessIssue(
                file_path=", ".join(base_files),
                message=f"Mehrere eigenständige SQLAlchemy-`Base`-Definitionen "
                        f"(`declarative_base()`/`DeclarativeBase`) in {', '.join(base_files)} "
                        f"gefunden - Modelle landen dann in getrennten Metadata-Registries, "
                        f"`Base.metadata.create_all()` legt nur einen Teil der Tabellen an.",
            ))
        return issues

    def _find_matching_paren(self, text: str, open_idx: int) -> int | None:
        """Pendant zu _find_matching_js_brace() (siehe oben), nur für "(...)" statt "{...}" -
        genutzt von _double_router_prefix(), um den vollständigen Argument-Bereich eines
        APIRouter(...)/include_router(...)-Aufrufs robust gegen verschachtelte Klammern (z.B.
        `tags=["a", "b"]`, verschachtelte Funktionsaufrufe) zu erfassen."""
        depth = 0
        for i in range(open_idx, len(text)):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        return None

    def _double_router_prefix(self, py_texts: dict[str, str]) -> list[CompletenessIssue]:
        """Neunter realer Fund (logpulse-Projekt, bei der Live-Verifikation dieses Checks
        gefunden): `app/routers/logs.py` deklariert bereits `APIRouter(prefix="/api/v1/logs")`,
        `app/main.py` hängt beim Registrieren zusätzlich `app.include_router(logs.router,
        prefix="/api/v1")` an - die tatsächliche Route landet dadurch unter
        `/api/v1/api/v1/logs` statt der beabsichtigten `/api/v1/logs`, jeder Aufruf der
        "richtigen" URL schlägt mit 404 fehl (echt reproduziert: `pytest` lief durch, bis
        genau dieser Bug den Testlauf fehlschlagen ließ). Rein regelbasiert: pro Datei wird der
        von `APIRouter(prefix=...)` deklarierte Präfix unter dem Dateinamen (ohne Endung) als
        Schlüssel gemerkt (FastAPI-Konvention `from app.routers import logs` + `logs.router`),
        dann wird jeder `include_router(<name>.router, ..., prefix=...)`-Aufruf mit demselben
        Namen gegengeprüft - zwei NICHT-LEERE Präfixe für denselben Router gleichzeitig sind
        so gut wie nie beabsichtigt. Ein Import-Alias (`import logs as x`) wird bewusst NICHT
        aufgelöst - dieselbe konservative Grundhaltung wie überall in dieser Datei, ein
        übersehener Fund ist besser als ein Fehlalarm."""
        router_prefix_by_module: dict[str, str] = {}
        for rel, text in py_texts.items():
            for m in re.finditer(r"\bAPIRouter\s*(\()", text):
                close_idx = self._find_matching_paren(text, m.start(1))
                if close_idx is None:
                    continue
                args_text = text[m.end(1):close_idx]
                prefix_match = re.search(r"\bprefix\s*=\s*[\"']([^\"']+)[\"']", args_text)
                if prefix_match and prefix_match.group(1):
                    router_prefix_by_module[Path(rel).stem] = prefix_match.group(1)

        if not router_prefix_by_module:
            return []

        issues: list[CompletenessIssue] = []
        for rel, text in py_texts.items():
            for m in re.finditer(r"\.include_router\s*(\()\s*([A-Za-z_]\w*)\.router\b", text):
                router_prefix = router_prefix_by_module.get(m.group(2))
                if not router_prefix:
                    continue
                close_idx = self._find_matching_paren(text, m.start(1))
                if close_idx is None:
                    continue
                call_args = text[m.end(1):close_idx]
                include_prefix_match = re.search(r"\bprefix\s*=\s*[\"']([^\"']+)[\"']", call_args)
                if not include_prefix_match or not include_prefix_match.group(1):
                    continue
                line_no = text.count("\n", 0, m.start()) + 1
                issues.append(CompletenessIssue(
                    file_path=rel, line_number=line_no,
                    message=f"`include_router({m.group(2)}.router, prefix=\"{include_prefix_match.group(1)}\")` "
                            f"registriert einen zusätzlichen Präfix, obwohl der Router selbst bereits "
                            f"`APIRouter(prefix=\"{router_prefix}\")` deklariert - die tatsächliche Route "
                            f"landet unter `{include_prefix_match.group(1)}{router_prefix}` statt der "
                            f"vermutlich beabsichtigten `{router_prefix}`.",
                ))
        return issues

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
