"""
core/verifier/security.py – SecurityMixin: echte Sicherheits-Scans statt LLM-Raten.

check_dependency_vulnerabilities() ersetzt die bisherige rein LLM-basierte Einschätzung des
security-Agenten zu Abhängigkeits-Risiken durch einen echten Scan (pip-audit/npm audit/
cargo-audit/govulncheck) gegen eine öffentliche Advisory-Datenbank – kein Raten mehr, ob eine
gepinnte Paketversion bekannte CVEs hat.

check_sast() ersetzt die bisherige rein LLM-basierte Einschätzung des security-Agenten zu
Schwachstellen im SELBST GESCHRIEBENEN Code (Freitext-Vermutungen ohne Datei/Zeile) durch
einen echten statischen Scan (bandit für Python) – dasselbe Prinzip, das
check_dependency_vulnerabilities() bereits für Fremdpaket-CVEs etabliert hat.

check_licenses() ersetzt die bisherige rein LLM-basierte Lizenz-Tabelle des compliance-
Agenten ("MIT/AGPL 🔴", geraten) durch einen echten Scan der tatsächlich installierten
Paket-Lizenzen (pip-licenses für Python) inkl. einfacher Copyleft-Heuristik (GPL/AGPL/LGPL/
MPL/CDDL/EUPL/SSPL) – kein Raten mehr, welche Lizenz ein Fremdpaket wirklich hat.
"""

import json
import shutil
from pathlib import Path

from core.code_sandbox import CodeSandbox, ExecutionResult
from core.verifier.models import (
    _IGNORED_DIRS,
    DependencyAuditReport,
    DependencyVulnerability,
    LicenseAuditReport,
    LicenseFinding,
    SastFinding,
    SastReport,
    _is_copyleft_license,
)


