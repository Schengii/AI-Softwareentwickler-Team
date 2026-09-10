"""
agents/orchestrator/verification.py – VerificationMixin: Governance-Fix-Schleife und echte
Verifikations-/Fix-Schleife (Ersetzt die alte Keyword-basierte Fix-Schleife).

_run_governance_fix_loop() beauftragt gezielte Korrekturen für kritische Review-Befunde
(code_reviewer/security/compliance) NACH der Fachbereichs-Hierarchie und VOR der echten
Testverifikation.

_run_verification_loop() installiert Abhängigkeiten in einer isolierten Umgebung, führt die
echte Testsuite aus und schickt bei Fehlschlägen einen GEZIELTEN Korrekturauftrag an genau
die Agenten, deren Dateien laut echtem Traceback betroffen sind. Führt anschließend alle
weiteren Verifikations-Checks aus (Docker-Build, Dependency-/SAST-/Lizenz-Audit, Lint,
Coverage, Runtime-Smoke, Lastentest, Browser/A11y) - Runtime-Smoke, Lastentest und Browser/UI
laufen dabei über _run_runtime_check_with_fix() (siehe unten), das bei Fehlschlag ebenfalls
einen gezielten Korrekturauftrag auslöst statt nur verification_ok zurückzusetzen.
"""

import asyncio
import logging
import re
from collections.abc import Callable, Collection, Iterable
from pathlib import PurePosixPath
from typing import TypeVar

from agents.department_lead_agent import DEPARTMENT_DEFINITIONS
from agents.orchestrator.constants import REVIEW_ONLY_AGENT_IDS
from config import (
    ENABLE_COMPLETENESS_CHECK,
    ENABLE_GOVERNANCE_FIX_LOOP,
    ENABLE_LOAD_TEST_CHECK,
    ENABLE_SMOKE_TEST_GATE,
    LOAD_TEST_DURATION_SECONDS,
    LOAD_TEST_TIMEOUT_SECONDS,
    MAX_REVIEW_ITERATIONS,
    MAX_TASK_TOKENS,
    MAX_VERIFICATION_ITERATIONS,
    MIN_TEST_COVERAGE,
)
from core.backlog_store import get_ticket, upsert_ticket
from core.decision_log import log_decision
from core.message_bus import AgentResult, AgentTask
from core.notifier import notify_external
from core.pre_flight_check import PreFlightIssue, run_pre_flight_check
from core.review_gate import (
    find_critical_findings,
    find_permission_blocked_questions,
    find_structural_scope_questions,
    finding_from_critical_block,
    route_findings_to_owners,
)
from core.team_memory import record_lesson
from core.verifier import ProjectVerifier, VerificationReport
from memory.agent_knowledge_base import agent_knowledge_base

# Realer Fund (taskpulse-Projekt, 2026-09-03): eine fehlende `app/models.py` (referenziert per
# `from . import database, models, schemas`) führte zu einem ModuleNotFoundError/ImportError,
# der als ganz normaler Testfehlschlag durch die Fix-Schleife unten lief - die generische
# Fix-Beschreibung ("Nutze read_file, um die betroffene(n) Datei(en) zu prüfen...") nannte NIE
# konkret, WELCHE Datei fehlt, nur den vollen Traceback-Text. Der beauftragte Agent musste sich
# das selbst erschließen und tat es über mehrere Versuche hinweg nicht zuverlässig (33
# Agenten-Durchläufe, 714k Tokens, am Ende trotzdem verification_ok=False). Diese Muster
# erkennen die beiden häufigsten Python-Fehlerklassen für "referenziertes Modul/Symbol
# existiert nicht" und machen die fehlende Datei/das fehlende Symbol im Fix-Auftrag EXPLIZIT,
# statt es implizit im Traceback zu verstecken.
_MODULE_NOT_FOUND_RE = re.compile(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]")
_IMPORT_NAME_ERROR_RE = re.compile(r"ImportError: cannot import name ['\"](\w+)['\"] from ['\"]([\w.]+)['\"]")

# Team-Optimierung (ki_team_analyse_und_optimierungen.md, Punkt 1.2/2): vier weitere häufige
# Laufzeit-Fehlerklassen, die bisher generisch ("lies die Datei und behebe den Fehler") ohne
# konkrete Handlungsanweisung an den Fix-Agenten weitergeleitet wurden - der Fix-Agent musste
# sich Ursache UND Lösungsweg selbst erschließen, oft über mehrere teure Iterationen hinweg
# (siehe _no_progress()-Zirkuit-Breaker unten, der genau solche Fälle abfängt, aber erst NACH
# dem ersten vergeblichen Versuch). Analog zu _diagnose_import_failure() oben: reine
# Regex-Erkennung ohne LLM-Aufruf, liefert eine konkrete, an den jeweils fachlich zuständigen
# Agenten (database/backend) adressierte Diagnosezeile.
_INTEGRITY_ERROR_RE = re.compile(
    r"IntegrityError[^\n]*?NOT NULL constraint failed:\s*([\w]+)\.([\w]+)", re.DOTALL,
)
_NO_SUCH_TABLE_RE = re.compile(r"OperationalError[^\n]*?no such table:\s*([\w]+)", re.DOTALL)
_DICT_ATTRIBUTE_ERROR_RE = re.compile(r"AttributeError:\s*'dict' object has no attribute '(\w+)'")
# Erkennt einen im URL-Pfad direkt aufeinanderfolgend WIEDERHOLTEN Prefix-Abschnitt
# (z.B. "/api/v1/api/v1/users") - das typische Symptom eines doppelt eingebundenen Routers
# (einmal `prefix=` im APIRouter() selbst, ein zweites Mal identisch in `include_router()`).
_DUPLICATE_URL_PREFIX_RE = re.compile(r"(/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)?)\1")

# Team-Optimierung (logipulse-Lauf 2026-09-10, logs/verification/20260910_084833_logipulse.log):
# `assert 404 == 202` in tests/test_events.py und `AttributeError: module 'jwt' has no attribute
# 'encode'` landeten beim `tester`, weil die fehlschlagende Zeile in einer Testdatei lag. Der
# tester kann aber weder einen fehlenden Router in main.py mounten noch eine toxische
# Paket-Kollision in requirements.txt beheben - die Fix-Schleife lief dreimal wirkungslos.
# Erkennt "Endpunkt nicht registriert": der Test erwartete einen ANDEREN Status als 404
# (pytest: `assert <ist> == <soll>`, unittest: `<ist> != <soll>`) oder FastAPIs Default-Body.
_ROUTE_NOT_FOUND_RE = re.compile(
    r"assert 404 == (?!404\b)\d{3}\b"
    r"|\b404 != (?!404\b)\d{3}\b"
    r"|['\"]detail['\"]\s*:\s*['\"]Not Found['\"]"
    r"|\bRoute Not Found\b",
    re.IGNORECASE,
)
_MODULE_ATTRIBUTE_ERROR_RE = re.compile(
    r"AttributeError: module ['\"]([\w.]+)['\"] has no attribute ['\"](\w+)['\"]"
)
# Agenten, die ein Dependency-Manifest fachlich pflegen dürfen (siehe _dependency_fix_owner).
_DEPENDENCY_FIX_AGENT_IDS = ("backend", "refactoring")


def _diagnose_runtime_failure(message: str) -> str | None:
    """Analog zu _diagnose_import_failure() oben, aber für die vier häufigsten NICHT-Import-
    Laufzeitfehlerklassen aus der Team-Analyse (SQLAlchemy-Schema-Konflikte, dict-statt-Modell-
    Rückgaben, doppelte Router-Prefixe). Gibt None zurück, wenn keines der Muster passt - dann
    bleibt der generische Fix-Auftrag unverändert (siehe Aufrufer)."""
    m = _INTEGRITY_ERROR_RE.search(message)
    if m:
        table, column = m.group(1), m.group(2)
        return (
            f"⚠️ KONKRETE URSACHE: `IntegrityError` – Spalte `{column}` in Tabelle `{table}` ist "
            f"`nullable=False`, aber ein Insert/Update übergibt keinen Wert dafür. Setze entweder "
            f"`nullable=True` (falls das Feld wirklich optional ist) oder ergänze in JEDEM "
            f"betroffenen Insert/Test einen validen Wert für `{column}`."
        )
    m = _NO_SUCH_TABLE_RE.search(message)
    if m:
        table = m.group(1)
        return (
            f"⚠️ KONKRETE URSACHE: `OperationalError: no such table: {table}` – das DB-Schema wurde "
            f"nie angelegt (Migration/`create_all()` nicht ausgeführt) ODER die Modelle nutzen eine "
            f"ANDERE `Base`-Instanz als die, gegen die Migration/`create_all()` läuft. Prüfe, dass "
            f"ALLE Modelle dieselbe zentrale `Base`-Klasse importieren und dass das Schema (Alembic-"
            f"Migration oder `Base.metadata.create_all()`) vor dem Testlauf tatsächlich erzeugt wird."
        )
    m = _DICT_ATTRIBUTE_ERROR_RE.search(message)
    if m:
        attr = m.group(1)
        return (
            f"⚠️ KONKRETE URSACHE: `AttributeError: 'dict' object has no attribute '{attr}'` – ein "
            f"Service/Endpoint gibt ein rohes `dict` zurück statt einer Instanz des deklarierten "
            f"Pydantic-Modells. Instanziiere das Modell explizit (z. B. `return UserOut(**data)` "
            f"statt `return data`), statt ein dict weiterzureichen."
        )
    if "404" in message:
        m = _DUPLICATE_URL_PREFIX_RE.search(message)
        if m:
            dup = m.group(1)
            return (
                f"⚠️ KONKRETE URSACHE: doppelter Router-Prefix im aufgerufenen Pfad (`{dup}{dup}`) – "
                f"der Router wurde vermutlich sowohl mit `prefix=\"{dup}\"` in `APIRouter(...)` "
                f"definiert als auch ein zweites Mal mit demselben Prefix in "
                f"`app.include_router(router, prefix=\"{dup}\")` eingebunden. Entferne den Prefix an "
                f"GENAU einer der beiden Stellen."
            )
    if _ROUTE_NOT_FOUND_RE.search(message):
        return (
            "⚠️ KONKRETE URSACHE: HTTP 404 statt des erwarteten Statuscodes – der aufgerufene "
            "Endpunkt ist in der laufenden App NICHT registriert. Prüfe in `main.py`/der App-Fabrik, "
            "ob der zuständige Router per `app.include_router(...)` eingebunden ist und ob Pfad und "
            "Prefix exakt dem dokumentierten Endpunkt (README/docs) entsprechen. Ändere NICHT die "
            "Test-Assertion, um den 404 zu akzeptieren."
        )
    m = _MODULE_ATTRIBUTE_ERROR_RE.search(message)
    if m:
        module, attr = m.group(1), m.group(2)
        from core.manifest_guard import TOXIC_DEPENDENCY_RULES

        rule = TOXIC_DEPENDENCY_RULES.get(module.split(".")[0].lower())
        if rule is not None:
            return (
                f"⚠️ KONKRETE URSACHE: `AttributeError: module '{module}' has no attribute '{attr}'` – "
                f"toxische Paket-Kollision: {rule.reason}. Entferne das Paket `{module}` aus "
                f"requirements.txt und behalte nur `{rule.legitimate_packages[0]}` – Code und Tests "
                "sind nicht die Ursache."
            )
        return (
            f"⚠️ KONKRETE URSACHE: `AttributeError: module '{module}' has no attribute '{attr}'` – "
            f"ist `{module}` ein Drittanbieter-Paket, ist in requirements.txt ein falsches oder "
            "kollidierendes Paket bzw. eine inkompatible Version eingetragen. Ist es ein lokales "
            f"Modul, fehlt `{attr}` dort tatsächlich."
        )
    return None


def _is_test_file(path: str) -> bool:
    """True für Testcode (test_*.py, *_test.py, conftest.py, alles unter tests/)."""
    p = PurePosixPath(path.replace("\\", "/"))
    return (
        p.name.startswith("test_") or p.name.endswith("_test.py") or p.name == "conftest.py"
        or "tests" in p.parts[:-1]
    )


def _is_local_module(module: str, file_owners: dict[str, str]) -> bool:
    """True, wenn der Top-Level-Name von `module` einer Projektdatei/einem Projektordner
    entspricht - dann ist ein Attribut-/Import-Fehler ein Code-, kein Dependency-Problem."""
    top = module.split(".")[0]
    for rel in file_owners:
        p = PurePosixPath(rel.replace("\\", "/"))
        if (p.suffix == ".py" and p.stem == top) or top in p.parts[:-1]:
            return True
    return False


def _dependency_error_module(message: str, file_owners: dict[str, str]) -> str | None:
    """Name des Drittanbieter-Moduls, falls die Fehlermeldung ein Dependency-Problem zeigt
    (`AttributeError: module 'jwt' ...` bzw. `ModuleNotFoundError` eines Nicht-Projektmoduls)."""
    for pattern in (_MODULE_ATTRIBUTE_ERROR_RE, _MODULE_NOT_FOUND_RE):
        m = pattern.search(message)
        if m and not _is_local_module(m.group(1), file_owners):
            return m.group(1)
    return None


def _dependency_fix_owner(file_owners: dict[str, str], available_agents: Collection[str]) -> str | None:
    """Bevorzugt den bisherigen Owner von requirements.txt (sofern backend/refactoring), sonst
    backend, sonst refactoring - nie den tester, der Manifeste fachlich nicht verantwortet."""
    manifest_owner = file_owners.get("requirements.txt")
    preferred = manifest_owner if manifest_owner in _DEPENDENCY_FIX_AGENT_IDS else None
    for candidate in (preferred, *_DEPENDENCY_FIX_AGENT_IDS):
        if candidate and candidate in available_agents:
            return candidate
    return None


def _route_not_found_owner(file_owners: dict[str, str], available_agents: Collection[str]) -> str | None:
    """backend (mountet Router in main.py); ohne backend der Owner einer main.py."""
    if "backend" in available_agents:
        return "backend"
    for rel, owner in file_owners.items():
        if PurePosixPath(rel.replace("\\", "/")).name == "main.py" and not _is_test_file(rel) and owner in available_agents:
            return owner
    return None


def _route_failure_owners(
    message: str,
    files: Iterable[str],
    file_owners: dict[str, str],
    available_agents: Collection[str],
    tester_participated: bool,
) -> set[str]:
    """Ursachen-basierte Zuordnung eines echten Testfehlers zu den Fix-Agenten.

    Reihenfolge: Datei-Owner laut Traceback als Ausgangsbasis, danach überschreiben bekannte
    Ursachenklassen diese Zuordnung (Import-Ziel, DB-Schema, dict-Rückgabe/doppelter Prefix,
    nicht registrierte Route -> backend, Dependency-Kollision -> backend/refactoring). Der
    `tester` bleibt nur für reine Test-Code-Fehler zuständig: Zeigt der Traceback zusätzlich
    Produktivcode eines anderen Agenten, wird er entfernt; als letzter Fallback greift er nur,
    wenn sonst niemand zuständig ist.
    """
    files = list(files)
    owners = {file_owners[f] for f in files if f in file_owners}
    # Team-Optimierung (dieser Auftrag: `workspace/opspilot` scheiterte wiederholt mit
    # `ImportError: cannot import name 'X' from 'Y'`) - der Traceback zeigt bei diesem
    # Fehlerbild nur die IMPORTIERENDE Datei (z.B. app/api/auth.py), nicht das Zielmodul
    # `Y` selbst, in dem das Symbol tatsächlich fehlt. Die generische Owner-Ermittlung
    # oben adressiert deshalb oft den falschen/gar keinen Agenten und der Fehler landete
    # zusätzlich beim `tester`-Fallback, der `Y` nicht besitzt und das Symbol strukturell
    # nicht ergänzen kann. Löst hier deterministisch den Owner von `Y` selbst auf (statt
    # nur der importierenden Datei) und dispatcht GEZIELT dorthin, BEVOR der generische
    # tester-Fallback greift.
    import_target = _import_name_error_target(message)
    if import_target is not None:
        _name, module = import_target
        module_owner = file_owners.get(module.replace(".", "/") + ".py")
        if module_owner:
            owners = {module_owner}
        elif not owners and "backend" in available_agents:
            owners = {"backend"}
    # Team-Optimierung (echter Fund: memory/backlog.json-Tickets `recurring-failure-
    # event_relay`/`recurring-failure-service_bookmark_monitor`) - ein "Ran 0 tests"/
    # "NO TESTS RAN"-Befund hat NIE einen Datei-Bezug im Traceback (reine Testlauf-
    # Diagnostik, kein Stacktrace), landete deshalb blind beim `tester` (siehe Fallback
    # unten) - der konnte die meist umgebungsbedingte Ursache (fehlende Testabhängigkeit
    # in requirements.txt) strukturell nie beheben. Bevorzugt jetzt den Owner von
    # requirements.txt (meist backend/database) für GENAU dieses Fehlerbild, bevor der
    # generische tester-Fallback greift.
    if not owners and _NO_TESTS_RAN_RE.search(message) and "requirements.txt" in file_owners:
        owners = {file_owners["requirements.txt"]}
    # Team-Optimierung (ki_team_analyse_und_optimierungen.md, Punkt 1.2/2): DB-Schema-
    # Fehler (IntegrityError/"no such table") und dict-statt-Modell-Rückgaben treffen
    # im Traceback oft nur eine unbeteiligte Aufrufer-Datei (z.B. den Router), nicht die
    # eigentlich zuständige Datei (Modell-Definition bzw. Service-Funktion) - deshalb
    # hier GEZIELT an den fachlich zuständigen Agenten geroutet, analog zum
    # import_target-Zweig oben, statt sich auf die generische Datei-Zuordnung zu
    # verlassen.
    if (_INTEGRITY_ERROR_RE.search(message) or _NO_SUCH_TABLE_RE.search(message)) and "database" in available_agents:
        owners = {"database"}
    elif (
        _DICT_ATTRIBUTE_ERROR_RE.search(message)
        or ("404" in message and _DUPLICATE_URL_PREFIX_RE.search(message))
    ) and "backend" in available_agents:
        owners = {"backend"}
    elif _ROUTE_NOT_FOUND_RE.search(message) and (route_owner := _route_not_found_owner(file_owners, available_agents)):
        # Nicht registrierter Endpunkt: die Assert-Zeile liegt zwar im Test, die Ursache
        # (fehlendes app.include_router/abweichender Pfad) aber im Backend.
        owners = {route_owner}
    elif _dependency_error_module(message, file_owners) and (dep_owner := _dependency_fix_owner(file_owners, available_agents)):
        owners = {dep_owner}
    elif "tester" in owners and any(
        not _is_test_file(f) and file_owners.get(f) not in (None, "tester") for f in files
    ):
        # Der Fehler entsteht im Produktivcode eines anderen Agenten - kein reiner Test-Code-Fehler.
        owners.discard("tester")
    if not owners and tester_participated:
        owners = {"tester"}
    return owners


def _diagnose_import_failure(message: str) -> str | None:
    """Extrahiert aus einer Python-Fehlermeldung, FALLS es sich um eine der beiden häufigsten
    'Modul/Symbol existiert nicht'-Fehlerklassen handelt, eine konkrete, an den Fix-Agenten
    adressierbare Diagnosezeile - None, wenn keines der beiden Muster passt (dann bleibt der
    generische Fix-Auftrag unverändert, siehe Aufrufer)."""
    m = _MODULE_NOT_FOUND_RE.search(message)
    if m:
        module = m.group(1)
        as_path = module.replace(".", "/")
        return (
            f"⚠️ KONKRETE URSACHE: Das Modul `{module}` existiert nicht (fehlende Datei "
            f"`{as_path}.py` oder fehlendes Paket-Verzeichnis `{as_path}/__init__.py`). Lege "
            f"GENAU DIESE Datei mit echtem Inhalt an, statt nur die importierende Datei zu ändern."
        )
    m = _IMPORT_NAME_ERROR_RE.search(message)
    if m:
        name, module = m.group(1), m.group(2)
        as_path = module.replace(".", "/")
        return (
            f"⚠️ KONKRETE URSACHE: `{name}` existiert nicht in `{as_path}.py` (Modul selbst ist "
            f"vorhanden, das importierte Symbol fehlt darin). Ergänze `{name}` (Klasse/Funktion/"
            f"Variable) in genau dieser Datei, statt nur die importierende Datei zu ändern."
        )
    return None


def _import_name_error_target(message: str) -> tuple[str, str] | None:
    """Extrahiert (Symbolname, Zielmodul) aus einer `ImportError: cannot import name 'X' from
    'Y'`-Meldung, oder None, falls die Meldung kein solches Muster enthält. Dieselbe Regex wie
    in _diagnose_import_failure() oben, hier separat nutzbar für Fix-Routing (siehe
    _run_verification_loop) und persistentes Lernen (siehe _record_verification_learning)."""
    m = _IMPORT_NAME_ERROR_RE.search(message)
    if not m:
        return None
    return m.group(1), m.group(2)


