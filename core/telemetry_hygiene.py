"""
core/telemetry_hygiene.py – Hält die Lern-Datenbasis frei von Test-Rauschen

Die Selbstoptimierung (optimization_advisor, Modell-A/B-Tests, Eval-Gate) rechnet mit
memory/run_history.json und evals/eval_history.json. Analyse 2026-09-15: 61 von 200 Lauf-Einträgen
und 48 von 50 Benchmark-Einträgen stammten aus der Testsuite (fake-model, 0 s Dauer).

- `is_synthetic_run()` / `is_synthetic_eval()` erkennen solche Einträge.
- `should_skip_real_write()` verhindert neue Einträge aus Testprozessen in die echten Dateien.
- `clean_run_history()` / `clean_eval_history()` bereinigen Altdaten (mit Sicherungskopie).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SYNTHETIC_MODEL_NAMES = frozenset({"fake-model", "mock-model", "test-model"})
# Ein echter Lauf mit LLM-Aufrufen dauert nie unter einer Sekunde.
MIN_REAL_DURATION_SECONDS = 1.0


def is_test_process() -> bool:
    """True, während pytest einen Test ausführt."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def should_skip_real_write(target: Path, real_default: Path) -> bool:
    """True, wenn ein Testprozess in die echte (nicht umgebogene) Historien-Datei schreiben würde."""
    if not is_test_process():
        return False
    try:
        return Path(target).resolve() == Path(real_default).resolve()
    except OSError:
        return False


def is_synthetic_run(entry: dict) -> bool:
    """Erkennt einen Lauf-Eintrag, der nicht aus einem echten Projektlauf stammt."""
    results = entry.get("agent_results") or []
    if any((r.get("model_used") or "") in SYNTHETIC_MODEL_NAMES for r in results):
        return True
    try:
        duration = float(entry.get("duration_seconds") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return duration < MIN_REAL_DURATION_SECONDS


def is_synthetic_eval(entry: dict) -> bool:
    """Erkennt einen Benchmark-Eintrag ohne echte Ausführung (0 s Gesamtdauer)."""
    try:
        duration = float(entry.get("total_duration_seconds") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return duration < MIN_REAL_DURATION_SECONDS


def _clean_json_list(path: Path, predicate, label: str, *, dry_run: bool) -> tuple[int, int]:
    path = Path(path)
    if not path.exists():
        return 0, 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("%s konnte nicht gelesen werden (%s): %r", label, path, e)
        return 0, 0
    if not isinstance(data, list):
        return 0, 0
    kept = [e for e in data if not (isinstance(e, dict) and predicate(e))]
    removed = len(data) - len(kept)
    if removed and not dry_run:
        backup = path.with_suffix(path.suffix + f".bak_{datetime.now():%Y%m%d_%H%M%S}")
        try:
            shutil.copy2(path, backup)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            logger.error("%s konnte nicht bereinigt werden (%s): %r", label, path, e)
            return len(data), 0
    return len(data), removed


def clean_run_history(path: Path | None = None, *, dry_run: bool = False) -> tuple[int, int]:
    """Entfernt synthetische Läufe. Liefert (Einträge vorher, entfernt)."""
    if path is None:
        from memory import run_history
        path = run_history.RUN_HISTORY_FILE
    return _clean_json_list(path, is_synthetic_run, "Lauf-Historie", dry_run=dry_run)


def clean_eval_history(path: Path | None = None, *, dry_run: bool = False) -> tuple[int, int]:
    """Entfernt synthetische Benchmark-Ergebnisse. Liefert (Einträge vorher, entfernt)."""
    if path is None:
        from evals import runner
        path = runner.EVALS_HISTORY_FILE
    return _clean_json_list(path, is_synthetic_eval, "Benchmark-Historie", dry_run=dry_run)
