"""
agents/orchestrator/failure_diagnosis.py – Regelbasierte Fehlerdiagnose & Owner-Routing für die
Verifikations-/Fix-Schleifen (extrahiert aus agents/orchestrator/verification.py).

ki_team_verbesserungsanalyse.md, Teil 5.1: verification.py war mit ~2850 Zeilen/193 KB die
größte Einzeldatei des Frameworks - dieser Block reiner, zustandsloser Diagnose-/Routing-
Funktionen (kein Zugriff auf `self`/Orchestrator-Zustand) ist der am klarsten abgrenzbare
Teil davon und lässt sich deshalb gefahrlos extrahieren: er analysiert eine rohe Fehlermeldung
(`message: str`) und liefert entweder eine konkrete Diagnosezeile für den Fix-Auftrag oder
den/die zuständigen Agenten zurück, ohne selbst Agenten zu beauftragen oder Ticket-/Log-Status
zu verändern.

agents/orchestrator/verification.py importiert alle hier definierten Namen unverändert zurück
(Re-Export), sodass bestehende Importe (`from agents.orchestrator.verification import
_diagnose_runtime_failure`, siehe u.a. tests/test_runtime_failure_diagnosis.py) weiter
funktionieren, ohne dass Aufrufer diesen Umzug bemerken müssen.

_run_governance_fix_loop()/_run_verification_loop() (in verification.py) beauftragen gezielte
Korrekturen NACH der Fachbereichs-Hierarchie bzw. nach einem echten Testlauf - die Funktionen
hier entscheiden dabei WAS als Ursache benannt wird und WER dafür zuständig ist.
"""

import re
from collections.abc import Callable, Collection, Iterable
from pathlib import Path, PurePosixPath
from typing import TypeVar