def _record_verification_learning(message: str, agent_id: str = "backend") -> None:
    """
    Deterministisches Lernen aus einem `ImportError: cannot import name 'X' from 'Y'` (echter
    Fund: `workspace/opspilot` scheiterte wiederholt mit genau diesem Fehlerbild, weil ein
    Router eine Hilfsfunktion importierte, die im Zielmodul nie definiert/exportiert wurde).
    Anders als die generischen LLM-Retrospektiven (agents/orchestrator/retrospective.py) läuft
    dies rein regelbasiert und SOFORT bei jedem Auftreten - kein zusätzlicher LLM-Aufruf nötig,
    keine Wartezeit auf den nächsten Retrospektiven-Lauf.

    Speichert eine kurze, konkrete Regel dauerhaft in memory/agent_learnings.json (siehe
    memory/agent_knowledge_base.py.AgentKnowledgeBase.add_learning) - diese Regel wird ab dem
    nächsten Aufruf automatisch in den System-Prompt DIESES Agenten injiziert
    (get_augmented_prompt), sodass das Team aus dem Fehler dauerhaft lernt, statt ihn in
    künftigen Projekten erneut zu begehen. Ein Fehler beim Speichern (z.B. Datei nicht
    schreibbar) darf die eigentliche Fix-Schleife nie zum Absturz bringen.
    """
    target = _import_name_error_target(message)
    if target is None:
        return
    name, module = target
    try:
        agent_knowledge_base.add_learning(
            agent_id,
            f"Prüfe vor Abschluss, dass alle in Routern importierten Hilfsfunktionen "
            f"(z. B. {name}) im Modul {module} tatsächlich definiert und exportiert sind.",
        )
    except Exception:
        pass


# Team-Optimierung (echter Fund: memory/backlog.json-Tickets `recurring-failure-event_relay`/
# `recurring-failure-service_bookmark_monitor`) - siehe _diagnose_no_tests_ran()-Docstring.
_NO_TESTS_RAN_RE = re.compile(r"ran 0 tests\b|no tests ran\b|collected 0 items\b", re.IGNORECASE)


def _diagnose_no_tests_ran(message: str) -> str | None:
    """Erkennt das 'Ran 0 tests'/'NO TESTS RAN'/'collected 0 items'-Muster - der Testlauf startete
    zwar, fand aber KEINEN einzigen Test, obwohl echte Testdateien existieren (core/verifier/
    environment.py.ProjectVerifier._ensure_pytest_available() beugt der häufigsten Ursache davon -
    fehlendes `pytest` in requirements.txt - inzwischen bereits VOR dem Testlauf vor; dieser
    Diagnosehinweis bleibt die zweite Verteidigungslinie, z.B. wenn die Nachinstallation mangels
    Netzwerkzugriffs fehlschlug). Ohne diesen Hinweis hatte der Fix-Loop hier KEINEN Datei-Bezug
    im Traceback (kein `File \"...\", line N` - reine Testlauf-Diagnostik ohne Stacktrace) und
    beauftragte blind den `tester`, der die eigentliche - meist umgebungsbedingte, nicht
    testcode-bedingte - Ursache nie beheben konnte ('Fixversuch änderte nichts')."""
    if _NO_TESTS_RAN_RE.search(message):
        return (
            "⚠️ KONKRETE URSACHE (vermutlich NICHT der Testcode selbst): Der Testlauf startete, "
            "fand aber KEINEN einzigen Test, obwohl Testdateien existieren - typischste Ursache "
            "ist eine fehlende Testabhängigkeit in der Umgebung (z.B. `pytest`/`pytest-asyncio` "
            "fehlt in requirements.txt, wodurch auf `unittest discover` zurückgefallen wird, das "
            "pytest-Stil-Testfunktionen ohne `unittest.TestCase` gar nicht erkennt). Prüfe ZUERST "
            "requirements.txt/requirements-dev.txt auf fehlende Test-Abhängigkeiten, bevor du "
            "Testdateien inhaltlich änderst."
        )
    return None


_T = TypeVar("_T")

# Vier der Fix-Schleifen unten (Test-, Governance-, Vorab-Import-, Vollständigkeits-Schleife)
# teilten bisher dieselbe, viermal wortgleich kopierte "identische Funde wie beim letzten
# Versuch? -> abbrechen"-Logik (Team-Retrospektive nach dem taskpulse-Lauf, zweite Runde).
# _issue_signature()/_no_progress() bündeln NUR die reine Signatur-Bildung/den -Vergleich -
# bewusst NICHT das Abbrechen/Notify/Ticket-Öffnen selbst, das unterscheidet sich je Schleife
# (unterschiedliche Ticket-IDs, Log-Texte, Nebeneffekte wie verification_ok=False) zu sehr, um
# es ohne Klarheitsverlust in eine gemeinsame Funktion zu zwingen - dieselbe Abwägung wie an
# anderer Stelle in dieser Datei (explizite, kommentierte Einzel-Schleifen statt einer
# generischen "Fix-Loop-Engine").
def _issue_signature(items: Iterable[_T], key_fn: Callable[[_T], tuple[str, str]]) -> frozenset[tuple[str, str]]:
    """Baut eine vergleichbare, auf 300 Zeichen gekappte Signatur aus einer Liste von Funden
    (Testfehlern/Governance-Befunden/Vollständigkeits-Issues) - zwei aufeinanderfolgende
    Aufrufe mit ergebnisgleichem `items` liefern dieselbe Signatur, unabhängig von der
    Reihenfolge (frozenset)."""
    return frozenset(key_fn(item) for item in items)


def _no_progress(previous: frozenset[tuple[str, str]] | None, current: frozenset[tuple[str, str]]) -> bool:
    """True, wenn `current` (der frische Fund-Stand) exakt der Signatur des VORHERIGEN
    Fixversuchs entspricht - der Fixversuch hat dann erkennbar nichts verändert. `previous is
    None` (erster Versuch, noch kein Vergleich möglich) zählt bewusst NICHT als "kein
    Fortschritt"."""
    return previous is not None and current == previous


def _prior_run_context(ticket_id: str) -> str:
    """Team-Retrospektive nach dem taskpulse-Lauf, zweite Runde: bisher startete JEDER neue
    Lauf bei Null, selbst wenn ein VORHERIGER Lauf desselben Projekts bereits an genau diesem
    Problem gescheitert war und dafür ein Ticket eröffnet hatte (siehe
    core/backlog_store.get_ticket()-Docstring). Liefert - falls ein offenes ("blocked") Ticket
    mit dieser ID existiert - einen kurzen Kontext-Satz für den ERSTEN Fix-Auftrag dieses Laufs,
    sonst einen leeren String. Ein Lookup-Fehler (z.B. eine kaputte memory/backlog.json) darf
    diesen rein informativen Hinweis nie zum Absturz des Laufs machen - dieselbe defensive
    Haltung wie bei den upsert_ticket()-Aufrufen in dieser Datei."""
    try:
        ticket = get_ticket(ticket_id)
    except Exception:
        return ""
    if ticket is None or ticket.status != "blocked":
        return ""
    return (
        f"\n\n⚠️ HINWEIS: Ein VORHERIGER Lauf dieses Projekts ist bereits an einem ähnlichen "
        f"Problem gescheitert und blieb ungelöst (Ticket `{ticket_id}`): {ticket.detail[:300]}\n"
        "Prüfe, ob dein Fix diesmal WIRKLICH an der Ursache ansetzt, statt denselben "
        "erfolglosen Ansatz zu wiederholen."
    )