class SecurityMixin:
    """Führt echte Dependency-/SAST-/Lizenz-Scans für ein Projekt aus."""

    def check_dependency_vulnerabilities(self, timeout_seconds: float = 120.0) -> list[DependencyAuditReport]:
        reports: list[DependencyAuditReport] = []
        # Bugfix: core/verifier/environment.py stellt seit der Unterstützung von
        # requirements-dev.txt _requirements_files() (Mehrzahl, Liste) bereit - der Aufruf
        # hier war noch auf die alte Einzahl-Methode ausgerichtet, die es nicht mehr gibt
        # (AttributeError bei JEDEM Projekt mit requirements.txt, brach die komplette
        # Verifikations-Schleife).
        # Zweiter, echter Fund (Sandbox-Dependency-Desynchronisation): entgegen dem früheren
        # Kommentar hier prüft `pip-audit -r <datei>` NUR die in GENAU dieser einen Datei
        # gelisteten Pakete gegen die Advisory-Datenbank, nicht "alle gefundenen Requirements-
        # Dateien gemeinsam" - ein Aufruf mit ausschließlich req_files[0] (meist requirements.txt)
        # ließ Testabhängigkeiten wie `httpx`/`pytest-asyncio` in requirements-dev.txt
        # STILLSCHWEIGEND aus jedem Sicherheits-Scan heraus, obwohl _ensure_python_environment()
        # sie tatsächlich installiert. pip-audit akzeptiert `-r` mehrfach wiederholt und prüft
        # dann alle so referenzierten Pakete in einem Aufruf.
        req_files = self._requirements_files()
        if req_files:
            reports.append(self._audit_python_dependencies(req_files, timeout_seconds))
        for node_dir in self._find_node_projects():
            reports.append(self._audit_node_dependencies(node_dir, timeout_seconds))
        if self._has_rust_project():
            reports.append(self._audit_rust_dependencies(timeout_seconds))
        if self._has_go_project():
            reports.append(self._audit_go_dependencies(timeout_seconds))
        return reports

    def _audit_rust_dependencies(self, timeout_seconds: float) -> DependencyAuditReport:
        if shutil.which("cargo") is None:
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="cargo-audit",
                reason_skipped="`cargo` ist auf diesem System nicht installiert/verfügbar.",
            )
        result = CodeSandbox.run_command(["cargo", "audit", "--json"], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        if result.exit_code != 0 and "not found" in (result.stderr or "").lower():
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="cargo-audit",
                reason_skipped="`cargo-audit` ist nicht installiert (`cargo install cargo-audit`).",
            )
        return DependencyAuditReport(attempted=True, vulnerable=result.exit_code != 0, tool="cargo-audit")

    def _audit_go_dependencies(self, timeout_seconds: float) -> DependencyAuditReport:
        if shutil.which("govulncheck") is None:
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="govulncheck",
                reason_skipped="`govulncheck` ist auf diesem System nicht installiert (`go install golang.org/x/vuln/cmd/govulncheck@latest`).",
            )
        result = CodeSandbox.run_command(["govulncheck", "./..."], cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return DependencyAuditReport(attempted=True, vulnerable=result.exit_code != 0, tool="govulncheck")

    def check_sast(self, timeout_seconds: float = 60.0) -> list[SastReport]:
        reports: list[SastReport] = []
        if self._has_python_files():
            reports.append(self._sast_python(timeout_seconds))
        return reports

    def _sast_python(self, timeout_seconds: float) -> SastReport:
        if shutil.which("bandit") is None:
            return SastReport(
                attempted=False, vulnerable=False, tool="bandit",
                reason_skipped="`bandit` ist auf diesem System nicht installiert/verfügbar (`pip install bandit`).",
            )
        # -x nimmt eine kommagetrennte Liste von Pfaden entgegen (kein wiederholbares Flag
        # wie ruffs --extend-exclude) – dieselben Build-/Umgebungs-Artefakte wie bei jedem
        # anderen Check (_IGNORED_DIRS) werden ausgeschlossen, keine vom Team geschriebenen
        # Projektdateien. Zusätzlich werden vom tester-Agenten geschriebene Testverzeichnisse
        # ausgeschlossen (siehe _find_test_dirs()): bandit prüft SICHERHEIT von Anwendungscode,
        # nicht die Qualität von Testcode - eine Testdatei mit `assert response.status_code ==
        # 200` ist kein Sicherheitsfund, nur bandits eigene Heuristik (B101) kann Testcode
        # architektonisch nicht von Produktivcode unterscheiden.
        exclude_dirs = sorted(_IGNORED_DIRS | self._find_test_dirs())
        exclude = ",".join(str(self.project_dir / d) for d in exclude_dirs)
        # Team-Optimierung (echter Fund: bandit meldete B101 "Use of assert detected" bei JEDER
        # generierten Testdatei, weil pytest-Tests idiomatisch auf `assert` statt auf
        # `self.assertEqual(...)` setzen - das ist die vom tester-Agenten (agents/tester_agent.py)
        # bewusst vorgeschriebene Praxis, keine Sicherheitslücke. Ohne die Regel wurde derselbe
        # False-Positive-Fund bei praktisch JEDEM Python-Projekt mit Tests gemeldet, unabhängig
        # vom -x-Ausschluss oben (z.B. wenn ein Test versehentlich außerhalb eines erkannten
        # Testverzeichnisses liegt) - `-s B101` schließt die Regel projektweit als zweite,
        # robustere Verteidigungslinie aus, ECHTE Sicherheitsregeln (SQL-Injection, hartcodierte
        # Secrets, unsichere Deserialisierung, ...) bleiben davon unberührt.
        command = ["bandit", "-r", str(self.project_dir), "-f", "json", "-x", exclude, "-s", "B101"]
        result = CodeSandbox.run_command(command, cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return self._parse_bandit_result(result)

    def _find_test_dirs(self) -> set[str]:
        """Findet typische Testverzeichnis-Namen im Projekt (relativ zu project_dir), damit
        bandit sie gezielt ausschließen kann - siehe _sast_python()-Docstring."""
        names = {"tests", "test", "__tests__"}
        found: set[str] = set()
        for candidate in self.project_dir.iterdir() if self.project_dir.exists() else []:
            if candidate.is_dir() and candidate.name in names:
                found.add(candidate.name)
        return found

    def _parse_bandit_result(self, result: ExecutionResult) -> SastReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return SastReport(
                attempted=False, vulnerable=False, tool="bandit",
                reason_skipped=f"bandit lieferte kein gültiges Ergebnis: {tail}",
            )

        findings: list[SastFinding] = []
        for entry in data.get("results", []):
            raw_path = entry.get("filename", "?")
            try:
                rel = str(Path(raw_path).resolve().relative_to(self.project_dir)).replace("\\", "/")
            except (ValueError, OSError):
                rel = raw_path
            findings.append(SastFinding(
                file_path=rel,
                line_number=entry.get("line_number", 0),
                message=entry.get("issue_text", ""),
                rule=entry.get("test_id") or "",
                severity=entry.get("issue_severity", ""),
            ))
        return SastReport(attempted=True, vulnerable=len(findings) > 0, tool="bandit", findings=findings)

    def check_licenses(self, timeout_seconds: float = 60.0) -> list[LicenseAuditReport]:
        reports: list[LicenseAuditReport] = []
        if self._requirements_files():
            reports.append(self._license_audit_python(timeout_seconds))
        return reports

    def _license_audit_python(self, timeout_seconds: float) -> LicenseAuditReport:
        if shutil.which("pip-licenses") is None:
            return LicenseAuditReport(
                attempted=False, has_copyleft_risk=False, tool="pip-licenses",
                reason_skipped="`pip-licenses` ist auf diesem System nicht installiert/verfügbar (`pip install pip-licenses`).",
            )
        # pip-licenses liest Metadaten der TATSÄCHLICH installierten Pakete (kein Netzwerk,
        # anders als pip-audit) - braucht daher gezielt die isolierte Projekt-venv aus
        # ensure_environment() statt der Framework-eigenen Umgebung, in der das Tool selbst
        # installiert ist. --python zeigt auf den Ziel-Interpreter, dessen Pakete geprüft
        # werden sollen (fällt wie überall sonst auf den System-Interpreter zurück, falls die
        # venv noch nicht existiert - siehe _resolve_python()).
        command = ["pip-licenses", "--python", self._resolve_python(), "--format=json"]
        result = CodeSandbox.run_command(command, cwd=self.project_dir, timeout_seconds=timeout_seconds)
        return self._parse_pip_licenses_result(result)

    def _parse_pip_licenses_result(self, result: ExecutionResult) -> LicenseAuditReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return LicenseAuditReport(
                attempted=False, has_copyleft_risk=False, tool="pip-licenses",
                reason_skipped=f"pip-licenses lieferte kein gültiges Ergebnis: {tail}",
            )

        findings: list[LicenseFinding] = []
        for entry in data:
            license_str = entry.get("License", "") or ""
            findings.append(LicenseFinding(
                package=entry.get("Name", "?"),
                version=entry.get("Version", "?"),
                license=license_str,
                copyleft=_is_copyleft_license(license_str),
            ))
        return LicenseAuditReport(
            attempted=True, has_copyleft_risk=any(f.copyleft for f in findings),
            tool="pip-licenses", findings=findings,
        )

    def _audit_python_dependencies(self, req_files: list[Path], timeout_seconds: float) -> DependencyAuditReport:
        if shutil.which("pip-audit") is None:
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="pip-audit",
                reason_skipped="`pip-audit` ist auf diesem System nicht installiert/verfügbar "
                               "(`pip install pip-audit`).",
            )
        # `-r <requirements.txt>` löst Versionen direkt aus der Datei auf – braucht KEINE
        # lokale Installation der Pakete, funktioniert also unabhängig von der isolierten
        # venv (die für ein frisches Projekt evtl. noch gar nicht existiert). `-r` ist
        # wiederholbar - JEDE gefundene Requirements-Datei (requirements.txt UND
        # requirements-dev.txt) wird in einem Aufruf geprüft, siehe
        # check_dependency_vulnerabilities()-Docstring.
        r_flags = [flag for req_file in req_files for flag in ("-r", str(req_file))]
        result = CodeSandbox.run_command(
            ["pip-audit", *r_flags, "-f", "json"],
            cwd=self.project_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_pip_audit_result(result)

    def _parse_pip_audit_result(self, result: ExecutionResult) -> DependencyAuditReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="pip-audit",
                reason_skipped=f"pip-audit lieferte kein gültiges Ergebnis (z. B. keine "
                               f"Netzwerkverbindung zur Advisory-Datenbank): {tail}",
            )

        vulnerabilities = [
            DependencyVulnerability(
                package=dep.get("name", "?"),
                version=dep.get("version", "?"),
                vulnerability_id=vuln.get("id", "?"),
                description=(vuln.get("description") or "").strip()[:300],
                fix_versions=list(vuln.get("fix_versions") or []),
            )
            for dep in data.get("dependencies", [])
            for vuln in dep.get("vulns", [])
        ]
        return DependencyAuditReport(
            attempted=True, vulnerable=len(vulnerabilities) > 0, tool="pip-audit",
            vulnerabilities=vulnerabilities,
        )

    def _audit_node_dependencies(self, node_dir: Path, timeout_seconds: float) -> DependencyAuditReport:
        rel = self._relative_label(node_dir)
        if shutil.which("npm") is None:
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"`npm` ist auf diesem System nicht installiert/verfügbar ({rel}).",
            )
        if not (node_dir / "package-lock.json").exists():
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"Keine package-lock.json ({rel}) – `npm audit` benötigt eine Lockfile "
                               f"(wird normalerweise von ensure_environment() angelegt).",
            )

        result = CodeSandbox.run_command(
            ["npm", "audit", "--json"], cwd=node_dir, timeout_seconds=timeout_seconds,
        )
        return self._parse_npm_audit_result(result, rel)

    def _parse_npm_audit_result(self, result: ExecutionResult, label: str) -> DependencyAuditReport:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            tail = (result.stdout + result.stderr).strip()[-800:]
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"`npm audit` ({label}) lieferte kein gültiges Ergebnis: {tail}",
            )

        # `npm audit` meldet einen technischen Fehlschlag (z. B. Registry nicht erreichbar)
        # als {"error": {...}} OHNE "vulnerabilities"-Schlüssel – das darf NIE stillschweigend
        # als "keine Schwachstellen" durchgehen.
        if "error" in data and "vulnerabilities" not in data:
            error_detail = json.dumps(data.get("error", {}))[:500]
            return DependencyAuditReport(
                attempted=False, vulnerable=False, tool="npm audit",
                reason_skipped=f"`npm audit` ({label}) meldete einen Fehler statt eines Scan-Ergebnisses: {error_detail}",
            )

        vulnerabilities: list[DependencyVulnerability] = []
        for pkg_name, pkg_info in data.get("vulnerabilities", {}).items():
            for via in pkg_info.get("via", []):
                if not isinstance(via, dict):
                    continue  # String-Eintrag = Verweis auf eine andere betroffene Abhängigkeit, keine eigene Advisory
                vuln_id = via.get("url", "").rsplit("/", 1)[-1] or via.get("title", "?")
                vulnerabilities.append(DependencyVulnerability(
                    package=pkg_name,
                    version=pkg_info.get("range", "?"),
                    vulnerability_id=vuln_id,
                    description=(via.get("title") or "").strip()[:300],
                    severity=via.get("severity", ""),
                ))
        total = data.get("metadata", {}).get("vulnerabilities", {}).get("total", len(vulnerabilities))
        return DependencyAuditReport(
            attempted=True, vulnerable=total > 0, tool="npm audit", vulnerabilities=vulnerabilities,
        )