from core.backlog_store import get_ticket
from core.failure_triage import (
    StructuralTriage,
    is_local_module,
    is_test_file,
    resolve_triage_owner,
    triage_structural_failure,
)
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
# ki_team_fehleranalyse_zusammenfassung.md, Befund 2 (chronos_ledger-Lauf 20260912_181917):
# `detector.record_metric(...)` schlug mit `AttributeError: 'AnomalyDetector' object has no
# attribute 'record_metric'` fehl. Python stürzt an der AUFRUFSTELLE ab (hier tests/test_ledger.py),
# nicht an der Klassendefinition (app/services/anomaly_detector.py) - _route_failure_owners()
# wies den Fehler deshalb bisher AUSSCHLIESSLICH dem tester zu, der eigentliche Autor der Klasse
# (hier: ml) wurde nie informiert. Bewusst getrennt von _DICT_ATTRIBUTE_ERROR_RE oben: ein rohes
# dict statt eines Pydantic-Modells ist ein anderes, spezifisches Fehlerbild mit eigener Diagnose.
_INSTANCE_ATTRIBUTE_ERROR_RE = re.compile(r"AttributeError:\s*'(\w+)' object has no attribute '(\w+)'")
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
    m = _INSTANCE_ATTRIBUTE_ERROR_RE.search(message)
    if m and m.group(1) != "dict":
        cls, attr = m.group(1), m.group(2)
        return (
            f"⚠️ KONKRETE URSACHE: `AttributeError: '{cls}' object has no attribute '{attr}'` – "
            f"die Methode/das Attribut `{attr}` existiert nicht auf der Klasse `{cls}`. Prüfe "
            f"ZUERST die tatsächliche Klassendefinition von `{cls}`: ENTWEDER ergänzt der Autor "
            f"dieser Klasse `{attr}` dort wirklich, ODER der Aufruf wird an eine bereits "
            f"vorhandene Methode der Klasse angepasst - ändere NICHT nur die aufrufende Stelle "
            "(z.B. einen Test), ohne die Klassendefinition selbst geprüft zu haben."
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


# Gemeinsame Definition mit core/failure_triage.py (Testcode-Erkennung für das Routing).
_is_test_file = is_test_file


def _dependency_error_module(message: str, file_owners: dict[str, str], project_dir: str | None = None) -> str | None:
    """Name des Drittanbieter-Moduls, falls die Fehlermeldung ein Dependency-Problem zeigt
    (`AttributeError: module 'jwt' ...` bzw. `ModuleNotFoundError` eines Nicht-Projektmoduls).
    Mit `project_dir` zählt auch ein nur im Dateisystem vorhandenes Projektmodul als lokal - die
    frühere, rein auf file_owners gestützte Prüfung hielt Module aus früheren Läufen für PyPI-
    Pakete und schickte den Refactoring-Agenten an requirements.txt."""
    for pattern in (_MODULE_ATTRIBUTE_ERROR_RE, _MODULE_NOT_FOUND_RE):
        m = pattern.search(message)
        if m and not is_local_module(m.group(1), project_dir, file_owners):
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


def _class_definition_owner(
    class_name: str,
    file_owners: dict[str, str],
    available_agents: Collection[str],
    project_dir: str | None,
) -> str | None:
    """Owner der Datei, die `class {class_name}` tatsächlich definiert - für eine
    `AttributeError: '{class_name}' object has no attribute ...` auf einer Instanz, bei der der
    Traceback nur die AUFRUFENDE Stelle zeigt (siehe _INSTANCE_ATTRIBUTE_ERROR_RE-Docstring
    oben), nicht die Klassendefinition selbst. Durchsucht deterministisch NUR die bekannten
    Projektdateien (file_owners) nach einer `class`-Definitionszeile - kein LLM-Aufruf, kein
    voller Dateisystem-Scan. None, wenn kein bekannter Agent die Klasse definiert."""
    if project_dir is None:
        return None
    pattern = re.compile(rf"^\s*class\s+{re.escape(class_name)}\b", re.MULTILINE)
    root = Path(project_dir)
    for rel, owner in file_owners.items():
        if not rel.endswith(".py") or owner not in available_agents:
            continue
        try:
            content = (root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        if pattern.search(content):
            return owner
    return None


def _route_failure_owners(
    message: str,
    files: Iterable[str],
    file_owners: dict[str, str],
    available_agents: Collection[str],
    tester_participated: bool,
    project_dir: str | None = None,
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
    # Strukturelle Fehler (Syntax/Collection/Import/Settings) zuerst: core/failure_triage.py
    # entscheidet anhand von interface_contract.json bzw. des realen Anbieter-Codes, WER vom
    # Vertrag abweicht (Konsument oder Anbieter), statt pauschal den Owner des Zielmoduls zu
    # beauftragen oder den Fehler als Dependency-Problem an requirements.txt zu schicken.
    triage = triage_structural_failure(message, files, file_owners, project_dir)
    if triage is not None and (triage_owner := resolve_triage_owner(triage, file_owners, available_agents)):
        return {triage_owner}
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
    elif _dependency_error_module(message, file_owners, project_dir) and (dep_owner := _dependency_fix_owner(file_owners, available_agents)):
        owners = {dep_owner}
    elif (
        (im := _INSTANCE_ATTRIBUTE_ERROR_RE.search(message))
        and im.group(1) != "dict"
        and (class_owner := _class_definition_owner(im.group(1), file_owners, available_agents, project_dir))
    ):
        # Befund 2: der Traceback zeigt oft nur die aufrufende Stelle (z.B. einen Test) -
        # ergänzt den tatsächlichen Autor der Klasse, statt ihn dem tester-Fallback zu
        # überlassen bzw. ganz zu übergehen.
        owners.add(class_owner)
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


def _record_instance_attribute_learning(message: str, agent_id: str = "tester") -> None:
    """Analog zu _record_verification_learning() oben, aber für die `AttributeError: '<Klasse>'
    object has no attribute '<Methode>'`-Fehlerklasse (siehe _INSTANCE_ATTRIBUTE_ERROR_RE).
    Realer Fund (chronos_ledger, Lauf 20260912_181917): `tester` rief `record_metric` auf
    `AnomalyDetector` auf, obwohl die Klasse dort nur `check_anomaly` bereitstellt - dieselbe
    Verwechslung wäre ohne Lernregel in künftigen Läufen erneut passiert. Rein regelbasiert,
    kein LLM-Aufruf; ein Speicherfehler darf die Fix-Schleife nie zum Absturz bringen."""
    m = _INSTANCE_ATTRIBUTE_ERROR_RE.search(message)
    if m is None or m.group(1) == "dict":
        return
    cls, attr = m.group(1), m.group(2)
    try:
        agent_knowledge_base.add_learning(
            agent_id,
            f"Prüfe vor dem Aufruf einer Hilfsmethode wie {attr}() auf einer Instanz von "
            f"{cls} stets die tatsächliche Klassendefinition - existiert die Methode dort "
            "nicht, nutze die vorhandene primäre Schnittstelle der Klasse, statt eine "
            "nicht existierende Methode aufzurufen.",
        )
    except Exception:
        pass


# Team-Optimierung (echter Fund: memory/backlog.json-Tickets `recurring-failure-event_relay`/
# `recurring-failure-service_bookmark_monitor`) - siehe _diagnose_no_tests_ran()-Docstring.
# Realer Fund (auditlog_sentinel, 2026-09-10): derselbe Collection-Fehler
# (`AttributeError: 'AsyncEngine' object has no attribute '_run_ddl_visitor'`) lieferte vor und
# nach dem Fixversuch unterschiedlich lange pytest-Ausgaben (1521 vs. 862 Zeichen). Die
# Fortschrittserkennung verglich die ersten 300 Zeichen der Rohmeldung, hielt den unveränderten
# Fehler deshalb für "Fortschritt" und eskalierte nie. Verglichen wird jetzt die eigentliche
# Exception-Zeile, bereinigt um flüchtige Anteile (Adressen, Laufzeiten, Zeilennummern).
_EXCEPTION_LINE_RE = re.compile(r"^(?:E\s+)?([A-Za-z_][\w.]*(?:Error|Exception|Exit)):\s?(.*)$", re.MULTILINE)
_VOLATILE_TOKEN_RE = re.compile(r"0x[0-9a-fA-F]+|\b\d+(?:\.\d+)?s\b|line \d+|:\d+:")


def _failure_fingerprint(message: str) -> str:
    """Stabiler Vergleichsschlüssel einer Testfehlermeldung für die Fortschrittserkennung."""
    match = _EXCEPTION_LINE_RE.search(message or "")
    core = f"{match.group(1)}: {match.group(2)}" if match else (message or "")[:300]
    return _VOLATILE_TOKEN_RE.sub("#", core).strip()[:300]


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


def _failure_diagnosis(message: str, triage: StructuralTriage | None) -> str | None:
    """Konkrete Ursache für den Fix-Auftrag: strukturelle Triage (core/failure_triage.py) vor
    den regex-basierten Diagnosen oben."""
    if triage is not None:
        return triage.diagnosis
    return _diagnose_import_failure(message) or _diagnose_no_tests_ran(message) or _diagnose_runtime_failure(message)


_T = TypeVar("_T")

# Vier der Fix-Schleifen in verification.py (Test-, Governance-, Vorab-Import-, Vollständigkeits-
# Schleife) teilten bisher dieselbe, viermal wortgleich kopierte "identische Funde wie beim
# letzten Versuch? -> abbrechen"-Logik (Team-Retrospektive nach dem taskpulse-Lauf, zweite
# Runde). _issue_signature()/_no_progress() bündeln NUR die reine Signatur-Bildung/den -Vergleich
# - bewusst NICHT das Abbrechen/Notify/Ticket-Öffnen selbst, das unterscheidet sich je Schleife
# (unterschiedliche Ticket-IDs, Log-Texte, Nebeneffekte wie verification_ok=False) zu sehr, um
# es ohne Klarheitsverlust in eine gemeinsame Funktion zu zwingen.
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
    Haltung wie bei den upsert_ticket()-Aufrufen in verification.py."""
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