class VerificationMixin:
    """Governance-Fix-Schleife und echte Test-/Deployment-Verifikations-Schleife."""

    async def _run_runtime_check_with_fix(
        self,
        *,
        check_fn: Callable,
        build_fix_task: Callable,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None,
        cancel_requested: Callable[[], bool] | None,
        is_attempted: Callable,
        is_passed: Callable,
    ):
        """
        Realer Fund bei einer Bestandsaufnahme des eigenen Teams: anders als ein echter
        Testfehler (siehe _run_verification_loop oben) lösten ein fehlgeschlagener Runtime-
        Smoke-Test, Lastentest oder Browser/UI-Check bisher NIE einen Korrekturauftrag aus -
        sie setzten nur verification_ok=False und der Lauf endete. Ein Projekt mit einem
        kaputten Frontend blieb dadurch über beliebig viele Läufe hinweg rot, weil derselbe
        Fehler nie behoben wurde (real beobachtet: snippet_vault scheiterte 3 Läufe in Folge
        am selben Frontend-Check). Dieselbe gezielte Fix-Schleife wie beim Testfehler, nur
        mit vom Aufrufer übergebener Owner-Ermittlung statt Traceback-Dateizuordnung (diese
        Checks liefern keinen Python-Traceback mit betroffenen Dateien).

        Gibt (report, all_results, budget_aborted, manually_cancelled) zurück. `report` ist
        das Ergebnis des letzten Check-Laufs (erster Lauf, falls nie gefixt wurde).
        """
        report = await asyncio.to_thread(check_fn)
        budget_aborted = False
        manually_cancelled = False
        if not is_attempted(report) or is_passed(report):
            return report, all_results, budget_aborted, manually_cancelled

        for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
            if run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify("  🚫 [bold red]Budget erreicht[/bold red] – weitere Fixversuche werden übersprungen.")
                break
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Fixversuche werden übersprungen.")
                break

            fix_task = build_fix_task(report, attempt)
            if fix_task is None:
                # Kein zuständiger Agent ermittelbar (z.B. kein frontend-Agent Teil des Plans) -
                # Fix-Schleife kann hier nichts beitragen, letzter Check-Stand bleibt maßgeblich.
                break

            notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix (Versuch {attempt}):[/bold yellow] Beauftrage {fix_task.agent_id}...")
            fix_results = await self._run_agents_parallel([fix_task], notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)

            report = await asyncio.to_thread(check_fn)
            if is_passed(report):
                break
            if attempt == MAX_VERIFICATION_ITERATIONS:
                notify("  ⚠️ [yellow]Maximale Fixversuche erreicht – letzter Check-Stand wird übernommen.[/yellow]")

        return report, all_results, budget_aborted, manually_cancelled

    async def _run_governance_fix_loop(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[AgentResult], str, bool, bool]:
        """
        Realer Fund bei einer Bestandsaufnahme des eigenen Teams: code_reviewer/security/
        compliance (REVIEW_ONLY_AGENT_IDS) kategorisieren Befunde in ihren Reports selbst nach
        Schweregrad ("Kritisch") - das löste bisher NIE einen Korrekturauftrag aus, nur ein
        echter Testfehler tat das (siehe _run_verification_loop unten). Ein "Kritisch" im
        Code-Review ist bei einem echten Team ein Blocker, kein FYI im Abschlussbericht.

        Läuft NACH der Fachbereichs-Hierarchie (die Governance-Phase ist bereits gelaufen,
        all_results enthält also schon die individuellen Review-Ergebnisse) und VOR der echten
        Testverifikation - Kritisch-Fixes zuerst, damit die anschließende Testsuite den
        reparierten Stand prüft. core/review_gate.py liefert die (bewusst als Best-Effort
        dokumentierte) Text-Heuristik zur Fund-Erkennung/-Zuordnung, kein LLM-Aufruf dafür nötig.

        Gibt (all_results, summary, budget_aborted, manually_cancelled) zurück - summary ist
        "", wenn nichts zu tun war (kein Rauschen im Normalfall, siehe process()).

        Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive): bei "kein
        Fortschritt" (identische kritische Befunde nach einem Fixversuch) durchläuft diese
        Schleife jetzt dieselbe Eskalationsleiter wie _run_verification_loop unten, BEVOR ein
        Backlog-Ticket eröffnet wird - erst Fachbereichsleiter (geänderte Strategie), dann ein
        letzter Versuch mit HEAVY_MODEL für die stecken gebliebenen Agenten. Vorher gab diese
        Schleife nach GENAU EINEM erfolglosen Fixversuch auf; der spätere `--work-backlog`-
        Retry (core/backlog_worker.py) eskaliert zwar ebenfalls das Modell, aber erst Stunden/
        Tage später im nächsten Scheduler-Zyklus. Zusätzlich läuft check_completeness() (core/
        verifier/completeness.py) als harte, deterministische Gegenprobe zum finalen LLM-Re-
        Review - ein struktureller Neu-Bruch (z.B. ein durch den Fix selbst eingeführter
        `ImportError`, real beobachtet am event_relay-Lauf 2026-09-06) gilt damit als weiterhin
        kritisch, UNABHÄNGIG davon, ob der LLM-Reviewer ihn bemerkt.
        """
        if not ENABLE_GOVERNANCE_FIX_LOOP:
            return all_results, "", False, False

        review_agent_ids = {
            r.agent_id for r in all_results
            if r.agent_id in REVIEW_ONLY_AGENT_IDS and r.success and r.content
        }
        if not review_agent_ids:
            # Keine der Review-Rollen war Teil dieses Plans (z.B. eine kleine Aufgabe ohne
            # QA/Governance) - kein Verhaltensunterschied zu vor dieser Erweiterung.
            return all_results, "", False, False

        summary_lines: list[str] = []
        budget_aborted = False
        manually_cancelled = False
        # Derselbe Zirkuit-Breaker wie in _run_verification_loop (Team-Retrospektive nach dem
        # taskpulse-Lauf): identische kritische Befunde nach einem Fixversuch bedeuten fast
        # immer, dass der Agent das Problem nicht lösen konnte - ein zweiter Fix-Dispatch UND
        # der anschließende verpflichtende Re-Review (siehe unten, "attempt ==
        # MAX_REVIEW_ITERATIONS") wären dann reine Tokens/Zeit-Verschwendung. Bricht in diesem
        # Fall direkt zur Ticket-Eröffnung durch, ohne den zweiten Fix-Dispatch zu versuchen.
        previous_findings_signature: frozenset[tuple[str, str]] | None = None
        # Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive): _run_verification_loop
        # unten eskaliert bei Stagnation bereits an den Fachbereichsleiter UND an ein stärkeres
        # Modell, BEVOR aufgegeben wird - diese Schleife hier brach bisher bei "kein Fortschritt"
        # nach genau EINEM Fixversuch direkt zum Ticket ab, ohne dieselbe Eskalationsleiter zu
        # durchlaufen (der spätere `--work-backlog`-Retry eskaliert zwar das Modell, aber erst
        # Stunden/Tage später im nächsten Scheduler-Zyklus, siehe core/backlog_worker.py). Diese
        # beiden Flags spiegeln escalation_attempted/model_escalation_attempted unten 1:1.
        escalation_attempted = False
        model_escalation_attempted = False
        # Dasselbe Cross-Run-Gedächtnis wie in _run_verification_loop (Team-Retrospektive nach
        # dem taskpulse-Lauf, zweite Runde).
        governance_ticket_id = f"unresolved-governance-critical-{self.last_project_slug}" if self.last_project_slug else None
        try:
            had_prior_governance_ticket = bool(governance_ticket_id and get_ticket(governance_ticket_id) is not None)
        except Exception:
            had_prior_governance_ticket = False

        def _latest_review_results() -> list[AgentResult]:
            # Neuestes Ergebnis JE Rolle - bei einem Re-Check ab Versuch 2 überschreibt das
            # frische Ergebnis das ursprüngliche für die Fund-Extraktion.
            latest: dict[str, AgentResult] = {}
            for r in all_results:
                if r.agent_id in review_agent_ids and r.success and r.content:
                    latest[r.agent_id] = r
            return list(latest.values())

        for attempt in range(1, MAX_REVIEW_ITERATIONS + 1):
            if run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify("  🚫 [bold red]Budget erreicht[/bold red] – weitere Governance-Fixversuche werden übersprungen.")
                summary_lines.append(f"- 🚫 {self._budget_exceeded_label(run_start_tokens)} erreicht – Governance-Fix-Schleife nach Versuch {attempt - 1} abgebrochen.")
                break
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Governance-Fixversuche werden übersprungen.")
                summary_lines.append(f"- ⏹️ Manuell abgebrochen – Governance-Fix-Schleife nach Versuch {attempt - 1} beendet.")
                break

            if attempt == 1:
                review_results = _latest_review_results()
            else:
                # Nur relevant, wenn MAX_REVIEW_ITERATIONS per .env erhöht wurde (Standard 1
                # macht diesen Zweig nie sichtbar) - ruft dieselben Review-Rollen frisch auf,
                # um zu prüfen, ob nach dem letzten Fix-Versuch noch kritische Befunde bestehen.
                notify(f"  🔍 [yellow]Versuch {attempt}/{MAX_REVIEW_ITERATIONS}:[/yellow] Governance-Rollen prüfen den aktuellen Stand erneut...")
                recheck_tasks = [
                    AgentTask(
                        task_id=f"governance_recheck_{agent_id}_{attempt}",
                        agent_id=agent_id,
                        description=(
                            f"Prüfe den AKTUELLEN Stand des Projekts erneut auf kritische Probleme "
                            f"(Versuch {attempt}) - vorherige kritische Befunde wurden inzwischen zur "
                            f"Korrektur an die zuständigen Agenten zurückgespielt."
                        ),
                        context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                    )
                    for agent_id in sorted(review_agent_ids)
                ]
                recheck_results = await self._run_agents_parallel(recheck_tasks, notify=notify)
                all_results.extend(recheck_results)
                review_results = [r for r in recheck_results if r.success and r.content]

            findings: list[tuple[str, str]] = [
                (res.agent_id, block)
                for res in review_results
                for block in find_critical_findings(res.content)
            ]

            if not findings:
                notify("  ✅ [bold green]Keine kritischen Governance-Befunde.[/bold green]")
                summary_lines.append(
                    f"- ✅ Keine kritischen Befunde in den Governance-Reports"
                    f"{f' (Versuch {attempt})' if attempt > 1 else ''}."
                )
                if had_prior_governance_ticket and governance_ticket_id:
                    try:
                        upsert_ticket(
                            ticket_id=governance_ticket_id,
                            title=f"Ungelöster kritischer Governance-Befund: {self.last_project_slug}",
                            source="orchestrator", status="done", project_slug=self.last_project_slug,
                            detail="In einem späteren Lauf behoben - keine kritischen Befunde mehr.",
                        )
                        notify("  🎫 [dim]Ticket für vorherigen Governance-Befund als gelöst geschlossen.[/dim]")
                    except Exception as e:
                        notify(f"⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                break

            current_findings_signature = _issue_signature(findings, lambda f: (f[0], f[1][:300]))
            if _no_progress(previous_findings_signature, current_findings_signature):
                escalated_and_resolved = False
                if not escalation_attempted and not (
                    run_start_tokens is not None and (
                        self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                    )
                ):
                    escalation_attempted = True
                    stuck_agents_to_fix, _ = route_findings_to_owners(findings, file_owners)
                    stuck_owner_ids = set(stuck_agents_to_fix.keys()) & set(self._agents.keys())
                    lead_targets = {
                        dept_id for dept_id, defn in DEPARTMENT_DEFINITIONS.items()
                        if stuck_owner_ids & set(defn["members"]) and dept_id in self._dept_leads
                    }
                    findings_text = "\n\n".join(block for _agent_id, block in findings)[:3000]

                    async def _rerun_review_agents(task_prefix: str) -> list[tuple[str, str]]:
                        # Dieselbe Nur-Lese-Recheck-Logik wie beim regulären Zwischen-Versuch
                        # oben (attempt > 1) - prüft NACH der Eskalation, ob die Governance-
                        # Rollen jetzt noch etwas Kritisches melden, statt blind weiterzumachen.
                        tasks = [
                            AgentTask(
                                task_id=f"{task_prefix}_{agent_id}",
                                agent_id=agent_id,
                                description=(
                                    "Prüfe AUSSCHLIESSLICH, ob das zuvor gemeldete kritische Problem "
                                    "jetzt tatsächlich behoben ist. Melde erneut mit klarer "
                                    "Schweregrad-Markierung (\"Kritisch\"), falls es weiterhin besteht."
                                ),
                                context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                            )
                            for agent_id in sorted(review_agent_ids)
                        ]
                        results = await self._run_agents_parallel(tasks, notify=notify)
                        all_results.extend(results)
                        return [
                            (res.agent_id, block) for res in results if res.success and res.content
                            for block in find_critical_findings(res.content)
                        ]

                    if lead_targets:
                        notify(
                            f"  🔀 [bold yellow]Strategiewechsel (Eskalation):[/bold yellow] Derselbe kritische "
                            f"Governance-Befund nach einem wirkungslosen Fixversuch – ziehe Fachbereichsleiter "
                            f"({', '.join(sorted(lead_targets))}) statt derselben Wiederholung hinzu..."
                        )
                        escalation_tasks = [
                            AgentTask(
                                task_id=f"governance_escalation_{dept_id}_{attempt}",
                                agent_id=dept_id,
                                description=(
                                    "Ein vorheriger, gezielter Fixversuch deines Fachbereichs hat den folgenden "
                                    "KRITISCHEN Governance-Befund NICHT behoben (identisch vor und nach dem "
                                    "Versuch) - derselbe Ansatz hat also erkennbar nicht funktioniert. "
                                    "Analysiere das Problem aus einer anderen Perspektive und weise dein Team "
                                    f"mit einer GEÄNDERTEN Strategie an, statt denselben Fix zu wiederholen.\n\n{findings_text}"
                                ),
                                context="", project_dir=project_dir,
                            )
                            for dept_id in lead_targets
                        ]
                        fix_results = await self._run_agents_parallel(escalation_tasks, notify=notify)
                        self._update_file_owners(file_owners, fix_results)
                        all_results.extend(fix_results)
                        summary_lines.append(
                            f"- 🔀 Versuch {attempt}: kein Fortschritt beim vorherigen Fix → Eskalation an "
                            f"Fachbereichsleiter ({', '.join(sorted(lead_targets))}) mit geänderter Strategie."
                        )
                        findings = await _rerun_review_agents(f"governance_escalation_recheck_{attempt}")
                        if not findings:
                            notify("  ✅ [bold green]Eskalation erfolgreich:[/bold green] keine kritischen Governance-Befunde mehr.")
                            summary_lines.append("- ✅ Eskalation an Fachbereichsleiter behob den Befund – keine kritischen Governance-Funde mehr.")
                            if had_prior_governance_ticket and governance_ticket_id:
                                try:
                                    upsert_ticket(
                                        ticket_id=governance_ticket_id,
                                        title=f"Ungelöster kritischer Governance-Befund: {self.last_project_slug}",
                                        source="orchestrator", status="done", project_slug=self.last_project_slug,
                                        detail="In einem späteren Lauf behoben - keine kritischen Befunde mehr.",
                                    )
                                except Exception as e:
                                    notify(f"⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                            break
                        escalated_and_resolved = True  # Eskalation lief, aber weiterhin kritisch - ggf. Modell-Eskalation unten.
                        current_findings_signature = _issue_signature(findings, lambda f: (f[0], f[1][:300]))

                    if not model_escalation_attempted and stuck_owner_ids:
                        model_escalation_attempted = True
                        escalated_agent_ids = self._escalate_agent_models(stuck_owner_ids)
                        if escalated_agent_ids:
                            notify(
                                f"  ⬆️ [bold yellow]Letzter Versuch mit stärkerem Modell:[/bold yellow] "
                                f"{', '.join(sorted(escalated_agent_ids))} laufen für diesen Governance-Fix "
                                "auf HEAVY_MODEL, statt direkt aufzugeben."
                            )
                            findings_text = "\n\n".join(block for _agent_id, block in findings)[:3000]
                            model_escalation_tasks = [
                                AgentTask(
                                    task_id=f"governance_model_escalation_{owner}_{attempt}",
                                    agent_id=owner,
                                    description=(
                                        "Dein vorheriger, gezielter Fixversuch UND die Eskalation an deinen "
                                        "Fachbereichsleiter haben den folgenden KRITISCHEN Governance-Befund "
                                        "NICHT behoben - du bekommst jetzt für diesen letzten Versuch ein "
                                        f"stärkeres Modell.\n\n{findings_text}"
                                    ),
                                    context="", project_dir=project_dir,
                                )
                                for owner in sorted(escalated_agent_ids)
                            ]
                            fix_results = await self._run_agents_parallel(model_escalation_tasks, notify=notify)
                            self._update_file_owners(file_owners, fix_results)
                            all_results.extend(fix_results)
                            summary_lines.append(
                                f"- ⬆️ Versuch {attempt}: kein Fortschritt auch nach Eskalation an den "
                                f"Fachbereichsleiter → letzter Versuch mit HEAVY_MODEL für {', '.join(sorted(escalated_agent_ids))}."
                            )
                            findings = await _rerun_review_agents(f"governance_model_escalation_recheck_{attempt}")
                            if not findings:
                                notify("  ✅ [bold green]Modell-Eskalation erfolgreich:[/bold green] keine kritischen Governance-Befunde mehr.")
                                summary_lines.append("- ✅ Fix mit HEAVY_MODEL behob den Befund – keine kritischen Governance-Funde mehr.")
                                if had_prior_governance_ticket and governance_ticket_id:
                                    try:
                                        upsert_ticket(
                                            ticket_id=governance_ticket_id,
                                            title=f"Ungelöster kritischer Governance-Befund: {self.last_project_slug}",
                                            source="orchestrator", status="done", project_slug=self.last_project_slug,
                                            detail="In einem späteren Lauf behoben - keine kritischen Befunde mehr.",
                                        )
                                    except Exception as e:
                                        notify(f"⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                                break
                            escalated_and_resolved = True

                notify(
                    "  🛑 [bold red]Kein Fortschritt:[/bold red] identische kritische Befunde wie vor dem letzten "
                    f"Fixversuch{' (auch nach Eskalation an den Fachbereichsleiter/stärkeres Modell)' if escalated_and_resolved else ''} "
                    "– eröffne Backlog-Ticket, statt unverändert weiterzumachen."
                )
                summary_lines.append(
                    f"- 🛑 Versuch {attempt}: dieselben {len(findings)} kritische(n) Befund(e) wie nach dem vorherigen "
                    "Fixversuch (keine Veränderung)" + (" - auch nach Eskalation" if escalated_and_resolved else "") +
                    " – weiterer Fix-Dispatch übersprungen, Backlog-Ticket direkt eröffnet."
                )
                # Team-Optimierung (Retrospektive 2026-09-05): früher wurde dieselbe Zusammen-
                # fassung an 3 Stellen (Ticket, Lernprotokoll, Entscheidungslog) JEWEILS separat
                # auf 300 Zeichen gekürzt - für keine der drei existiert ein ungekürztes
                # Vollprotokoll wie .ai_team_status_full.log, ein hier gekürzter Governance-Fund
                # war also unwiederbringlich weg. Einmal ungekürzt berechnen, überall gleich
                # verwenden (log_decision() deckelt selbst noch auf core.decision_log.
                # MAX_DETAIL_CHARS, aber deutlich großzügiger als vorher).
                unresolved_detail = "\n\n".join(block for _agent_id, block in findings) + self._provider_exhaustion_ticket_note()
                try:
                    upsert_ticket(
                        ticket_id=f"unresolved-governance-critical-{getattr(self, 'last_project_slug', 'project')}",
                        title=f"Ungelöster kritischer Governance-Befund: {getattr(self, 'last_project_slug', 'project')}",
                        source="orchestrator", status="blocked",
                        project_slug=getattr(self, "last_project_slug", "project"),
                        detail=unresolved_detail,
                    )
                except Exception as e:
                    notify(f"⚠️ [dim yellow]Ticket für ungelösten Governance-Befund konnte nicht angelegt werden: {e}[/dim yellow]")
                record_lesson(
                    project_slug=getattr(self, "last_project_slug", "project"),
                    category="unresolved_governance_critical",
                    detail=unresolved_detail,
                )
                log_decision(project_dir, "unresolved_governance_critical_ticket_opened", unresolved_detail)
                await asyncio.to_thread(
                    notify_external, "Ungelöster kritischer Governance-Befund",
                    f"{getattr(self, 'last_project_slug', 'project')}: {unresolved_detail[:300]}",
                )
                break
            previous_findings_signature = current_findings_signature

            agents_to_fix, unrouted = route_findings_to_owners(findings, file_owners)

            if unrouted:
                shown = "; ".join(u[:150] for u in unrouted[:3])
                more = f" … und {len(unrouted) - 3} weitere" if len(unrouted) > 3 else ""
                summary_lines.append(
                    f"- ⚠️ {len(unrouted)} kritische(r) Befund(e) ohne eindeutigen Datei-Bezug "
                    f"– braucht manuelle Prüfung: {shown}{more}"
                )

            if not agents_to_fix:
                notify("  ⚠️ [yellow]Kritische Governance-Befunde konnten keinem Agenten eindeutig zugeordnet werden – Auto-Fix übersprungen.[/yellow]")
                break

            # Team-Retrospektive nach dem zeiterfassung_app-Lauf: dieselbe Fehlerklasse (fehlendes
            # lokales Modul/Paket, z.B. `app/routers/`) wurde hier vom LLM-Reviewer als Freitext-
            # Befund gemeldet UND wenig später vom rein statischen Vorab-Import-Check in
            # _run_verification_loop erneut gefunden - zwei getrennte, unkoordinierte Fix-Budgets
            # für denselben Defekt. Reichert den Freitext-Befund hier zusätzlich um die exakte,
            # dateigenaue Fundliste des statischen Checks an (Datei:Zeile + erwarteter Pfad statt
            # nur Prosa) - derselbe check_completeness()-Aufruf wie beim Vorab-Import-Check, hier
            # nur zusätzlich in den Fix-Prompt gemischt, läuft rein lokal (Millisekunden, kein
            # LLM-Aufruf) und kostet daher kein zusätzliches Budget.
            # Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive, echter Fund
            # am event_relay-Lauf 2026-09-06): dieser Filter nutzte bisher dieselbe fragile
            # Substring-Suche `"existierendes lokales" in message` wie der Vorab-Import-Check
            # unten - core/verifier/models.py.CompletenessIssue.kind ersetzt das durch ein
            # stabiles, maschinenlesbares Tag (siehe dessen Docstring für den vollen Kontext,
            # inkl. des `resilience`-Imports, den die alte Substring-Suche verpasste).
            try:
                structural_report = ProjectVerifier(project_dir).check_completeness()
                structural_import_issues = [
                    i for i in structural_report.issues if i.kind == "missing_local_import"
                ] if structural_report.attempted else []
            except Exception:
                structural_import_issues = []

            fix_tasks = []
            for agent_id, texts in agents_to_fix.items():
                finding_text = "\n\n".join(texts)[:3000]
                owned_import_issues = [
                    i for i in structural_import_issues if file_owners.get(i.file_path) == agent_id
                ] or structural_import_issues
                structural_addendum = ""
                if owned_import_issues:
                    exact_list = "\n".join(
                        f"- {i.file_path}:{i.line_number} – {i.message}" for i in owned_import_issues[:10]
                    )
                    structural_addendum = (
                        "\n\nZUSÄTZLICH ein statischer Check derselben Fehlerklasse (fehlendes "
                        "lokales Modul/Paket) mit der EXAKTEN Datei-Liste - lege GENAU diese "
                        f"Dateien/Symbole an, nicht nur sinngemäß:\n{exact_list}"
                    )
                fix_tasks.append(AgentTask(
                    task_id=f"governance_fix_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        f"Das Governance-Review (code_reviewer/security/compliance) hat ein "
                        f"KRITISCHES Problem in deinem Code gefunden. Nutze read_file, um die "
                        f"betroffene(n) Datei(en) zu prüfen, und edit_file/write_file, um das "
                        f"Problem zu beheben.\n\n{finding_text}{structural_addendum}"
                        + (_prior_run_context(governance_ticket_id) if attempt == 1 and governance_ticket_id else "")
                    ),
                    context="", project_dir=project_dir,
                ))

            notify(f"  🛠️ [bold yellow]Governance-Fix:[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())} mit {len(findings)} kritischem/kritischen Befund(en)...")
            log_decision(
                project_dir, "governance_fix_dispatched",
                f"Versuch {attempt}: {len(findings)} kritische(r) Befund(e) → {', '.join(agents_to_fix.keys())}",
            )
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(
                f"- 🛠️ Versuch {attempt}: {len(findings)} kritische(r) Governance-Befund(e) → gezielt "
                f"zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt (der Fix wird NICHT "
                f"erneut vom Reviewer bestätigt – das übernimmt für automatisiert testbares Verhalten "
                f"nur die anschließende echte Testverifikation, nicht die qualitative Review-Aussage selbst)."
            )

            # Proaktives Pro-Task-Budget (Punkt 2 einer Team-Retrospektive): ein einzelner
            # ausufernder Fix-Task konnte bisher unbemerkt einen unverhältnismäßig großen Teil
            # des GESAMTEN Lauf-Budgets verbrauchen, bevor spätere Fachbereiche überhaupt an der
            # Reihe waren. Kein Abbruch mitten im laufenden Aufruf (technisch nicht sauber
            # möglich), aber ein klares Warnsignal, das WEITERE Versuche für denselben Befund in
            # dieser Schleife stoppt, statt ungebremst weiterzueskalieren.
            oversized = [r for r in fix_results if MAX_TASK_TOKENS > 0 and r.total_tokens > MAX_TASK_TOKENS]
            if oversized:
                names = ", ".join(sorted({r.agent_id for r in oversized}))
                notify(f"  🚫 [bold red]Pro-Task-Budget überschritten[/bold red] ({names}) – weitere Governance-Fixversuche für diesen Befund werden übersprungen.")
                summary_lines.append(
                    f"- 🚫 Pro-Task-Budget ({MAX_TASK_TOKENS:,} Tokens) von {names} überschritten – "
                    f"Governance-Fix-Schleife nach Versuch {attempt} beendet, statt unbegrenzt weiter zu eskalieren."
                )
                break

            if attempt == MAX_REVIEW_ITERATIONS:
                # Verpflichtender Re-Review nach dem letzten Fix-Dispatch (Punkt 4 einer
                # Team-Retrospektive): bisher wurde der Fix im letzten erlaubten Versuch NIE mehr
                # gegengeprüft (nur Zwischen-Versuche liefen in eine erneute Runde mit Recheck
                # oben) - ein Fix im finalen Versuch galt damit unbesehen als erledigt, selbst bei
                # sicherheitskritischen Befunden. Ein einzelner, günstiger Nur-Lese-Recheck
                # derselben Rollen schließt diese Lücke; bleibt der Befund bestehen, wird ein
                # Backlog-Ticket für menschliche Prüfung eröffnet statt stillschweigend zu
                # akzeptieren.
                notify(f"  🔍 [yellow]Verpflichtender Re-Review nach Versuch {attempt}:[/yellow] prüft, ob der Fix tatsächlich griff...")
                final_recheck_tasks = [
                    AgentTask(
                        task_id=f"governance_final_recheck_{agent_id}",
                        agent_id=agent_id,
                        description=(
                            "Prüfe AUSSCHLIESSLICH, ob das zuvor gemeldete kritische Problem jetzt "
                            "tatsächlich behoben ist. Melde erneut mit klarer Schweregrad-Markierung "
                            "(\"Kritisch\"), falls es weiterhin besteht."
                        ),
                        context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                    )
                    for agent_id in sorted(agents_to_fix.keys() & review_agent_ids)
                ] or [
                    AgentTask(
                        task_id=f"governance_final_recheck_{agent_id}",
                        agent_id=agent_id,
                        description="Prüfe den aktuellen Stand des Projekts erneut auf kritische Probleme.",
                        context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                    )
                    for agent_id in sorted(review_agent_ids)
                ]
                final_recheck_results = await self._run_agents_parallel(final_recheck_tasks, notify=notify)
                all_results.extend(final_recheck_results)
                still_critical = [
                    block for res in final_recheck_results if res.success and res.content
                    for block in find_critical_findings(res.content)
                ]
                # Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive, echter
                # Fund am event_relay-Lauf 2026-09-06): der Re-Review oben verlässt sich AUSSCHLIESSLICH
                # auf die Einschätzung des LLM-Reviewers - genau das akzeptierte real einen Fix
                # als erledigt ("Resilience-Manager verdrahtet"), der dabei einen frischen,
                # garantierten `ImportError` einführte (`from app.resilience import resilience`,
                # obwohl die globale Instanz im selben Fix entfernt wurde). Der Bruch fiel erst im
                # NÄCHSTEN, unabhängigen Lauf per echtem pytest auf. check_completeness() erkennt
                # genau diese Fund-Klasse bereits rein lokal (kein LLM-Aufruf, keine zusätzlichen
                # Kosten) - läuft deshalb HIER zusätzlich als harte, deterministische Gegenprobe:
                # ein struktureller Neu-Bruch gilt als weiterhin kritisch, UNABHÄNGIG davon, ob
                # der LLM-Re-Review ihn bemerkt hat.
                try:
                    structural_recheck = ProjectVerifier(project_dir).check_completeness()
                    structural_still_critical = [
                        f"Statischer Check (ohne LLM-Bewertung): {i.file_path}:{i.line_number} – {i.message}"
                        for i in structural_recheck.issues if i.kind == "missing_local_import"
                    ] if structural_recheck.attempted else []
                except Exception:
                    structural_still_critical = []
                if structural_still_critical:
                    notify(f"  🧩 [bold red]Struktureller Neu-Bruch:[/bold red] {len(structural_still_critical)} lokale(r) Import(e) nach dem Fix nicht auflösbar - unabhängig vom LLM-Re-Review als weiterhin kritisch gewertet.")
                still_critical = still_critical + structural_still_critical

                # Team-Optimierung (Fortsetzung der Analyse 2026-09-06, echter Fund am
                # event_relay-Lauf): der `_no_progress()`-Zirkuit-Breaker oben eskaliert nur bei
                # EXAKT WIEDERHOLTEM Befund - real blieb ein Fixversuch beim zweiten Fund derselben
                # Ursache aber eine ANDERE Symptomatik zurück (Versuch 1: "ResilienceManager nicht
                # verdrahtet" → Versuch 2, nach dem Fix: "ImportError: `resilience` keine globale
                # Instanz mehr"), sodass `_no_progress()` NIE griff und der verpflichtende
                # Re-Review hier direkt ein Ticket eröffnete, OHNE je den Fachbereichsleiter mit
                # einer geänderten Strategie zu versuchen - dieselbe Eskalationsleiter wie oben,
                # nur ohne die Modell-Eskalation (die bräuchte einen echten Provider-Client, siehe
                # core/llm_factory.py.LLMFactory.create_for_model() - hier bewusst nicht riskiert,
                # das ist bereits über den Zirkuit-Breaker-Pfad oben abgedeckt).
                if still_critical and not escalation_attempted and not (
                    run_start_tokens is not None and (
                        self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                    )
                ):
                    escalation_attempted = True
                    stuck_owner_ids = set(agents_to_fix.keys()) & set(self._agents.keys())
                    lead_targets = {
                        dept_id for dept_id, defn in DEPARTMENT_DEFINITIONS.items()
                        if stuck_owner_ids & set(defn["members"]) and dept_id in self._dept_leads
                    }
                    if lead_targets:
                        still_critical_text = "\n\n".join(still_critical)[:3000]
                        notify(
                            f"  🔀 [bold yellow]Strategiewechsel (Eskalation):[/bold yellow] Der "
                            f"verpflichtende Re-Review meldet nach dem letzten Fixversuch weiterhin "
                            f"ein kritisches Problem (ggf. eine andere Symptomatik derselben Ursache) "
                            f"– ziehe Fachbereichsleiter ({', '.join(sorted(lead_targets))}) hinzu, "
                            "statt direkt ein Ticket zu eröffnen..."
                        )
                        escalation_tasks = [
                            AgentTask(
                                task_id=f"governance_final_escalation_{dept_id}",
                                agent_id=dept_id,
                                description=(
                                    "Der verpflichtende Abschluss-Review meldet nach dem letzten "
                                    "Fixversuch deines Fachbereichs WEITERHIN ein kritisches Problem "
                                    "(ggf. eine andere Symptomatik derselben Ursache, statt exakt "
                                    "desselben Befunds) - derselbe Ansatz hat also erkennbar nicht "
                                    "ausgereicht. Analysiere das Problem aus einer anderen "
                                    "Perspektive und weise dein Team mit einer GEÄNDERTEN Strategie "
                                    f"an.\n\n{still_critical_text}"
                                ),
                                context="", project_dir=project_dir,
                            )
                            for dept_id in lead_targets
                        ]
                        fix_results = await self._run_agents_parallel(escalation_tasks, notify=notify)
                        self._update_file_owners(file_owners, fix_results)
                        all_results.extend(fix_results)
                        summary_lines.append(
                            f"- 🔀 Nach {MAX_REVIEW_ITERATIONS} Versuch(en) weiterhin kritisch (andere "
                            f"Symptomatik) → Eskalation an Fachbereichsleiter "
                            f"({', '.join(sorted(lead_targets))}) vor der Ticket-Eröffnung."
                        )
                        escalation_recheck_agents = sorted(set(agents_to_fix.keys()) & review_agent_ids) or sorted(review_agent_ids)
                        escalation_recheck_tasks = [
                            AgentTask(
                                task_id=f"governance_final_escalation_recheck_{agent_id}",
                                agent_id=agent_id,
                                description=(
                                    "Prüfe AUSSCHLIESSLICH, ob das zuvor gemeldete kritische Problem "
                                    "jetzt tatsächlich behoben ist. Melde erneut mit klarer "
                                    "Schweregrad-Markierung (\"Kritisch\"), falls es weiterhin besteht."
                                ),
                                context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                            )
                            for agent_id in escalation_recheck_agents
                        ]
                        escalation_recheck_results = await self._run_agents_parallel(escalation_recheck_tasks, notify=notify)
                        all_results.extend(escalation_recheck_results)
                        still_critical = [
                            block for res in escalation_recheck_results if res.success and res.content
                            for block in find_critical_findings(res.content)
                        ]
                        try:
                            structural_after_escalation = ProjectVerifier(project_dir).check_completeness()
                            still_critical += [
                                f"Statischer Check (ohne LLM-Bewertung): {i.file_path}:{i.line_number} – {i.message}"
                                for i in structural_after_escalation.issues if i.kind == "missing_local_import"
                            ] if structural_after_escalation.attempted else []
                        except Exception:
                            pass
                        if still_critical:
                            summary_lines.append(
                                "- 🛑 Eskalation an Fachbereichsleiter behob den Befund NICHT – "
                                "weiterhin kritisch."
                            )
                        else:
                            notify("  ✅ [bold green]Eskalation erfolgreich:[/bold green] keine kritischen Governance-Befunde mehr.")
                            summary_lines.append("- ✅ Eskalation an Fachbereichsleiter (nach dem verpflichtenden Re-Review) behob den Befund – keine kritischen Governance-Funde mehr.")

                if still_critical:
                    notify("  🛑 [bold red]Fix nicht bestätigt:[/bold red] Re-Review meldet weiterhin kritische Befunde – Backlog-Ticket für menschliche Prüfung eröffnet.")
                    summary_lines.append(
                        f"- 🛑 Nach {MAX_REVIEW_ITERATIONS} Versuch(en) bestätigt der Re-Review WEITERHIN "
                        f"{len(still_critical)} kritische(n) Befund(e) – Backlog-Ticket eröffnet statt "
                        "stillschweigend zu übernehmen."
                    )
                    still_critical_detail = "\n\n".join(still_critical) + self._provider_exhaustion_ticket_note()
                    # Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, echte PR-Review-
                    # Kommentare): dieselben still_critical-Blöcke, die gerade als Fließtext im
                    # Backlog-Ticket landen, werden hier ZUSÄTZLICH in ReviewFinding-Objekte
                    # (mit best-effort extrahiertem file_path) umgewandelt und am Orchestrator
                    # gespeichert - interface/cli.py._ask_for_git_push()/core/backlog_worker.py
                    # lesen dieses Attribut nach einem erfolgreichen create_pull_request() und
                    # hinterlassen echte, dateibezogene GitHub-Review-Kommentare am PR
                    # (agents/github_agent.py.post_pr_review()), statt den Befund nur im PR-Body
                    # zu verstecken, wo ihn ein menschlicher Reviewer leicht überliest.
                    self.last_unresolved_review_findings.extend(
                        finding_from_critical_block(block) for block in still_critical
                    )
                    try:
                        upsert_ticket(
                            ticket_id=f"unresolved-governance-critical-{getattr(self, 'last_project_slug', 'project')}",
                            title=f"Ungelöster kritischer Governance-Befund: {getattr(self, 'last_project_slug', 'project')}",
                            source="orchestrator", status="blocked",
                            project_slug=getattr(self, "last_project_slug", "project"),
                            detail=still_critical_detail,
                        )
                    except Exception as e:
                        notify(f"⚠️ [dim yellow]Ticket für ungelösten Governance-Befund konnte nicht angelegt werden: {e}[/dim yellow]")
                    record_lesson(
                        project_slug=getattr(self, "last_project_slug", "project"),
                        category="unresolved_governance_critical",
                        detail=still_critical_detail,
                    )
                    log_decision(project_dir, "unresolved_governance_critical_ticket_opened", still_critical_detail)
                    await asyncio.to_thread(
                        notify_external, "Ungelöster kritischer Governance-Befund",
                        f"{getattr(self, 'last_project_slug', 'project')}: {still_critical_detail[:300]}",
                    )
                else:
                    summary_lines.append(f"- ✅ Re-Review nach Versuch {attempt} bestätigt: keine kritischen Befunde mehr.")

        summary = (
            "### 🔍 Governance-Fix-Protokoll (kritische Review-Befunde)\n" + "\n".join(summary_lines)
            if summary_lines else ""
        )
        return all_results, summary, budget_aborted, manually_cancelled

    async def _run_permission_blocked_clarification_fix(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[AgentResult], str, bool, bool]:
        """
        Realer Fund (omnichat-Projekt): der security-Agent identifizierte ein echtes kritisches
        Problem (Pydantic-v2-Migration in `app/schemas.py`, CORS-Härtung in `app/main.py`), hatte
        in diesem Aufruf aber keine Schreibrechte und griff statt zu einem normalen, per
        `find_critical_findings` erkennbaren "Kritisch"-Bericht zu `ask_human_for_clarification`
        mit der Frage "Wie erhalte ich Schreibrechte...?". Diese Frage landete unbeantwortet in
        .ai_team_status.json (open_questions) und wurde NIE an einen schreibberechtigten Agenten
        weitergeroutet - anders als bei _run_governance_fix_loop oben blieb das Problem so über
        beliebig viele Läufe hinweg ungelöst liegen, obwohl der Fund selbst konkret und lösbar
        war. Läuft direkt NACH der Governance-Fix-Schleife (dieselbe Reihenfolge-Logik: vor der
        echten Testverifikation, damit die Testsuite den reparierten Stand prüft) und nutzt
        dieselbe core/review_gate.py.route_findings_to_owners()-Zuordnung wie dort - der
        Fund-Text ist hier die Rückfrage selbst statt eines Review-Abschnitts.

        Gibt (all_results, summary, budget_aborted, manually_cancelled) zurück - summary ist ""
        bei nichts zu tun (kein Rauschen im Normalfall).
        """
        blocked: list[tuple[str, str, AgentResult]] = []
        for res in all_results:
            if not res.clarification_questions:
                continue
            for q in find_permission_blocked_questions(res.clarification_questions):
                blocked.append((res.agent_id, q, res))

        if not blocked:
            return all_results, "", False, False

        if run_start_tokens is not None and (
            self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
        ):
            notify("  🚫 [bold red]Budget erreicht[/bold red] – Fix für schreibgeschützt blockierte Rückfragen übersprungen.")
            return all_results, "", True, False
        if cancel_requested and cancel_requested():
            notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – Fix für schreibgeschützt blockierte Rückfragen übersprungen.")
            return all_results, "", False, True

        findings = [(agent_id, q) for agent_id, q, _res in blocked]
        agents_to_fix, unrouted = route_findings_to_owners(findings, file_owners)

        summary_lines: list[str] = []
        if unrouted:
            shown = "; ".join(u[:150] for u in unrouted[:3])
            more = f" … und {len(unrouted) - 3} weitere" if len(unrouted) > 3 else ""
            summary_lines.append(
                f"- ⚠️ {len(unrouted)} schreibgeschützt blockierte Rückfrage(n) ohne eindeutigen "
                f"Datei-Bezug – braucht manuelle Prüfung: {shown}{more}"
            )

        if agents_to_fix:
            fix_tasks = []
            for agent_id, texts in agents_to_fix.items():
                finding_text = "\n\n".join(texts)[:3000]
                fix_tasks.append(AgentTask(
                    task_id=f"permission_blocked_fix_{agent_id}",
                    agent_id=agent_id,
                    description=(
                        f"Ein anderer Agent hat ein konkretes Problem identifiziert, konnte es aber wegen "
                        f"fehlender Schreibrechte NICHT selbst beheben. Nutze read_file, um die betroffene(n) "
                        f"Datei(en) zu prüfen, und edit_file/write_file, um das Problem wirklich zu "
                        f"beheben.\n\n{finding_text}"
                    ),
                    context="", project_dir=project_dir,
                ))
            notify(f"  🛠️ [bold yellow]Schreibgeschützt blockierte Rückfrage(n):[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())} mit {len(agents_to_fix)} Fund(en)...")
            log_decision(
                project_dir, "permission_blocked_fix_dispatched",
                f"{len(agents_to_fix)} blockierte Rückfrage(n) → {', '.join(agents_to_fix.keys())}",
            )
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(
                f"- 🛠️ {len(blocked) - len(unrouted)} schreibgeschützt blockierte Rückfrage(n) → gezielt "
                f"zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt (keine unbeantwortete "
                f"Rückfrage mehr im Abschlussbericht)."
            )

            # Dasselbe Pro-Task-Budget-Warnsignal wie in _run_governance_fix_loop oben (Punkt 2
            # einer Team-Retrospektive) - auch hier kann ein einzelner Fix-Task ausufern.
            oversized = [r for r in fix_results if MAX_TASK_TOKENS > 0 and r.total_tokens > MAX_TASK_TOKENS]
            if oversized:
                names = ", ".join(sorted({r.agent_id for r in oversized}))
                notify(f"  🚫 [bold red]Pro-Task-Budget überschritten[/bold red] ({names}).")
                summary_lines.append(f"- 🚫 Pro-Task-Budget ({MAX_TASK_TOKENS:,} Tokens) von {names} überschritten.")

            # Behobene Fragen aus dem Abschlussbericht entfernen (open_questions), damit sie nicht
            # trotz erfolgtem Fix als unbeantwortet im Status/PROJECT_STATE.md landen - eine echte
            # fachliche Rückfrage im selben Ergebnis (falls vorhanden) bleibt davon unberührt.
            # `unrouted`-Einträge tragen dasselbe "[agent_id] text"-Format wie
            # route_findings_to_owners() sie selbst erzeugt (core/review_gate.py) - so lässt sich
            # ohne eigene Owner-Neuberechnung feststellen, welche der ursprünglichen Fragen
            # tatsächlich geroutet (= gerade gefixt) statt unrouted geblieben sind.
            unrouted_set = set(unrouted)
            fixed_raiser_ids: set[str] = set()
            for agent_id, q, res in blocked:
                if f"[{agent_id}] {q.strip()}" in unrouted_set:
                    continue
                if q in res.clarification_questions:
                    res.clarification_questions.remove(q)
                    fixed_raiser_ids.add(res.agent_id)

            # Verpflichtender Re-Review (Punkt 4 einer Team-Retrospektive, analog zum finalen
            # Recheck in _run_governance_fix_loop): der ursprünglich blockierte Agent (z.B.
            # security) prüft den nun schreibbaren Fix noch einmal read-only nach, statt den
            # Fix-Dispatch ungeprüft als erledigt zu behandeln - genau die Lücke, die im echten
            # omnichat-Fund dazu führte, dass niemand je bestätigte, ob CORS/Pydantic-v2
            # tatsächlich behoben wurden.
            if fixed_raiser_ids and not oversized:
                notify(f"  🔍 [yellow]Verpflichtender Re-Review:[/yellow] {', '.join(sorted(fixed_raiser_ids))} prüft den Fix nach...")
                recheck_tasks = [
                    AgentTask(
                        task_id=f"permission_blocked_recheck_{raiser_id}",
                        agent_id=raiser_id,
                        description=(
                            "Prüfe, ob das von dir zuvor gemeldete Problem (das du mangels "
                            "Schreibrechten nicht selbst beheben konntest) jetzt tatsächlich behoben "
                            "ist. Melde mit klarer Schweregrad-Markierung (\"Kritisch\"), falls nicht."
                        ),
                        context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                    )
                    for raiser_id in sorted(fixed_raiser_ids)
                    if raiser_id in self._agents or raiser_id in self._dept_leads
                ]
                recheck_results = await self._run_agents_parallel(recheck_tasks, notify=notify)
                all_results.extend(recheck_results)
                still_critical = [
                    block for res in recheck_results if res.success and res.content
                    for block in find_critical_findings(res.content)
                ]
                if still_critical:
                    notify("  🛑 [bold red]Fix nicht bestätigt:[/bold red] Re-Review meldet weiterhin ein kritisches Problem – Backlog-Ticket eröffnet.")
                    summary_lines.append(
                        f"- 🛑 Re-Review bestätigt den Fix NICHT – {len(still_critical)} weiterhin kritische(r) "
                        "Befund(e). Backlog-Ticket für menschliche Prüfung eröffnet."
                    )
                    still_critical_detail = "\n\n".join(still_critical) + self._provider_exhaustion_ticket_note()
                    # Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, echte PR-Review-
                    # Kommentare) - siehe die ausführliche Begründung bei der Schwester-Stelle in
                    # _run_governance_fix_loop() oben.
                    self.last_unresolved_review_findings.extend(
                        finding_from_critical_block(block) for block in still_critical
                    )
                    try:
                        upsert_ticket(
                            ticket_id=f"unresolved-permission-blocked-{getattr(self, 'last_project_slug', 'project')}",
                            title=f"Ungelöster, zuvor schreibgeschützt blockierter Befund: {getattr(self, 'last_project_slug', 'project')}",
                            source="orchestrator", status="blocked",
                            project_slug=getattr(self, "last_project_slug", "project"),
                            detail=still_critical_detail,
                        )
                    except Exception as e:
                        notify(f"⚠️ [dim yellow]Ticket konnte nicht angelegt werden: {e}[/dim yellow]")
                    record_lesson(
                        project_slug=getattr(self, "last_project_slug", "project"),
                        category="unresolved_permission_blocked_fix",
                        detail=still_critical_detail,
                    )
                    log_decision(project_dir, "unresolved_permission_blocked_fix_ticket_opened", still_critical_detail)
                    await asyncio.to_thread(
                        notify_external, "Ungelöster, zuvor schreibgeschützt blockierter Befund",
                        f"{getattr(self, 'last_project_slug', 'project')}: {still_critical_detail[:300]}",
                    )
                else:
                    summary_lines.append("- ✅ Re-Review bestätigt: Fix erfolgreich.")

        summary = (
            "### 🔓 Fix-Protokoll (schreibgeschützt blockierte Rückfragen)\n" + "\n".join(summary_lines)
            if summary_lines else ""
        )
        return all_results, summary, False, False

    async def _run_scope_clarification_autofix(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[AgentResult], str, bool, bool]:
        """
        Realer Fund (incidentpilot-Projekt): der tester-Agent stellte eine echte fachliche
        Scope-Rückfrage ("Soll ich die Grundstruktur der Anwendung ... von Grund auf neu
        erstellen, da ich kein 'app/'-Verzeichnis sehe?") statt sie autonom zu beantworten und
        weiterzuarbeiten. Anders als eine Schreibrechte-Rückfrage (siehe
        _run_permission_blocked_clarification_fix oben) passt hier KEIN Muster von
        find_permission_blocked_questions() - die Frage blieb deshalb unbeantwortet in
        .ai_team_status.json (open_questions) stehen, und der Lauf endete mit
        verification_ok=False, OHNE dass die eigentliche Kernfunktion je gebaut wurde, obwohl
        Architektur/ADRs/OpenAPI-Spezifikation für das Projekt bereits vollständig vorlagen.

        Das Team hat keinen anwesenden Menschen, der eine solche Rückfrage in Echtzeit
        beantworten könnte - der einzig sinnvolle Default ist, dass der fragende Agent selbst
        die naheliegendste Annahme trifft (z.B. "ja, lege die fehlende Struktur selbst an") und
        die Aufgabe zu Ende bringt, statt den Lauf unbeantwortet stehen zu lassen. Läuft NACH
        der Schreibrechte-Fix-Schleife (die spezifischere, bereits behandelte Fälle vorher
        herausfiltert), aus demselben Grund wie dort: vor der echten Testverifikation, damit
        die Testsuite den vervollständigten Stand prüft.

        Nutzt bewusst find_structural_scope_questions() (eine enge ALLOWLIST, siehe deren
        Docstring in core/review_gate.py) statt "alles außer Schreibrechte-Fragen" - eine echte
        fachliche Unklarheit, die nur ein Mensch beantworten kann (z.B. "Welche Zahlungsanbieter
        sollen unterstützt werden?"), MUSS weiterhin unangetastet zur Mid-Task-Eskalation an
        einen Menschen führen (core/agent_toolbox.py.ask_human_for_clarification, siehe
        tests/test_clarification_escalation.py) - sonst würde diese Funktion genau die
        Eskalation unterlaufen, die sie eigentlich ergänzen soll.

        Gibt (all_results, summary, budget_aborted, manually_cancelled) zurück - summary ist ""
        bei nichts zu tun (kein Rauschen im Normalfall, in dem gar keine Rückfrage offen ist).
        """
        remaining: list[tuple[str, str, AgentResult]] = []
        for res in all_results:
            if not res.clarification_questions:
                continue
            in_scope = set(find_structural_scope_questions(res.clarification_questions))
            for q in res.clarification_questions:
                if q in in_scope:
                    remaining.append((res.agent_id, q, res))

        if not remaining:
            return all_results, "", False, False

        if run_start_tokens is not None and (
            self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
        ):
            notify("  🚫 [bold red]Budget erreicht[/bold red] – Auto-Entscheid für offene Rückfragen übersprungen.")
            return all_results, "", True, False
        if cancel_requested and cancel_requested():
            notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – Auto-Entscheid für offene Rückfragen übersprungen.")
            return all_results, "", False, True

        # Je fragendem Agent EINE Sammel-Aufgabe (nicht pro Frage einzeln) - dieselbe Bündelung
        # wie route_findings_to_owners() bei Governance-Funden.
        by_agent: dict[str, list[str]] = {}
        for agent_id, q, _res in remaining:
            if agent_id in self._agents or agent_id in self._dept_leads:
                by_agent.setdefault(agent_id, []).append(q.strip())

        if not by_agent:
            return all_results, "", False, False

        fix_tasks = [
            AgentTask(
                task_id=f"scope_clarification_autofix_{agent_id}",
                agent_id=agent_id,
                description=(
                    "Du hast zuvor eine offene fachliche Rückfrage gestellt, statt direkt "
                    "weiterzuarbeiten. Es ist KEIN Mensch verfügbar, der diese Rückfrage in "
                    "Echtzeit beantworten kann - das Team arbeitet autonom. Triff selbst die "
                    "naheliegendste, sinnvollste Annahme (z.B.: fehlende Grundstruktur/Dateien "
                    "einfach selbst anlegen, statt zu fragen, ob du das darfst) und setze die "
                    "Aufgabe VOLLSTÄNDIG um. Dokumentiere die getroffene Annahme kurz als "
                    "Kommentar im Code oder in einer README-Sektion.\n\n"
                    "Deine offene(n) Rückfrage(n):\n" + "\n".join(f"- {q}" for q in questions)
                ),
                context="", project_dir=project_dir,
            )
            for agent_id, questions in by_agent.items()
        ]

        notify(
            f"  🧭 [bold yellow]Offene Scope-Rückfrage(n):[/bold yellow] Kein Mensch verfügbar – "
            f"{', '.join(by_agent.keys())} entscheidet/entscheiden autonom und baut/bauen weiter..."
        )
        log_decision(
            project_dir, "scope_clarification_autofix_dispatched",
            f"{len(remaining)} offene Rückfrage(n) → {', '.join(by_agent.keys())}",
        )
        fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
        self._update_file_owners(file_owners, fix_results)
        all_results.extend(fix_results)

        # Beantwortete Rückfragen aus dem ursprünglichen Ergebnis entfernen, damit sie nicht
        # trotz Auto-Entscheid weiterhin als unbeantwortet im Abschlussbericht/PROJECT_STATE.md
        # auftauchen - dieselbe Bereinigung wie in _run_permission_blocked_clarification_fix.
        resolved_agent_ids = set(by_agent.keys())
        for agent_id, q, res in remaining:
            if agent_id in resolved_agent_ids and q in res.clarification_questions:
                res.clarification_questions.remove(q)

        summary = (
            "### 🧭 Auto-Entscheid-Protokoll (offene Scope-Rückfragen ohne verfügbaren Menschen)\n"
            f"- 🧭 {len(remaining)} offene fachliche Rückfrage(n) von {', '.join(sorted(resolved_agent_ids))} "
            f"autonom mit der naheliegendsten Annahme weiterbearbeitet, statt den Lauf unbeantwortet enden zu lassen."
        )
        return all_results, summary, False, False

    async def _run_smoke_test_gate(
        self,
        verifier: ProjectVerifier,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
    ) -> list[str]:
        """
        Prüft VOR der Testschleife, ob die erzeugte Anwendung überhaupt startet, und lässt einen
        Startfehler gezielt beheben, bevor Zeit und Token in eine vollständige Testsuite fließen.

        Gibt die Zeilen zurück, die ins Verifikations-Protokoll aufgenommen werden sollen.

        Bewusst höchstens EIN Fixversuch: Das Gate soll den häufigsten und teuersten Fall früh
        abfangen (App startet gar nicht), nicht die eigentliche Fix-Schleife duplizieren. Bleibt
        der Start danach kaputt, läuft die reguläre Testschleife trotzdem an - sie sieht denselben
        Fehler dann erneut und hat ihre eigene, mehrstufige Eskalationsleiter dafür.
        """
        summary: list[str] = []
        try:
            report = await asyncio.to_thread(verifier.check_runtime_smoke)
        except Exception as e:
            # Ein Smoke-Test ist eine Zusatzabsicherung - fällt er selbst aus, darf das die
            # reguläre Verifikation nicht verhindern.
            notify(f"  ⚠️ [dim yellow]Smoke-Test-Gate übersprungen ({type(e).__name__}).[/dim yellow]")
            return summary

        if not report.attempted:
            # Kein erkennbarer Einstiegspunkt (z.B. reine Bibliothek) - kein Fehler, nur nicht prüfbar.
            return summary
        if report.passed:
            notify("  ✅ [green]Smoke-Test-Gate:[/green] Die Anwendung startet.")
            summary.append(f"- 🚦 Smoke-Test-Gate bestanden (`{report.entrypoint}` startet).")
            return summary

        fehlertext = (report.output or "").strip()
        notify(
            f"  🚦 [bold red]Smoke-Test-Gate: Die Anwendung startet nicht[/bold red] "
            f"(`{report.entrypoint}`) – behebe das VOR der Testsuite."
        )
        summary.append(
            f"- 🚦 ❌ Smoke-Test-Gate: `{report.entrypoint}` startet nicht – gezielter Fix vor der Testsuite."
        )
        log_decision(project_dir, "smoke_test_gate_failed", fehlertext[:500])

        # Zuständigkeit über die bekannten Datei-Eigentümer bestimmen; ohne Zuordnung übernimmt
        # der backend-Agent, weil ein nicht startender Einstiegspunkt fast immer dort liegt.
        owner = file_owners.get(report.entrypoint or "", "") or "backend"
        if owner not in self._agents:
            owner = "backend"
        if owner not in self._agents:
            return summary

        fix_tasks = [AgentTask(
            task_id=f"smoke-gate-fix-{owner}",
            agent_id=owner,
            description=(
                "🚦 KRITISCH – die Anwendung startet überhaupt nicht. Solange das so ist, ist "
                "jeder Test wertlos, weil ausnahmslos alle Tests an derselben Ursache scheitern.\n\n"
                f"Einstiegspunkt: `{report.entrypoint}`\n"
                f"Art der Anwendung: {report.app_type or 'unbekannt'}\n\n"
                "ECHTE Fehlerausgabe des Startversuchs:\n"
                f"```\n{fehlertext[:3000]}\n```\n\n"
                "Behebe AUSSCHLIESSLICH die Ursache dieses Startfehlers (fehlender Import, "
                "Syntaxfehler, falscher Modulpfad, fehlende Abhängigkeit in requirements.txt, "
                "Konfigurationsfehler beim Start). Schreibe KEINE neuen Features und KEINE Tests. "
                "Prüfe deine Korrektur, indem du den Einstiegspunkt tatsächlich importierst bzw. "
                "startest."
            ),
            context="",
            project_dir=project_dir,
        )]
        fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
        self._update_file_owners(file_owners, fix_results)
        all_results.extend(fix_results)

        try:
            recheck = await asyncio.to_thread(verifier.check_runtime_smoke)
        except Exception:
            return summary

        if recheck.passed:
            notify("  ✅ [green]Smoke-Test-Gate:[/green] Startfehler behoben – weiter mit der Testsuite.")
            summary.append(f"- 🚦 ✅ Startfehler durch `{owner}` behoben – die Anwendung startet jetzt.")
        else:
            notify(
                "  ⚠️ [yellow]Smoke-Test-Gate: Start weiterhin fehlerhaft – die reguläre "
                "Testschleife übernimmt.[/yellow]"
            )
            summary.append(
                f"- 🚦 ⚠️ Startfehler durch `{owner}` NICHT behoben – die reguläre Testschleife übernimmt."
            )
        return summary

    async def _run_tests_logged(self, verifier: ProjectVerifier, phase: str) -> VerificationReport:
        """
        Führt die echte Testsuite aus und schreibt deren ROHE Ausgabe (stdout+stderr) in das
        Verifikations-Log dieses Laufs (core/run_logger.py).

        Realer Fund (KI-Team-Masterplan-Analyse): In den Bericht wandert nur eine stark gekürzte
        Zusammenfassung ("⚠️ pip install -r requirements.txt (exit_code=1)"). Die eigentliche
        Fehlerausgabe - also genau das, was ein Mensch zum Debuggen braucht - existierte nach
        Ende des Laufs nirgends mehr, weil `logs/` leer blieb und die rich-Konsolenausgabe mit
        dem Terminal verschwand. `phase` unterscheidet den Erstlauf von den Wiederholungen nach
        einem Fixversuch, damit im Log nachvollziehbar bleibt, ob ein Fix etwas bewirkt hat.
        """
        report = await asyncio.to_thread(verifier.run_tests)
        try:
            run_logger = getattr(self, "_run_logger", None)
            if run_logger is not None:
                run_logger.log_verification_output(
                    step=f"pytest ({phase})",
                    exit_code=report.exit_code,
                    output=(report.stdout or "") + (
                        f"\n--- stderr ---\n{report.stderr}" if report.stderr else ""
                    ),
                )
        except Exception as e:
            # Sichtbar statt verschluckt: ohne Rohausgabe ist ein roter Lauf später nicht mehr
            # diagnostizierbar (Framework-Analyse 2026-09-10).
            logging.getLogger(__name__).warning(
                "Testausgabe (%s) konnte nicht ins Verifikations-Log geschrieben werden: %r", phase, e,
            )
        return report

    async def _run_verification_loop(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[AgentResult], str, bool, bool, bool]:
        """
        Ersetzt die alte Keyword-basierte Fix-Schleife. Installiert Abhängigkeiten
        in einer isolierten Umgebung, führt die echte Testsuite aus und schickt bei
        Fehlschlägen einen GEZIELTEN Korrekturauftrag an genau die Agenten, deren
        Dateien laut echtem Traceback betroffen sind.

        Gibt zusätzlich zurück, ob das harte Lauf-Budget (MAX_RUN_TOKENS) während der
        Fixversuche erreicht wurde bzw. der Lauf manuell abgebrochen wurde
        (run_start_tokens/cancel_requested=None -> jeweiliger Mechanismus deaktiviert),
        sowie verification_ok: True NUR, wenn die echte Testsuite tatsächlich gelaufen UND
        bestanden ist – False bei jedem anderen Ausgang (keine Tests gefunden, Testfehler
        blieben ungelöst, Budget während der Fixversuche erreicht, manuell abgebrochen).
        Realer Fund: bisher endete JEDER Lauf mit einem uneingeschränkten "✅ Fertig!", selbst
        wenn die Verifikation nie bestätigt werden konnte – verification_ok macht diesen
        Unterschied jetzt im finalen Status sichtbar (siehe process()) statt ihn im
        Kleingedruckten des Verifikations-Protokolls zu verstecken.
        """
        verifier = ProjectVerifier(project_dir)
        summary_lines: list[str] = []
        budget_aborted = False
        manually_cancelled = False
        verification_ok = False
        # Bleibt None, wenn die Schleife unten (z.B. MAX_VERIFICATION_ITERATIONS<=0) nie
        # durchläuft - der Coverage-Check danach prüft explizit auf None, statt sich auf eine
        # garantierte Zuweisung zu verlassen.
        report: VerificationReport | None = None
        # Höchstens EIN automatischer Nachbeauftragungs-Versuch für "keine Tests gefunden" (siehe
        # unten) - verhindert eine Endlosschleife, falls der tester-Agent wiederholt keine
        # echte Testdatei anlegt.
        no_tests_fix_attempted = False
        # Zirkuit-Breaker gegen wirkungslose Wiederholungen (Team-Retrospektive nach dem
        # taskpulse-Lauf): bisher wurde ein zweiter Fixversuch immer unternommen, selbst wenn
        # der erste erkennbar NICHTS verändert hat - derselbe Satz Testfehler (gleiche
        # test_id+Fehlermeldung) nach einem Fixversuch bedeutet fast immer, dass der
        # beauftragte Agent das Problem nicht lösen konnte, nicht dass ein zweiter,
        # identischer Auftrag beim nächsten Versuch anders ausgeht. Bricht die Schleife dann
        # SOFORT ab (spart einen kompletten, meist wirkungslosen Agenten-Durchlauf) statt den
        # letzten erlaubten Versuch trotzdem zu verbrauchen.
        previous_failure_signature: frozenset[tuple[str, str]] | None = None
        # Team-Retrospektive (Verbesserungsvorschlag "Strategiewechsel statt Wiederholung"):
        # bisher bedeutete der obige Zirkuit-Breaker nur "aufgeben" - derselbe Agent bekam
        # denselben Fehler zweimal exakt gleich beschrieben und scheiterte beide Male gleich,
        # das Ergebnis wurde dann trotzdem als "letzter Stand" übernommen (real beobachtet in
        # mehreren Läufen: sentinelproxy, incidentpilot, omnichat - "Nach 2 Versuchen nicht
        # vollständig grün"). EIN zusätzlicher Eskalations-Versuch (nicht mehr, um die Schleife
        # nicht doch wieder unbegrenzt zu verlängern) holt bei "kein Fortschritt" den
        # zuständigen Fachbereichsleiter (falls vorhanden) statt denselben Mitarbeiter erneut
        # gegen dasselbe Problem laufen zu lassen - eine andere Perspektive/Instruktion statt
        # exakter Wiederholung.
        escalation_attempted = False
        # Team-Optimierung (Retrospektive 2026-09-05, Punkt 3): core/backlog_worker.py eskaliert
        # bereits beim ZWEITEN automatischen Retry eines liegen gebliebenen Governance-/
        # Verifikations-Tickets auf HEAVY_MODEL (Orchestrator(escalate_models=True)) - aber ERST
        # in einem SEPARATEN, späteren Lauf. Real beobachtet (workspace/zeiterfassung_app,
        # 2026-09-04): drei komplette, eigenständige Läufe an demselben Projekt, bevor der Fehler
        # behoben war - jeder einzelne davon wiederholte innerhalb sich selbst nur "derselbe
        # Agent, dann der Fachbereichsleiter", beide mit dem UNVERÄNDERTEN Standard-Modell. Bevor
        # DIESER Lauf komplett aufgibt und ein Ticket für einen erst viel später folgenden
        # Backlog-Retry eröffnet, wird deshalb - GENAU EINMAL pro Lauf, NUR für die tatsächlich
        # betroffenen Agenten (kein pauschales Hochstufen aller 33 Fachagenten) - ein letzter
        # Versuch mit HEAVY_MODEL unternommen. Das verkürzt den in zeiterfassung_app real
        # beobachteten Drei-Lauf-Kreislauf im Idealfall auf einen einzigen Lauf.
        model_escalation_attempted = False
        # Defensiv vorinitialisiert (nicht nur im escalation_attempted-Zweig unten): bei einem
        # per Env auf >2 hochgesetzten MAX_VERIFICATION_ITERATIONS kann der "kein Fortschritt"-
        # Zweig ein zweites Mal greifen, NACHDEM escalation_attempted schon True ist - top_failures
        # würde dann sonst nie (neu) berechnet, aber unten beim Ticket-Text referenziert.
        top_failures = ""
        # Cross-Run-Gedächtnis (Team-Retrospektive nach dem taskpulse-Lauf, zweite Runde): ein
        # offenes Ticket aus einem VORHERIGEN Lauf desselben Projekts fließt als Kontext in den
        # ERSTEN Fix-Auftrag dieses Laufs ein (siehe _prior_run_context()) - und wird, sobald
        # die Testsuite in DIESEM Lauf tatsächlich grün wird, als gelöst geschlossen, statt als
        # "blocked" liegen zu bleiben, obwohl das Problem längst behoben ist.
        test_ticket_id = f"recurring-failure-{self.last_project_slug}" if self.last_project_slug else None
        try:
            had_prior_test_ticket = bool(test_ticket_id and get_ticket(test_ticket_id) is not None)
        except Exception:
            had_prior_test_ticket = False

        # Deterministischer Pre-Flight-Check: ast-basiert, blitzschnell vor isolierter Testsuite.
        # Erkennt fehlende __init__.py, Syntax-Fehler und nicht deklarierte Abhängigkeiten in
        # requirements.txt.
        #
        # Realer Fund (Analyse 2026-09-06): core/pre_flight_check.py wurde eingeführt, aber nur
        # für eine reine Notify-Anzeige verdrahtet - format_pre_flight_issues_for_fix() (extra
        # dafür geschrieben) und has_blocking_issues wurden nie aufgerufen, jeder Fund blieb
        # bis zum teuren, isolierten Testlauf liegen statt sofort behoben zu werden, obwohl er
        # in Millisekunden ohne LLM erkannt wurde. Jetzt derselbe gezielte Fix-und-Retry-Loop
        # (Owner-Routing über file_owners, Kein-Fortschritt-Zirkuitbrecher) wie beim Vorab-
        # Import-Check direkt darunter.
        previous_preflight_signature: frozenset[tuple[str, str]] | None = None
        for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
            if run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify("  🚫 [bold red]Budget erreicht[/bold red] – Pre-Flight-Check übersprungen.")
                break
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – Pre-Flight-Check übersprungen.")
                break

            try:
                pre_flight_report = await asyncio.to_thread(run_pre_flight_check, project_dir)
            except Exception as e:
                notify(f"  ⚠️ [dim]Pre-Flight-Check übersprungen: {e}[/dim]")
                break
            if pre_flight_report.error:
                notify(f"  ⚠️ [dim]Pre-Flight-Check übersprungen: {pre_flight_report.error}[/dim]")
                break
            if pre_flight_report.passed:
                if attempt > 1:
                    notify(f"  ✨ [bold green]Pre-Flight-Check nach Fix (Versuch {attempt}) bestanden.[/bold green]")
                    summary_lines.append(f"- 🔍 Pre-Flight-Check: nach {attempt} Durchlauf/Durchläufen bestanden.")
                else:
                    notify(f"  ✨ [bold green]Pre-Flight-Check bestanden ({pre_flight_report.files_checked} Dateien geprüft).[/bold green]")
                break

            notify(f"  🔍 [bold yellow]Pre-Flight-Check:[/bold yellow] {len(pre_flight_report.issues)} Problem(e) in {pre_flight_report.files_checked} Dateien gefunden.")
            for issue in pre_flight_report.issues[:3]:
                notify(f"    ⚠️ [{issue.issue_type}] {issue.file}:{issue.line}: {issue.message}")

            current_preflight_signature = _issue_signature(
                pre_flight_report.issues, lambda i: (i.file, i.message[:300])
            )
            if _no_progress(previous_preflight_signature, current_preflight_signature):
                notify("  🛑 [bold red]Kein Fortschritt:[/bold red] identische Pre-Flight-Funde wie vor dem letzten Fixversuch – breche ab, weiter mit der regulären Testsuite.")
                summary_lines.append(
                    f"- 🔍 🛑 Pre-Flight-Check, Versuch {attempt}: dieselben {len(pre_flight_report.issues)} Fund(e) wie nach "
                    "dem vorherigen Fixversuch (keine Veränderung) – Schleife abgebrochen statt einen wirkungslosen "
                    "weiteren Versuch zu verbrauchen."
                )
                break
            previous_preflight_signature = current_preflight_signature

            # Zuständigkeits-Fallback (Team-Optimierung, echter Fund: Pre-Flight-Befunde ohne
            # bekannten file_owners-Eintrag blieben bisher komplett unbeauftragt liegen und
            # landeten als Dauer-Blocker im recurring-failure-*-Backlog-Ticket, ohne dass je ein
            # Agent den Fix übernahm. Statt den Fund stillschweigend fallen zu lassen: Format-/
            # Lint-/Import-Funde (missing_init = fehlende __init__.py, hidden_runtime_dependency
            # = Import ohne deklarierte Abhängigkeit) gehen an project_cleaner (räumt Struktur/
            # Imports auf), reine Dependency-Manifest-Lücken (missing_dependency) an refactoring
            # (pflegt requirements.txt/pyproject.toml), alle übrigen echten Code-Probleme
            # (syntax_error u.ä.) an dev_lead als Auffangzuständigkeit für Code-Fehler.
            _FALLBACK_OWNER_BY_ISSUE_TYPE = {
                "missing_init": "project_cleaner",
                "hidden_runtime_dependency": "project_cleaner",
                "missing_dependency": "refactoring",
                "syntax_error": "dev_lead",
                # Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08): "empty_test_suite"
                # (core/pre_flight_check.py._check_empty_test_suite) meldet ein tests/-
                # Verzeichnis ohne eine einzige echte Testfunktion - kein Code-/Import-Problem,
                # sondern fehlende Testabdeckung. `tester` (nicht dev_lead) schreibt bereits
                # regulär die gesamte Testsuite und ist damit der fachlich richtige Owner.
                "empty_test_suite": "tester",
            }
            agents_to_fix: dict[str, list[PreFlightIssue]] = {}
            for issue in pre_flight_report.issues:
                owner = file_owners.get(issue.file)
                if not owner or owner not in self._agents:
                    owner = _FALLBACK_OWNER_BY_ISSUE_TYPE.get(issue.issue_type, "dev_lead")
                if owner in self._agents:
                    agents_to_fix.setdefault(owner, []).append(issue)

            if not agents_to_fix:
                summary_lines.append(f"- 🔍 ❌ Pre-Flight-Check: {len(pre_flight_report.issues)} Fund(e) blieben ungelöst (keinem Agenten eindeutig zuordenbar).")
                break

            fix_tasks = []
            for agent_id, agent_issues in agents_to_fix.items():
                issue_text = "\n".join(
                    f"- [{i.issue_type}] {i.file}:{i.line} – {i.message}"
                    + (f" Lösung: {i.suggestion}" if i.suggestion else "")
                    for i in agent_issues
                )
                fix_tasks.append(AgentTask(
                    task_id=f"verify_fix_preflight_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        "Ein statischer Pre-Flight-Check (VOR jeder Dependency-Installation und "
                        "jedem Testlauf) hat Probleme gefunden, die einen Testlauf mit hoher "
                        "Wahrscheinlichkeit zum Scheitern bringen. Behebe AUSSCHLIESSLICH diese "
                        "Befunde, erstelle keine neuen Features.\n\n"
                        f"{issue_text}"
                    ),
                    context="", project_dir=project_dir,
                ))

            notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix (Pre-Flight-Check):[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())}...")
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(f"- 🔍 Pre-Flight-Check, Versuch {attempt}: {len(pre_flight_report.issues)} Problem(e) → gezielt zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt.")

            if attempt == MAX_VERIFICATION_ITERATIONS:
                notify("  ⚠️ [yellow]Maximale Pre-Flight-Fixversuche erreicht – weiter mit der regulären Testsuite.[/yellow]")
                summary_lines.append(f"- 🔍 ⚠️ Pre-Flight-Check nach {MAX_VERIFICATION_ITERATIONS} Versuchen weiterhin mit Funden – weiter mit der regulären Testsuite.")

        notify("🧪 [bold cyan]Verifikation:[/bold cyan] Installiere Abhängigkeiten in isolierter Umgebung...")
        install_log = await asyncio.to_thread(verifier.ensure_environment)
        if install_log:
            notify(f"  📦 {install_log.splitlines()[0]}")
            summary_lines.append(f"- 📦 {install_log.splitlines()[0]}")

        # Vorab-Check (statt Vollständigkeits-Check erst NACH der teuren Testsuite/Governance-
        # Schleife, siehe unten): ein fehlendes lokales Python-Modul (z.B. `app/models.py`, das
        # per `from . import database, models, schemas` referenziert wird) ist rein statisch,
        # ohne jeden Testlauf, in Millisekunden erkennbar (core/verifier/completeness.py.
        # _missing_local_python_imports) - beim taskpulse-Lauf wurde genau dieser Fund erst nach
        # der vollständigen Test-/Governance-/Review-Kaskade sichtbar (33 Agenten-Durchläufe,
        # 714k Tokens, 23 Minuten), obwohl er von Anfang an feststand. Läuft NUR gegen
        # Import-Auflösungs-Funde (nicht den vollen Vollständigkeits-Check inkl. Stub-Marker/
        # fehlender I/O - die bleiben bewusst beim regulären, späteren Durchlauf, der zusätzlich
        # den frischen Testlauf mitprüft), maximal MAX_VERIFICATION_ITERATIONS Versuche wie jede
        # andere Fix-Schleife hier.
        if ENABLE_COMPLETENESS_CHECK and not (budget_aborted or manually_cancelled):
            # Derselbe Zirkuit-Breaker wie in den übrigen Fix-Schleifen dieser Datei (Team-
            # Retrospektive nach dem taskpulse-Lauf) - identische Import-Funde nach einem
            # Fixversuch bedeuten fast immer, dass der Agent das Problem nicht lösen konnte.
            previous_preimport_signature: frozenset[tuple[str, str]] | None = None
            for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
                if run_start_tokens is not None and (
                    self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                ):
                    budget_aborted = True
                    notify("  🚫 [bold red]Budget erreicht[/bold red] – Vorab-Import-Check übersprungen.")
                    break
                if cancel_requested and cancel_requested():
                    manually_cancelled = True
                    notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – Vorab-Import-Check übersprungen.")
                    break

                pre_report = await asyncio.to_thread(verifier.check_completeness)
                # Dieselbe Reihenfolge (erst .attempted, DANN .passed, bevor .issues überhaupt
                # angefasst wird) wie der bestehende Vollständigkeits-Check weiter unten - hält
                # Tests, die ProjectVerifier komplett mocken, ohne check_completeness() explizit
                # zu konfigurieren, unverändert lauffähig (ein MagicMock().passed ist truthy,
                # ein MagicMock().issues wäre dagegen nicht iterierbar und würde crashen).
                if not pre_report.attempted or pre_report.passed:
                    break
                # Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive, echter
                # Fund am event_relay-Lauf 2026-09-06): dieselbe fragile Substring-Suche wie
                # oben (structural_import_issues) - core/verifier/models.py.CompletenessIssue.
                # kind == "missing_local_import" erfasst jetzt auch einen fehlenden SYMBOL-Import
                # (z.B. `from app.resilience import resilience`), den die alte Suche nach
                # "existierendes lokales" NIE fand, obwohl check_completeness() ihn bereits
                # korrekt erkannte - der Vorab-Check brach damit still ab, statt den längst
                # erkannten Fund zur Korrektur weiterzureichen.
                import_issues = [i for i in pre_report.issues if i.kind == "missing_local_import"]
                if not import_issues:
                    if attempt > 1:
                        notify(f"  🧩 [bold green]Vorab-Import-Check nach Fix (Versuch {attempt}) bestanden.[/bold green]")
                        summary_lines.append(f"- 🧩 Vorab-Import-Check (statisch, vor der Testsuite): nach {attempt} Durchlauf/Durchläufen bestanden.")
                    break

                current_preimport_signature = _issue_signature(import_issues, lambda i: (i.file_path, i.message[:300]))
                if _no_progress(previous_preimport_signature, current_preimport_signature):
                    notify("  🛑 [bold red]Kein Fortschritt:[/bold red] identische Import-Funde wie vor dem letzten Fixversuch – breche Vorab-Import-Check ab, weiter mit der regulären Testsuite.")
                    summary_lines.append(
                        f"- 🧩 🛑 Vorab-Import-Check, Versuch {attempt}: dieselben {len(import_issues)} Fund(e) wie nach dem "
                        "vorherigen Fixversuch (keine Veränderung) – Schleife abgebrochen statt einen wirkungslosen weiteren "
                        "Versuch zu verbrauchen (bleibt im regulären Testlauf danach erneut sichtbar)."
                    )
                    break
                previous_preimport_signature = current_preimport_signature

                top = "; ".join(f"{i.file_path}:{i.line_number} – {i.message}" for i in import_issues[:5])
                notify(f"  🧩 [bold red]Vorab-Import-Check: {len(import_issues)} fehlende(s) lokale(s) Modul/Symbol VOR jedem Testlauf gefunden.[/bold red]")

                # Derselbe Zuständigkeits-Fallback wie beim Pre-Flight-Check oben: ein fehlendes
                # lokales Modul/Symbol ist immer ein Code-Problem, nie ein Format-/Lint-Fund -
                # ohne bekannten file_owners-Eintrag geht der Fund deshalb an dev_lead statt
                # unbeauftragt liegen zu bleiben.
                agents_to_fix: dict[str, list] = {}
                for issue in import_issues:
                    owner = file_owners.get(issue.file_path)
                    if not owner or owner not in self._agents:
                        owner = "dev_lead"
                    if owner in self._agents:
                        agents_to_fix.setdefault(owner, []).append(issue)

                if not agents_to_fix:
                    summary_lines.append(f"- 🧩 ❌ Vorab-Import-Check: {len(import_issues)} Fund(e) blieben ungelöst (keinem Agenten eindeutig zuordenbar): {top}")
                    break

                fix_tasks = []
                for agent_id, agent_issues in agents_to_fix.items():
                    issue_text = "\n".join(f"- {i.file_path}:{i.line_number} – {i.message}" for i in agent_issues)
                    fix_tasks.append(AgentTask(
                        task_id=f"verify_fix_preimport_{agent_id}_{attempt}",
                        agent_id=agent_id,
                        description=(
                            "Ein statischer Vorab-Check (VOR jedem Testlauf) hat lokale Python-Importe "
                            "gefunden, die auf nicht existierende Dateien/Symbole verweisen - der Code kann "
                            "dadurch nicht einmal importiert werden. Lege die fehlende(n) Datei(en) mit "
                            "echtem Inhalt an bzw. ergänze das fehlende Symbol in der genannten Datei.\n\n"
                            f"{issue_text}"
                        ),
                        context="",
                        project_dir=project_dir,
                    ))

                notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix (Vorab-Import-Check):[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())}...")
                fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
                self._update_file_owners(file_owners, fix_results)
                all_results.extend(fix_results)
                summary_lines.append(f"- 🧩 Vorab-Import-Check, Versuch {attempt}: {len(import_issues)} Fund(e) → gezielt zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt: {top}")

                if attempt == MAX_VERIFICATION_ITERATIONS:
                    notify("  ⚠️ [yellow]Maximale Vorab-Import-Fixversuche erreicht – weiter mit der regulären Testsuite.[/yellow]")
                    summary_lines.append(f"- 🧩 ⚠️ Vorab-Import-Check nach {MAX_VERIFICATION_ITERATIONS} Versuchen weiterhin mit Funden – weiter mit der regulären Testsuite (dort erneut sichtbar).")

        # ── Smoke-Test-Gate: Startet die App überhaupt? ───────────────────────────────────
        #
        # Team-Optimierung (KI-Team-Masterplan, Stufe 2): Der Runtime-Smoke-Test lief bisher
        # ERST NACH der kompletten Testschleife (siehe check_runtime_smoke weiter unten). Der
        # `tester` ist mit 78 Aufrufen der meistgerufene und mit 65,4% der schwächste
        # Kern-Agent - und ein Großteil dieser Fehlschläge entsteht, weil die Anwendung
        # überhaupt nicht startet. Eine vollständige Testsuite gegen eine App zu schreiben und
        # auszuführen, die schon beim Import scheitert, erzeugt nur Folgefehler: Jeder einzelne
        # Test schlägt aus derselben Ursache fehl, die Fix-Schleife bekommt einen Berg
        # scheinbar unabhängiger Fehler und verbrennt Token an Symptomen statt an der Ursache.
        # Genau das erklärt die teuren Fehlläufe (opspilot: 1.038.910 Tokens, agent_governance:
        # 999.313 - beide ohne bestandene Verifikation).
        #
        # Deshalb VOR der Testschleife: Startet die App nicht, wird genau dieser eine Fehler
        # gezielt behoben, bevor irgendetwas anderes passiert.
        if ENABLE_SMOKE_TEST_GATE and not (budget_aborted or manually_cancelled):
            smoke_gate_summary = await self._run_smoke_test_gate(
                verifier=verifier, project_dir=project_dir, all_results=all_results,
                file_owners=file_owners, notify=notify,
            )
            summary_lines.extend(smoke_gate_summary)

        for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
            if run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify("  🚫 [bold red]Budget erreicht[/bold red] – weitere Verifikations-/Fixversuche werden übersprungen.")
                summary_lines.append(f"- 🚫 {self._budget_exceeded_label(run_start_tokens)} erreicht – Verifikation nach Versuch {attempt - 1} abgebrochen.")
                break
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Verifikations-/Fixversuche werden übersprungen.")
                summary_lines.append(f"- ⏹️ Manuell abgebrochen – Verifikation nach Versuch {attempt - 1} beendet.")
                break

            notify(f"  🧪 [yellow]Testlauf {attempt}/{MAX_VERIFICATION_ITERATIONS}:[/yellow] Führe echte Tests aus...")
            report = await self._run_tests_logged(verifier, "erstlauf")

            if not report.ran:
                if not report.passed:
                    # Realer Fund (Workspace-Audit): ein mehrteiliges Backend-Projekt ohne jeden
                    # Einstiegspunkt bzw. eine Testsuite mit conftest.py, aber ohne echte Testdatei,
                    # sah bisher genauso aus wie "keine Tests gefunden" und lief als vermeintlich
                    # bestandene Verifikation durch – core/verifier.py.ProjectVerifier erkennt das
                    # jetzt als eigenständigen Fehlschlag statt als bloßes "nicht geprüft".
                    notify(f"  ❌ [bold red]{report.reason_skipped}[/bold red]")
                    summary_lines.append(f"- ❌ {report.reason_skipped}")

                    # Team-Optimierung (Retrospektive, zeiterfassung_app-Lauf): "conftest.py ohne
                    # jede echte Testdatei" wurde bisher zwar korrekt als Fehlschlag ERKANNT, aber
                    # nie ein Fix dafür ausgelöst - der Zweig endete direkt in `break`, anders als
                    # der Nachbar-Zweig weiter unten ("keine Tests gefunden" bei report.passed=True),
                    # der den tester gezielt nachbeauftragt. Ergebnis: das Projekt blieb dauerhaft
                    # ohne lauffähige Testsuite, obwohl die Ursache (fehlende Testdatei, kein
                    # fehlender Einstiegspunkt) für den tester-Agenten genauso behebbar gewesen wäre
                    # wie im Nachbar-Fall. Derselbe EINE Nachbeauftragungs-Versuch (no_tests_fix_
                    # attempted-Zirkuit-Breaker) wie dort, NUR für die Testdatei-Variante des Befunds
                    # - eine fehlende Einstiegspunkt-Datei (main.py/app.py/...) ist kein Testsuite-
                    # Problem und bleibt bewusst unangetastet, damit der tester nicht fälschlich mit
                    # einer Aufgabe beauftragt wird, die architect/backend lösen müssten.
                    if (
                        not no_tests_fix_attempted and "tester" in self._agents
                        and ("Testdatei" in report.reason_skipped or "Testsuite" in report.reason_skipped)
                    ):
                        no_tests_fix_attempted = True
                        notify(f"  🧪 [yellow]{report.reason_skipped}[/yellow] – beauftrage tester, die fehlende Testsuite nachzuliefern...")
                        summary_lines.append(f"- 🧪 {report.reason_skipped} → tester beauftragt, eine echte Testsuite nachzuliefern.")
                        log_decision(project_dir, "missing_tests_fix_dispatched", report.reason_skipped)
                        fix_task = AgentTask(
                            task_id=f"incomplete_tests_fix_{attempt}",
                            agent_id="tester",
                            description=(
                                "Für dieses Projekt existiert ein tests/-Verzeichnis (z.B. eine "
                                "conftest.py), aber KEINE einzige echte Testdatei (test_*.py/"
                                "*_test.py) - die Testsuite bricht dadurch ab, bevor auch nur ein "
                                "Test läuft, der vorhandene Code bleibt komplett ungeprüft. Schreibe "
                                "jetzt vollständige, lauffähige Testdateien (pytest) für den "
                                f"vorhandenen Code.\n\n{report.reason_skipped}"
                            ),
                            context="", project_dir=project_dir,
                        )
                        fix_results = await self._run_agents_parallel([fix_task], notify=notify)
                        self._update_file_owners(file_owners, fix_results)
                        all_results.extend(fix_results)
                        continue
                    break
                # Bewusst ⚠️ statt ℹ️: "keine Tests gefunden" bedeutet, dass generierter Code
                # UNGEPRÜFT ausgeliefert wird – real beobachtet an einem Taschenrechner-Projekt
                # ohne jeden Test, dessen "+"-Button sofort mit TypeError abstürzte (Add.execute()
                # verlangte zwei Argumente, die GUI übergab nur eines). DECOMPOSE_SYSTEM_PROMPT
                # (core/task_manager.py) weist das Modell inzwischen an, den tester-Agenten bei
                # echter Programmlogik einzubeziehen - reicht aber nicht immer (real beobachtet
                # am incidentpilot-Projekt: tester blieb ganz ohne Testdatei, statt hier nur
                # sichtbar zu bleiben, wird jetzt EIN gezielter Nachbeauftragungs-Versuch
                # unternommen, bevor endgültig aufgegeben wird.
                if not no_tests_fix_attempted and "tester" in self._agents:
                    no_tests_fix_attempted = True
                    notify(f"  🧪 [yellow]{report.reason_skipped}[/yellow] – beauftrage tester mit einer echten Testsuite...")
                    summary_lines.append(f"- 🧪 {report.reason_skipped} → tester beauftragt, eine echte Testsuite nachzuliefern.")
                    log_decision(project_dir, "missing_tests_fix_dispatched", report.reason_skipped)
                    fix_task = AgentTask(
                        task_id=f"missing_tests_fix_{attempt}",
                        agent_id="tester",
                        description=(
                            "Für dieses Projekt existiert noch KEINE echte, automatisch ausführbare "
                            "Testsuite (kein test_*.py, kein npm-Testskript gefunden) - der bereits "
                            "geschriebene Code wird dadurch komplett ungeprüft ausgeliefert. Schreibe "
                            "jetzt eine vollständige, lauffähige Testsuite (pytest bzw. das für dieses "
                            "Projekt passende Framework) für den vorhandenen Code."
                        ),
                        context="", project_dir=project_dir,
                    )
                    fix_results = await self._run_agents_parallel([fix_task], notify=notify)
                    self._update_file_owners(file_owners, fix_results)
                    all_results.extend(fix_results)
                    continue
                notify(f"  ⚠️ [yellow]{report.reason_skipped}[/yellow]")
                summary_lines.append(f"- ⚠️ {report.reason_skipped} Generierter Code wurde NICHT automatisch verifiziert.")
                break

            if report.passed:
                notify(f"  ✅ [bold green]Alle Tests bestanden[/bold green] (Versuch {attempt}, {report.duration_seconds:.1f}s).")
                summary_lines.append(f"- ✅ Echte Testsuite bestanden nach {attempt} Durchlauf/Durchläufen ({report.duration_seconds:.1f}s).")
                verification_ok = True
                if had_prior_test_ticket and test_ticket_id:
                    try:
                        upsert_ticket(
                            ticket_id=test_ticket_id,
                            title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                            source="orchestrator", status="done", project_slug=self.last_project_slug,
                            detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                        )
                        notify("  🎫 [dim]Ticket für vorherigen Testfehlschlag als gelöst geschlossen.[/dim]")
                    except Exception as e:
                        notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                break

            notify(f"  ❌ [bold red]{len(report.failures)} Testfehler[/bold red] – ermittle betroffene Agenten aus dem echten Traceback...")

            current_signature = _issue_signature(report.failures, lambda f: (f.test_id, f.message[:300]))
            if _no_progress(previous_failure_signature, current_signature):
                escalated_and_resolved = False
                if not escalation_attempted and not (
                    run_start_tokens is not None and (
                        self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                    )
                ):
                    escalation_attempted = True
                    stuck_owners = {
                        file_owners[f] for failure in report.failures for f in failure.files if f in file_owners
                    } & set(self._agents.keys())
                    lead_targets = {
                        dept_id for dept_id, defn in DEPARTMENT_DEFINITIONS.items()
                        if stuck_owners & set(defn["members"]) and dept_id in self._dept_leads
                    }
                    top_failures = "\n\n".join(
                        f"Test: {f.test_id}\nFehlermeldung: {f.message}\nBetroffene Dateien: {', '.join(f.files) or 'unbekannt'}"
                        for f in report.failures[:5]
                    )
                    if lead_targets:
                        notify(
                            f"  🔀 [bold yellow]Strategiewechsel (Eskalation):[/bold yellow] Derselbe Fehler nach "
                            f"einem wirkungslosen Fixversuch – ziehe Fachbereichsleiter "
                            f"({', '.join(sorted(lead_targets))}) statt derselben Wiederholung hinzu..."
                        )
                        escalation_tasks = [
                            AgentTask(
                                task_id=f"verify_escalation_{dept_id}_{attempt}",
                                agent_id=dept_id,
                                description=(
                                    "Ein vorheriger, gezielter Fixversuch deines Fachbereichs hat den folgenden "
                                    "echten Testfehler NICHT behoben (identisch vor und nach dem Versuch) - "
                                    "derselbe Ansatz hat also erkennbar nicht funktioniert. Analysiere das Problem "
                                    "aus einer anderen Perspektive (z.B. falsche Grundannahme, fehlende "
                                    "Abhängigkeit zwischen Dateien, falscher zuständiger Agent) und weise dein "
                                    f"Team mit einer GEÄNDERTEN Strategie an, statt denselben Fix zu wiederholen.\n\n{top_failures}"
                                ),
                                context="", project_dir=project_dir,
                            )
                            for dept_id in lead_targets
                        ]
                        fix_results = await self._run_agents_parallel(escalation_tasks, notify=notify)
                        self._update_file_owners(file_owners, fix_results)
                        all_results.extend(fix_results)
                        summary_lines.append(
                            f"- 🔀 Versuch {attempt}: kein Fortschritt beim vorherigen Fix → Eskalation an "
                            f"Fachbereichsleiter ({', '.join(sorted(lead_targets))}) mit geänderter Strategie."
                        )
                        # WICHTIG: das Ergebnis der Eskalation wird HIER SOFORT per echtem
                        # Testlauf geprüft (nicht über `continue` in die äußere Schleife
                        # zurückgereicht) - ein `continue` würde einen der ohnehin knappen
                        # MAX_VERIFICATION_ITERATIONS-Versuche für die Eskalation selbst
                        # verbrauchen und im letzten erlaubten Versuch dazu führen, dass die
                        # Schleife nach der Eskalation kommentarlos endet, OHNE das Scheitern
                        # zu melden oder ein Ticket zu eröffnen (so beim ersten Implementierungs-
                        # versuch real per Test aufgedeckt, siehe
                        # tests/test_verification_no_progress_breaker.py).
                        report = await self._run_tests_logged(verifier, "nach-fixversuch")
                        if report.passed:
                            notify(f"  ✅ [bold green]Eskalation erfolgreich:[/bold green] Alle Tests bestanden (Versuch {attempt}, {report.duration_seconds:.1f}s).")
                            summary_lines.append("- ✅ Eskalation an Fachbereichsleiter behob den Fehler – Testsuite bestanden.")
                            verification_ok = True
                            if had_prior_test_ticket and test_ticket_id:
                                try:
                                    upsert_ticket(
                                        ticket_id=test_ticket_id,
                                        title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                                        source="orchestrator", status="done", project_slug=self.last_project_slug,
                                        detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                                    )
                                except Exception as e:
                                    notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                            break
                        escalated_and_resolved = True  # Eskalation lief, aber weiterhin rot - unten normal abbrechen.

                    # Team-Optimierung (Retrospektive 2026-09-05, Punkt 3): letzter Versuch VOR
                    # dem endgültigen Aufgeben - dieselben stecken gebliebenen Agenten (NICHT die
                    # Fachbereichsleiter, die haben es gerade erst versucht) bekommen für GENAU
                    # diesen einen Fix-Auftrag ein stärkeres Modell (HEAVY_MODEL), statt den Fehler
                    # unverändert in ein Ticket zu schieben, das ohnehin erst bei einem viel
                    # späteren Backlog-Retry (core/backlog_worker.py) dieselbe Eskalation bekäme.
                    if not model_escalation_attempted and stuck_owners:
                        model_escalation_attempted = True
                        escalated_agent_ids = self._escalate_agent_models(stuck_owners)
                        if escalated_agent_ids:
                            notify(
                                f"  ⬆️ [bold yellow]Letzter Versuch mit stärkerem Modell:[/bold yellow] "
                                f"{', '.join(sorted(escalated_agent_ids))} laufen für diesen Fix-Auftrag "
                                "auf HEAVY_MODEL, statt direkt aufzugeben."
                            )
                            model_escalation_tasks = [
                                AgentTask(
                                    task_id=f"verify_model_escalation_{owner}_{attempt}",
                                    agent_id=owner,
                                    description=(
                                        "Dein vorheriger, gezielter Fixversuch UND die Eskalation an deinen "
                                        "Fachbereichsleiter haben den folgenden echten Testfehler NICHT behoben - "
                                        "du bekommst jetzt für diesen letzten Versuch ein stärkeres Modell. "
                                        "Analysiere die Grundannahme neu, statt denselben Ansatz ein drittes Mal "
                                        f"zu wiederholen.\n\n{top_failures}"
                                    ),
                                    context="", project_dir=project_dir,
                                )
                                for owner in sorted(escalated_agent_ids)
                            ]
                            fix_results = await self._run_agents_parallel(model_escalation_tasks, notify=notify)
                            self._update_file_owners(file_owners, fix_results)
                            all_results.extend(fix_results)
                            summary_lines.append(
                                f"- ⬆️ Versuch {attempt}: kein Fortschritt auch nach Eskalation an den "
                                f"Fachbereichsleiter → letzter Versuch mit HEAVY_MODEL für "
                                f"{', '.join(sorted(escalated_agent_ids))}."
                            )
                            report = await self._run_tests_logged(verifier, "nach-eskalation")
                            if report.passed:
                                notify(f"  ✅ [bold green]Modell-Eskalation erfolgreich:[/bold green] Alle Tests bestanden (Versuch {attempt}, {report.duration_seconds:.1f}s).")
                                summary_lines.append("- ✅ Fix mit HEAVY_MODEL behob den Fehler – Testsuite bestanden.")
                                verification_ok = True
                                if had_prior_test_ticket and test_ticket_id:
                                    try:
                                        upsert_ticket(
                                            ticket_id=test_ticket_id,
                                            title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                                            source="orchestrator", status="done", project_slug=self.last_project_slug,
                                            detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                                        )
                                    except Exception as e:
                                        notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                                break
                            escalated_and_resolved = True  # Auch mit stärkerem Modell weiterhin rot - unten normal abbrechen.

                notify(
                    "  🛑 [bold red]Kein Fortschritt:[/bold red] identische Testfehler wie vor dem letzten "
                    f"Fixversuch{' (auch nach Eskalation an den Fachbereichsleiter)' if escalated_and_resolved else ''} "
                    "– breche Verifikations-Schleife ab statt unverändert zu wiederholen."
                )
                summary_lines.append(
                    f"- 🛑 Versuch {attempt}: dieselben {len(report.failures)} Testfehler wie nach dem vorherigen "
                    "Fixversuch (keine Veränderung)" + (" - auch nach Eskalation" if escalated_and_resolved else "") +
                    " – Schleife abgebrochen statt einen wirkungslosen weiteren Versuch zu verbrauchen."
                )
                if self.last_project_slug:
                    try:
                        upsert_ticket(
                            ticket_id=f"recurring-failure-{self.last_project_slug}",
                            title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                            source="orchestrator", status="blocked", project_slug=self.last_project_slug,
                            detail=f"Fixversuch änderte nichts an {len(report.failures)} Testfehler(n) – "
                                   "vermutlich falscher/unzureichend instruierter Agent.\n\n" + top_failures
                                   + self._provider_exhaustion_ticket_note(),
                        )
                    except Exception as e:
                        notify(f"  ⚠️ [dim yellow]Ticket für ungelösten Testfehler konnte nicht angelegt werden: {e}[/dim yellow]")
                break
            previous_failure_signature = current_signature

            agents_to_fix: dict[str, list] = {}
            tester_participated = any(r.agent_id == "tester" for r in all_results)
            for failure in report.failures:
                # Persistentes Lernen (siehe _record_verification_learning) für künftige Läufe
                # desselben Agenten - bewusst außerhalb der seiteneffektfreien Routing-Funktion.
                if _import_name_error_target(failure.message) is not None:
                    _record_verification_learning(failure.message)
                owners = _route_failure_owners(
                    failure.message, failure.files, file_owners, self._agents, tester_participated,
                )
                for owner in owners:
                    if owner in self._agents:
                        agents_to_fix.setdefault(owner, []).append(failure)

            if not agents_to_fix:
                notify("  ⚠️ [yellow]Testfehler konnten keinem Agenten eindeutig zugeordnet werden – Auto-Fix abgebrochen.[/yellow]")
                summary_lines.append(f"- ⚠️ Versuch {attempt}: {len(report.failures)} Testfehler blieben ungelöst (keine eindeutige Dateizuordnung im Traceback).")
                break

            fix_tasks = []
            for agent_id, fails in agents_to_fix.items():
                failure_text = "\n\n".join(
                    f"Test: {f.test_id}\nFehlermeldung: {f.message}\nBetroffene Dateien: {', '.join(f.files) or 'unbekannt'}"
                    + (
                        f"\n{diag}"
                        if (diag := (
                            _diagnose_import_failure(f.message)
                            or _diagnose_no_tests_ran(f.message)
                            or _diagnose_runtime_failure(f.message)
                        ))
                        else ""
                    )
                    for f in fails
                )
                fix_tasks.append(AgentTask(
                    task_id=f"verify_fix_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        f"Die ECHTE automatische Testsuite ist fehlgeschlagen (kein Schätzwert, sondern realer "
                        f"pytest/unittest-Output). Nutze read_file, um die betroffene(n) Datei(en) zu prüfen, und "
                        f"edit_file/write_file, um den Fehler zu beheben. Verifiziere deinen Fix danach mit run_tests.\n\n"
                        f"{failure_text}"
                        + (_prior_run_context(test_ticket_id) if attempt == 1 and test_ticket_id else "")
                    ),
                    context="",
                    project_dir=project_dir,
                ))

            notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix:[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())} (nicht blind alle Dev-Agenten)...")
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(f"- 🛠️ Versuch {attempt}: {len(report.failures)} echte Testfehler → gezielt zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt.")

            if attempt == MAX_VERIFICATION_ITERATIONS:
                notify("  ⚠️ [yellow]Maximale Verifikations-Iterationen erreicht – letzter Stand wird übernommen.[/yellow]")
                summary_lines.append(f"- ⚠️ Nach {MAX_VERIFICATION_ITERATIONS} Versuchen nicht vollständig grün – letzter Stand wurde übernommen.")
                # Realer Fund (Team-Retrospektive, omnichat-Projekt): bisher wurde ein nach
                # MAX_VERIFICATION_ITERATIONS aufgegebener Testfehlschlag NUR geloggt - kein
                # Backlog-Ticket, keine sonstige Eskalation. Die bereits bestehende
                # `has_repeated_failure`-Eskalation in agents/orchestrator/__init__.py greift
                # erst NACH zwei aufeinanderfolgenden kompletten Läufen - hier wird bereits
                # beim ERSTEN Scheitern innerhalb dieses einen Laufs ein Ticket eröffnet
                # (upsert_ticket, dieselbe Ticket-ID wie ein etwaiges späteres wiederholtes
                # Scheitern würde erzeugen, damit beide Pfade dasselbe Ticket aktualisieren
                # statt Duplikate anzulegen), statt auf einen zweiten fehlgeschlagenen Lauf
                # zu warten, bevor überhaupt ein sichtbares Signal für menschliche Prüfung
                # entsteht.
                if self.last_project_slug:
                    try:
                        upsert_ticket(
                            ticket_id=f"recurring-failure-{self.last_project_slug}",
                            title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                            source="orchestrator", status="blocked", project_slug=self.last_project_slug,
                            detail="\n".join(summary_lines).strip()[:300] + self._provider_exhaustion_ticket_note(),
                        )
                    except Exception as e:
                        notify(f"  ⚠️ [dim yellow]Ticket für ungelösten Testfehler konnte nicht angelegt werden: {e}[/dim yellow]")

        # Echtes Deployment beginnt damit, dass das Projekt sich überhaupt containerisieren
        # lässt: ein generiertes Dockerfile, das nie tatsächlich baut, bringt niemanden näher
        # an ein echtes Ausrollen. Baut NIE `docker run`/einen echten Push/Deploy aus (würde
        # eine konkrete Ziel-Infrastruktur voraussetzen, die dieses Framework nicht kennt) -
        # nur die Build-Fähigkeit wird geprüft. Übersprungen bei Budget-Abbruch (kostet zwar
        # keine LLM-Tokens, aber echte Zeit) und generell kein Fehler, wenn kein Dockerfile
        # existiert oder Docker lokal nicht verfügbar ist (siehe DockerBuildReport).
        if not (budget_aborted or manually_cancelled):
            docker_report = await asyncio.to_thread(verifier.check_docker_build)
            if docker_report.attempted:
                if docker_report.success:
                    notify("  🐳 [bold green]Docker-Image baut erfolgreich.[/bold green]")
                    summary_lines.append("- 🐳 Docker-Image baut erfolgreich (echter `docker build`).")
                else:
                    notify("  🐳 [bold red]Docker-Build fehlgeschlagen.[/bold red]")
                    summary_lines.append(f"- 🐳 ❌ Docker-Build fehlgeschlagen: {docker_report.output[:500]}")
            elif docker_report.reason_skipped and "Daemon" in docker_report.reason_skipped:
                # Sichtbar (anders als "kein Dockerfile"/"Docker nicht installiert"), weil diese
                # Ursache sonst leicht mit einem echten, im Dockerfile liegenden Fehler verwechselt
                # wird - siehe _DOCKER_DAEMON_UNAVAILABLE_RE (core/verifier/models.py).
                notify(f"  🐳 [dim yellow]{docker_report.reason_skipped}[/dim yellow]")
                summary_lines.append(f"- 🐳 ⏭️ {docker_report.reason_skipped}")

        # Ersetzt die rein LLM-basierte Einschätzung des security-Agenten zu Abhängigkeits-
        # Risiken durch einen echten Abgleich gegen eine öffentliche Advisory-Datenbank
        # (pip-audit/npm audit) – kein Raten mehr, ob eine gepinnte Paketversion bekannte
        # CVEs hat. Ein technischer Fehlschlag des Scans (Tool fehlt, kein Netzwerk zur
        # Advisory-Datenbank) ist NIE ein Fehler, nur nicht prüfbar (attempted=False) und
        # wird deshalb bewusst NICHT als "keine Schwachstellen" ausgegeben.
        if not (budget_aborted or manually_cancelled):
            audit_reports = await asyncio.to_thread(verifier.check_dependency_vulnerabilities)
            for audit in audit_reports:
                if not audit.attempted:
                    continue
                if audit.vulnerable:
                    top = "; ".join(
                        f"{v.package} {v.version} ({v.vulnerability_id})" for v in audit.vulnerabilities[:5]
                    )
                    if len(audit.vulnerabilities) > 5:
                        top += f" … und {len(audit.vulnerabilities) - 5} weitere"
                    notify(f"  🔓 [bold red]{audit.tool}: {len(audit.vulnerabilities)} bekannte Schwachstelle(n) in Abhängigkeiten.[/bold red]")
                    summary_lines.append(f"- 🔓 ❌ {audit.tool}: {len(audit.vulnerabilities)} bekannte Schwachstelle(n) in Abhängigkeiten: {top}")
                else:
                    notify(f"  🔒 [bold green]{audit.tool}: keine bekannten Schwachstellen in Abhängigkeiten.[/bold green]")
                    summary_lines.append(f"- 🔒 {audit.tool}: keine bekannten Schwachstellen in Abhängigkeiten gefunden.")

        # Ersetzt die rein LLM-basierte Einschätzung des security-Agenten zu Schwachstellen
        # im SELBST GESCHRIEBENEN Code (Freitext-Vermutungen ohne Datei/Zeile) durch einen
        # echten statischen Scan (bandit für Python) – dasselbe Prinzip wie beim Dependency-
        # Audit oben, nur für eigenen Code statt Fremdpakete. Rein informativ wie der
        # Lint-Check, beeinflusst verification_ok nicht - ein SAST-Fund kann ein False
        # Positive sein und braucht menschliche Einschätzung, anders als ein roter Test.
        if not (budget_aborted or manually_cancelled):
            sast_reports = await asyncio.to_thread(verifier.check_sast)
            for sast in sast_reports:
                if not sast.attempted:
                    continue
                if sast.vulnerable:
                    top = "; ".join(
                        f"{f.file_path}:{f.line_number} [{f.rule}/{f.severity}]" for f in sast.findings[:5]
                    )
                    if len(sast.findings) > 5:
                        top += f" … und {len(sast.findings) - 5} weitere"
                    notify(f"  🕵️ [bold red]{sast.tool}: {len(sast.findings)} potenzielle Sicherheits-Fund(e) im Code.[/bold red]")
                    summary_lines.append(f"- 🕵️ ⚠️ {sast.tool}: {len(sast.findings)} potenzielle Sicherheits-Fund(e) im Code: {top}")
                else:
                    notify(f"  🕵️ [bold green]{sast.tool}: keine Sicherheits-Funde im Code.[/bold green]")
                    summary_lines.append(f"- 🕵️ {sast.tool}: keine Sicherheits-Funde im Code (statischer Scan).")

        # Ersetzt die rein LLM-basierte Lizenz-Tabelle des compliance-Agenten ("MIT/AGPL 🔴",
        # geraten) durch einen echten Scan der tatsächlich installierten Paket-Lizenzen
        # (pip-licenses). Rein informativ wie Lint/SAST, beeinflusst verification_ok nicht -
        # ein Copyleft-Fund ist eine rechtliche Einschätzungsfrage (z. B. Nutzung als Library
        # vs. verlinkt vs. modifiziert), kein automatisch behebbarer Codefehler.
        if not (budget_aborted or manually_cancelled):
            license_reports = await asyncio.to_thread(verifier.check_licenses)
            for lic in license_reports:
                if not lic.attempted:
                    continue
                if lic.has_copyleft_risk:
                    copyleft_findings = [f for f in lic.findings if f.copyleft]
                    top = "; ".join(f"{f.package} {f.version} ({f.license})" for f in copyleft_findings[:5])
                    if len(copyleft_findings) > 5:
                        top += f" … und {len(copyleft_findings) - 5} weitere"
                    notify(f"  📜 [bold red]{lic.tool}: {len(copyleft_findings)} Copyleft-Lizenz(en) in Abhängigkeiten (GPL/LGPL/MPL/…).[/bold red]")
                    summary_lines.append(f"- 📜 ⚠️ {lic.tool}: {len(copyleft_findings)} Copyleft-Lizenz(en) in Abhängigkeiten: {top}")
                else:
                    notify(f"  📜 [bold green]{lic.tool}: keine Copyleft-Lizenzen in Abhängigkeiten.[/bold green]")
                    summary_lines.append(f"- 📜 {lic.tool}: keine Copyleft-Lizenzen in Abhängigkeiten gefunden ({len(lic.findings)} geprüft).")

        # Erstmals überhaupt eine automatische Stil-/Fehlerprüfung für generierten Code -
        # ruff.toml lief bisher NUR gegen den Framework-Code selbst (workspace/ dort bewusst
        # ausgeschlossen). Python wird immer geprüft (ruff braucht keine Projekt-Konfiguration),
        # ESLint/tsc nur, wenn das Projekt sie selbst bereits mitbringt (keine ungefragte
        # Meinungsänderung an einem Projekt, das sich nie dafür entschieden hat). Rein
        # informativ, beeinflusst verification_ok nicht - anders als ein Testfehler hat ein
        # Lint-Fund oft keine unmittelbare Ein-Zeilen-Lösung.
        # Fingerabdruck aller Lint-Funde dieses Laufs ("tool:datei:regel") - dient
        # core/project_status.py.has_repeated_lint_finding() dazu, denselben, über mehrere
        # Läufe unverändert bestehen bleibenden Lint-Fund zu erkennen (siehe Kommentar dort).
        # self.last_lint_signature statt Erweiterung des Rückgabe-Tupels dieser Methode - hält
        # bestehende Aufrufer/Tests, die die feste Tupel-Länge erwarten, unverändert.
        self.last_lint_signature: list[str] = []
        # Team-Optimierung (Retrospektive, 2026-09-04): agents/orchestrator/__init__.py schließt
        # ein offenes "recurring-lint-"-Ticket automatisch, sobald ein Lauf KEINE Lint-Funde mehr
        # meldet (last_lint_signature leer) - das darf aber NICHT greifen, wenn Lint in diesem Lauf
        # gar nicht erst lief (z.B. `ruff` auf diesem System nicht installiert, oder die Schleife
        # wegen Budget/Abbruch übersprungen wurde). Ohne dieses Flag würde ein übersprungener Check
        # fälschlich als "Fund behoben" durchgehen.
        self.last_lint_attempted: bool = False
        if not (budget_aborted or manually_cancelled):
            lint_reports = await asyncio.to_thread(verifier.check_lint)
            for lint in lint_reports:
                if not lint.attempted:
                    continue
                self.last_lint_attempted = True
                self.last_lint_signature.extend(
                    f"{lint.tool}:{i.file_path}:{i.rule}" for i in lint.issues
                )
                if not lint.passed:
                    top = "; ".join(
                        f"{i.file_path}:{i.line_number} [{i.rule}]" for i in lint.issues[:5]
                    )
                    if len(lint.issues) > 5:
                        top += f" … und {len(lint.issues) - 5} weitere"
                    notify(f"  🎨 [bold yellow]{lint.tool}: {len(lint.issues)} Lint-Fund(e).[/bold yellow]")
                    summary_lines.append(f"- 🎨 ⚠️ {lint.tool}: {len(lint.issues)} Lint-Fund(e): {top}")
                else:
                    notify(f"  🎨 [bold green]{lint.tool}: keine Lint-Funde.[/bold green]")
                    summary_lines.append(f"- 🎨 {lint.tool}: keine Lint-Funde.")

        # Vollständigkeits-Check: erkennt Stub-/Platzhalter-Code (z.B. "Hier würde die
        # Verschlüsselung erfolgen") und im README referenzierte, aber fehlende Dateien (z.B.
        # requirements.txt) - siehe core/verifier/completeness.py und ENABLE_COMPLETENESS_CHECK
        # (config.py) für den vollständigen Kontext. Anders als Lint/SAST blockiert ein Fund
        # hier verification_ok, weil ein Stub-Kommentar eine nicht erfüllte fachliche
        # Anforderung ist, kein Stil-Hinweis - deshalb dieselbe gezielte Fix-Schleife wie beim
        # echten Testfehler oben, statt nur eine informative Zeile im Protokoll.
        if ENABLE_COMPLETENESS_CHECK and not (budget_aborted or manually_cancelled):
            # Derselbe Zirkuit-Breaker wie in der Test-Fix- und der Governance-Fix-Schleife
            # (Team-Retrospektive nach dem taskpulse-Lauf): identische Vollständigkeits-Funde
            # nach einem Fixversuch bedeuten fast immer, dass der Agent das Problem nicht lösen
            # konnte - ein zweiter, identischer Fix-Dispatch wäre reine Verschwendung.
            previous_completeness_signature: frozenset[tuple[str, str]] | None = None
            for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
                if run_start_tokens is not None and (
                    self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                ):
                    budget_aborted = True
                    notify("  🚫 [bold red]Budget erreicht[/bold red] – weitere Vollständigkeits-Fixversuche werden übersprungen.")
                    summary_lines.append(f"- 🚫 {self._budget_exceeded_label(run_start_tokens)} erreicht – Vollständigkeits-Check nach Versuch {attempt - 1} abgebrochen.")
                    break
                if cancel_requested and cancel_requested():
                    manually_cancelled = True
                    notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Vollständigkeits-Fixversuche werden übersprungen.")
                    summary_lines.append(f"- ⏹️ Manuell abgebrochen – Vollständigkeits-Check nach Versuch {attempt - 1} beendet.")
                    break

                completeness_report = await asyncio.to_thread(verifier.check_completeness)
                if not completeness_report.attempted:
                    break
                if completeness_report.passed:
                    if attempt == 1:
                        notify("  🧩 [bold green]Vollständigkeits-Check:[/bold green] keine Stub-/Platzhalter-Funde, keine fehlenden README-Referenzen.")
                        summary_lines.append("- 🧩 Vollständigkeits-Check: keine Stub-/Platzhalter-Funde, keine fehlenden README-referenzierten Dateien.")
                    else:
                        notify(f"  🧩 [bold green]Vollständigkeits-Check nach Fix (Versuch {attempt}) bestanden.[/bold green]")
                        summary_lines.append(f"- 🧩 Vollständigkeits-Check nach {attempt} Durchlauf/Durchläufen bestanden.")
                    break

                current_completeness_signature = _issue_signature(
                    completeness_report.issues, lambda i: (i.file_path, i.message[:300]),
                )
                if _no_progress(previous_completeness_signature, current_completeness_signature):
                    notify("  🛑 [bold red]Kein Fortschritt:[/bold red] identische Vollständigkeits-Funde wie vor dem letzten Fixversuch – breche Schleife ab.")
                    summary_lines.append(
                        f"- 🧩 🛑 Versuch {attempt}: dieselben {len(completeness_report.issues)} Vollständigkeits-Fund(e) wie nach "
                        "dem vorherigen Fixversuch (keine Veränderung) – Schleife abgebrochen statt einen wirkungslosen weiteren "
                        "Versuch zu verbrauchen."
                    )
                    verification_ok = False
                    break
                previous_completeness_signature = current_completeness_signature

                top = "; ".join(
                    f"{i.file_path}" + (f":{i.line_number}" if i.line_number else "") + f" – {i.message}"
                    for i in completeness_report.issues[:5]
                )
                if len(completeness_report.issues) > 5:
                    top += f" … und {len(completeness_report.issues) - 5} weitere"
                notify(f"  🧩 [bold red]Vollständigkeits-Check: {len(completeness_report.issues)} Fund(e).[/bold red]")
                verification_ok = False

                agents_to_fix: dict[str, list] = {}
                for issue in completeness_report.issues:
                    owner = file_owners.get(issue.file_path)
                    if not owner:
                        owner = self._infer_owner_from_path(issue.file_path)
                    if owner and owner in self._agents:
                        agents_to_fix.setdefault(owner, []).append(issue)

                if not agents_to_fix:
                    summary_lines.append(f"- 🧩 ❌ {len(completeness_report.issues)} Vollständigkeits-Fund(e) blieben ungelöst (keinem Agenten eindeutig zuordenbar): {top}")
                    break

                fix_tasks = []
                for agent_id, agent_issues in agents_to_fix.items():
                    issue_text = "\n".join(
                        f"- {i.file_path}" + (f":{i.line_number}" if i.line_number else "") + f" – {i.message}"
                        for i in agent_issues
                    )
                    fix_tasks.append(AgentTask(
                        task_id=f"verify_fix_completeness_{agent_id}_{attempt}",
                        agent_id=agent_id,
                        description=(
                            f"Der Vollständigkeits-Check hat unfertigen Code gefunden: ein Kommentar/Stub "
                            f"beschreibt eine Funktionalität, die NICHT wirklich implementiert ist (z.B. "
                            f"\"Hier würde X erfolgen\"), oder eine im README referenzierte Datei fehlt. "
                            f"Nutze read_file, um die betroffene(n) Stelle(n) zu prüfen, und implementiere "
                            f"die fehlende Funktionalität WIRKLICH (nicht nur den Kommentar entfernen) bzw. "
                            f"lege die fehlende Datei an.\n\n{issue_text}"
                        ),
                        context="",
                        project_dir=project_dir,
                    ))

                notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix (Vollständigkeit):[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())}...")
                fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
                self._update_file_owners(file_owners, fix_results)
                all_results.extend(fix_results)
                summary_lines.append(f"- 🧩 Versuch {attempt}: {len(completeness_report.issues)} Vollständigkeits-Fund(e) → gezielt zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt: {top}")

                if attempt == MAX_VERIFICATION_ITERATIONS:
                    notify("  ⚠️ [yellow]Maximale Vollständigkeits-Fixversuche erreicht – letzter Stand wird übernommen.[/yellow]")
                    summary_lines.append(f"- 🧩 ⚠️ Nach {MAX_VERIFICATION_ITERATIONS} Versuchen weiterhin Stub-/Platzhalter-Funde – letzter Stand wurde übernommen.")

        # Realer Fund bei einer Bestandsaufnahme des eigenen Teams: die Verifikation misst
        # bisher nur Pass/Fail, keine Abdeckung - ein Projekt mit 3 bestandenen Tests bei 500
        # Zeilen ungetestetem Code gilt genauso als "verifiziert" wie eines mit echter
        # Abdeckung. Opt-in über MIN_TEST_COVERAGE (Standard 0 = deaktiviert, siehe config.py) -
        # nur sinnvoll, wenn die Testsuite überhaupt gelaufen UND bestanden ist (report kann
        # None sein, wenn die Schleife oben nie durchlief, z.B. MAX_VERIFICATION_ITERATIONS<=0).
        if not (budget_aborted or manually_cancelled) and MIN_TEST_COVERAGE > 0 and report is not None and report.ran and report.passed:
            coverage_report = await asyncio.to_thread(verifier.check_coverage)
            if coverage_report.attempted:
                if coverage_report.percent >= MIN_TEST_COVERAGE:
                    notify(f"  📊 [bold green]Testabdeckung: {coverage_report.percent}%[/bold green] (Schwelle: {MIN_TEST_COVERAGE}%).")
                    summary_lines.append(f"- 📊 Testabdeckung: {coverage_report.percent}% (Schwelle von {MIN_TEST_COVERAGE}% erreicht).")
                else:
                    # Anders als ein Lint-Fund (rein informativ) ist eine EXPLIZIT konfigurierte
                    # Schwelle als echte Anforderung gemeint - verification_ok wird deshalb
                    # tatsächlich zurückgesetzt, nicht nur protokolliert.
                    notify(f"  📊 [bold red]Testabdeckung {coverage_report.percent}% UNTER der Schwelle von {MIN_TEST_COVERAGE}%.[/bold red]")
                    summary_lines.append(f"- 📊 ❌ Testabdeckung {coverage_report.percent}% UNTER der konfigurierten Schwelle (`MIN_TEST_COVERAGE={MIN_TEST_COVERAGE}%`).")
                    verification_ok = False

        # Runtime Smoke-Check: Prüft, ob die generierte App tatsächlich hochfährt / antwortet (Tests grün != App startet)
        #
        # Team-Optimierung (Retrospektive 2026-09-04): bisher lief dieser Check nur bei
        # report.passed - also GENAU DANN NICHT, wenn die Testsuite nach MAX_VERIFICATION_
        # ITERATIONS-Versuchen weiterhin rot blieb und "der letzte Stand übernommen" wurde
        # (siehe Zweig oben, `verify_fix_test`-Schleife). Real beobachtet an `zeiterfassung_
        # app`: genau in diesem Fall blieb ein simpler ImportError (Klassenname-Mismatch
        # zwischen main.py-Import und der tatsächlichen Middleware-Klasse) unentdeckt, bis ihn
        # ein SPÄTERER Governance-Review-Lauf per Code-Lesen fand - der automatisierte Smoke-
        # Test hätte ihn sofort UND günstiger gefunden. `report.ran` bleibt Voraussetzung (ohne
        # jeden Testlauf ist z.B. auch keine Dependency-Installation gesichert, gegen die
        # `check_runtime_smoke()` starten könnte), `report.passed` nicht mehr.
        if not (budget_aborted or manually_cancelled) and report is not None and report.ran:
            def _build_smoke_fix_task(smoke_report, attempt):
                owner = file_owners.get(smoke_report.entrypoint) if smoke_report.entrypoint else None
                agent_id = owner if owner in self._agents else ("backend" if "backend" in self._agents else None)
                if agent_id is None:
                    return None
                return AgentTask(
                    task_id=f"verify_fix_smoke_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        f"Der ECHTE Runtime-Smoke-Test ist fehlgeschlagen: die App startet nicht bzw. "
                        f"antwortet nicht (Entrypoint `{smoke_report.entrypoint}`, Typ {smoke_report.app_type}). "
                        f"Tests waren grün, aber 'Tests grün' heißt nicht 'App startet'. Nutze read_file, "
                        f"um die betroffene(n) Datei(en) zu prüfen, und edit_file/write_file, um den Start-"
                        f"fehler zu beheben.\n\nFehlerausgabe:\n{smoke_report.output[:1000]}"
                    ),
                    context="",
                    project_dir=project_dir,
                )

            smoke_report, all_results, sb_aborted, sb_cancelled = await self._run_runtime_check_with_fix(
                check_fn=verifier.check_runtime_smoke,
                build_fix_task=_build_smoke_fix_task,
                all_results=all_results,
                file_owners=file_owners,
                notify=notify,
                run_start_tokens=run_start_tokens,
                cancel_requested=cancel_requested,
                is_attempted=lambda r: r.attempted,
                is_passed=lambda r: r.passed,
            )
            budget_aborted = budget_aborted or sb_aborted
            manually_cancelled = manually_cancelled or sb_cancelled
            if smoke_report.attempted:
                if smoke_report.passed:
                    code_info = f" (HTTP {smoke_report.status_code})" if smoke_report.status_code else ""
                    notify(f"  🚀 [bold green]Runtime-Smoke-Test erfolgreich:[/bold green] `{smoke_report.entrypoint}` [{smoke_report.app_type}]{code_info}.")
                    summary_lines.append(f"- 🚀 Runtime-Smoke-Test: `{smoke_report.entrypoint}` [{smoke_report.app_type}] startet fehlerfrei{code_info}.")
                else:
                    # Bugfix (Code-Review-Fund): dieser Zweig baute bisher nur eine `err`-Variable,
                    # rief aber weder notify() noch summary_lines.append() auf und setzte
                    # verification_ok nicht zurück - ein fehlgeschlagener Smoke-Test (App startet
                    # nicht) blieb dadurch komplett unsichtbar UND unblockiert, obwohl genau das
                    # der Sinn dieses Checks ist ("Tests grün != App startet", siehe Kommentar
                    # oben). Analog zur Testabdeckungs-Schwelle: eine tatsächlich geprüfte, aber
                    # nicht startende App ist eine echte Anforderungsverletzung, kein reiner
                    # Stil-Hinweis wie ein Lint-Fund.
                    err = f": {smoke_report.output[:150]}" if smoke_report.output else ""
                    notify(f"  🚀 [bold red]Runtime-Smoke-Test fehlgeschlagen:[/bold red] `{smoke_report.entrypoint}` [{smoke_report.app_type}]{err}.")
                    summary_lines.append(f"- 🚀 ❌ Runtime-Smoke-Test fehlgeschlagen: `{smoke_report.entrypoint}` [{smoke_report.app_type}] startet nicht{err}.")
                    verification_ok = False

        # Lastentest: führt vom performance-Agenten geschriebene k6-/Locust-Skripte (tests/load/)
        # tatsächlich AUS statt sie nur unausgeführt im Projekt liegen zu lassen - startet die
        # App und lässt einen kurzen Smoke-Lasttest (wenige Sekunden, wenige virtuelle Nutzer)
        # dagegen laufen. Rein informativ wie Lint/SAST (kein Performance-Benchmark, keine
        # Kapazitätsaussage) - EXCEPT ein fehlgeschlagener Request ist wie beim Runtime-Smoke-
        # Test eine echte Anforderungsverletzung (die App crasht/fehlerantwortet unter simultaner
        # Last), kein reiner Stil-Hinweis. In der Praxis für die meisten Projekte ein No-Op
        # (braucht ein Skript unter tests/load/ UND das jeweilige Tool lokal installiert).
        if ENABLE_LOAD_TEST_CHECK and not (budget_aborted or manually_cancelled) and report is not None and report.ran and report.passed:
            def _build_load_fix_task(perf_report, attempt):
                owner = file_owners.get(perf_report.script) if perf_report.script else None
                agent_id = owner if owner in self._agents else ("backend" if "backend" in self._agents else None)
                if agent_id is None:
                    return None
                return AgentTask(
                    task_id=f"verify_fix_load_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        f"Der ECHTE Lastentest (`{perf_report.script}`, {perf_report.tool}) ist fehlgeschlagen: "
                        f"{perf_report.failed_requests} von {perf_report.total_requests} Requests scheiterten "
                        f"unter simultaner Last. Nutze read_file, um die betroffene(n) Datei(en) zu prüfen, "
                        f"und edit_file/write_file, um die Ursache (z.B. fehlende Nebenläufigkeitssicherung, "
                        f"blockierende I/O) zu beheben."
                    ),
                    context="",
                    project_dir=project_dir,
                )

            perf_report, all_results, lb_aborted, lb_cancelled = await self._run_runtime_check_with_fix(
                check_fn=lambda: verifier.check_load_test(LOAD_TEST_DURATION_SECONDS, LOAD_TEST_TIMEOUT_SECONDS),
                build_fix_task=_build_load_fix_task,
                all_results=all_results,
                file_owners=file_owners,
                notify=notify,
                run_start_tokens=run_start_tokens,
                cancel_requested=cancel_requested,
                is_attempted=lambda r: r.attempted,
                is_passed=lambda r: r.passed,
            )
            budget_aborted = budget_aborted or lb_aborted
            manually_cancelled = manually_cancelled or lb_cancelled
            if perf_report.attempted:
                stats = f"{perf_report.total_requests} Requests, {perf_report.failed_requests} fehlgeschlagen"
                # isinstance() statt "is not None": ein Test, der ProjectVerifier komplett mockt,
                # aber check_load_test() nicht explizit auf ein PerfCheckReport setzt (wie bei
                # check_docker_build/check_runtime_smoke gibt es hier keinen sicheren MagicMock-
                # Default), liefert für p95_ms sonst ein MagicMock-Objekt statt None - das würde
                # an der ":.0f"-Formatierung mit TypeError crashen. isinstance() ist für den
                # echten Produktivpfad (p95_ms ist dort immer float|None) gleichwertig, macht den
                # Codepfad aber robust gegen unvollständig gemockte Verifier in Tests.
                if isinstance(perf_report.p95_ms, (int, float)):
                    stats += f", p95={perf_report.p95_ms:.0f}ms"
                if perf_report.passed:
                    notify(f"  🏋️ [bold green]Lastentest ({perf_report.tool}) bestanden:[/bold green] `{perf_report.script}` [{stats}].")
                    summary_lines.append(f"- 🏋️ Lastentest ({perf_report.tool}) bestanden: `{perf_report.script}` [{stats}].")
                else:
                    notify(f"  🏋️ [bold red]Lastentest ({perf_report.tool}) fehlgeschlagen:[/bold red] `{perf_report.script}` [{stats}].")
                    summary_lines.append(f"- 🏋️ ❌ Lastentest ({perf_report.tool}) fehlgeschlagen: `{perf_report.script}` [{stats}].")
                    verification_ok = False

        # Browser / Frontend UI-Check: Prüft statische Assets, Rendering und JS-Konsolenfehler.
        # Realer Fund (Pong-Projekt): ein Fehlschlag hier war bisher rein informativ und
        # beeinflusste verification_ok NICHT - ein Frontend, das im echten Browser mit einem
        # JS-Fehler crasht oder ein <canvas> nie tatsächlich zeichnet (siehe blank_canvases,
        # core/browser_verifier.py), bestand die Verifikation trotzdem. Das war eine bewusste
        # Design-Entscheidung analog zu Lint/SAST - für ein Frontend-Projekt ist dieser Check
        # aber oft die EINZIGE Instanz, die überhaupt echten Browser-Code ausführt (Unit-Tests
        # wie im Pong-Fall mockten Canvas/DOM komplett weg), nicht nur ein Stil-Hinweis wie ein
        # Lint-Fund. Ein echter Fehlschlag zählt deshalb jetzt wie beim Lastentest/Runtime-
        # Smoke-Test oben als echte Anforderungsverletzung.
        if not (budget_aborted or manually_cancelled):
            def _build_browser_fix_task(browser_report, attempt):
                agent_id = "frontend" if "frontend" in self._agents else next(
                    (a for a in ("backend",) if a in self._agents), None,
                )
                if agent_id is None:
                    return None
                details = browser_report.missing_assets + browser_report.console_errors + [
                    f"Canvas nie gezeichnet: {c}" for c in browser_report.blank_canvases
                ]
                return AgentTask(
                    task_id=f"verify_fix_browser_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        f"Der ECHTE Browser/UI-Check (Playwright) gegen `{browser_report.tested_url}` ist "
                        f"fehlgeschlagen: {'; '.join(details)[:800]}. Nutze read_file, um die betroffene(n) "
                        f"Datei(en) zu prüfen, und edit_file/write_file, um den Fehler zu beheben (z.B. "
                        f"fehlendes Asset, JS-Konsolenfehler, nie gezeichnetes Canvas-Element)."
                    ),
                    context="",
                    project_dir=project_dir,
                )

            browser_report, all_results, br_aborted, br_cancelled = await self._run_runtime_check_with_fix(
                check_fn=verifier.check_browser_ui,
                build_fix_task=_build_browser_fix_task,
                all_results=all_results,
                file_owners=file_owners,
                notify=notify,
                run_start_tokens=run_start_tokens,
                cancel_requested=cancel_requested,
                is_attempted=lambda r: r.attempted,
                is_passed=lambda r: r.passed,
            )
            budget_aborted = budget_aborted or br_aborted
            manually_cancelled = manually_cancelled or br_cancelled
            if browser_report.attempted:
                if browser_report.passed:
                    if browser_report.engine == "playwright":
                        notify(f"  🌐 [bold green]Frontend/UI-Check erfolgreich:[/bold green] `{browser_report.tested_url}` [playwright, echter Browser-Lauf].")
                        summary_lines.append(f"- 🌐 Frontend/UI-Check: `{browser_report.tested_url}` [playwright] fehlerfrei (JS wurde echt ausgeführt).")
                    else:
                        # static_dom-Fallback: prüft NUR, ob referenzierte Dateien existieren -
                        # es läuft dabei KEIN JavaScript. Ein grüner static_dom-Pass sah bisher
                        # optisch identisch zu einem echten Playwright-Pass aus (nur der kleine
                        # "[engine]"-Zusatz unterschied sie) - genau der fehlende Kontrast, der
                        # einen kaputten Bootstrap (fehlendes type="module", kein Game-Loop) als
                        # "geprüft und ok" durchgehen ließ, obwohl nie echter Code lief.
                        notify(f"  🌐 [bold yellow]Frontend/UI-Check eingeschränkt:[/bold yellow] `{browser_report.tested_url}` [static_dom] - kein echter Browser installiert, JavaScript wurde NICHT ausgeführt (nur Dateiexistenz geprüft).")
                        summary_lines.append(f"- 🌐 ⚠️ Frontend/UI-Check nur eingeschränkt (`static_dom`, `{browser_report.tested_url}`): referenzierte Dateien existieren, aber JavaScript lief NICHT in einem echten Browser (Playwright fehlt/nicht nutzbar) - Laufzeitfehler bleiben so unentdeckt.")
                else:
                    details = browser_report.missing_assets + browser_report.console_errors + [
                        f"Canvas nie gezeichnet: {c}" for c in browser_report.blank_canvases
                    ]
                    err_details = "; ".join(details)[:150]
                    notify(f"  🌐 [bold red]Frontend/UI-Check fehlgeschlagen:[/bold red] {err_details}.")
                    summary_lines.append(f"- 🌐 ❌ Frontend/UI-Check fehlgeschlagen: {err_details}.")
                    verification_ok = False

        # Accessibility-Check: echter axe-core-Scan (WCAG 2.x) gegen die gerenderte Seite -
        # ersetzt die rein LLM-basierte Einschätzung des accessibility-Agenten durch geparste
        # Verstöße mit Regel/Schweregrad/Element. Rein informativ wie Lint/SAST/Lizenz-Scan
        # (beeinflusst verification_ok nicht) - dieselbe Einstufung wie der bereits bestehende
        # Frontend/UI-Check direkt darüber, der aus demselben Grund ebenfalls nicht blockiert.
        if not (budget_aborted or manually_cancelled):
            a11y_report = await asyncio.to_thread(verifier.check_accessibility)
            if a11y_report.attempted:
                if a11y_report.passed:
                    notify(f"  ♿ [bold green]Accessibility-Check (axe-core) erfolgreich:[/bold green] `{a11y_report.tested_url}`.")
                    summary_lines.append(f"- ♿ Accessibility-Check (axe-core): `{a11y_report.tested_url}` keine WCAG-Verstöße.")
                else:
                    top = "; ".join(f"{v.rule_id} [{v.impact}] {v.target}" for v in a11y_report.violations[:5])
                    if len(a11y_report.violations) > 5:
                        top += f" … und {len(a11y_report.violations) - 5} weitere"
                    notify(f"  ♿ [bold red]Accessibility-Check (axe-core): {len(a11y_report.violations)} WCAG-Verstoß/Verstöße.[/bold red]")
                    summary_lines.append(f"- ♿ ⚠️ Accessibility-Check (axe-core): {len(a11y_report.violations)} WCAG-Verstoß/Verstöße: {top}")

        verification_summary = "### 🧪 Verifikations-Protokoll (echte Dependency-Installation & Testausführung)\n" + (
            "\n".join(summary_lines) if summary_lines else "- Keine Verifikation durchgeführt."
        )
        return all_results, verification_summary, budget_aborted, manually_cancelled, verification_ok
