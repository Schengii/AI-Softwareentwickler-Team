# src/agents/parser.py
"""Parser‑Modul zum Einlesen von CSV‑ähnlichen Agent‑Definitionen.

Die Datei hat das Format:

    name,workspace,ki_model

* Leere Zeilen und Zeilen, die mit ``#`` beginnen, werden ignoriert.
* Bei strukturellen Fehlern wird eine ``ValueError`` mit Zeilennummer geworfen.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import List

from .models import AgentDefinition, AgentDefinitionList

# --------------------------------------------------------------------------- #
# Logging‑Konfiguration (kann von der Anwendung überschrieben werden)
# --------------------------------------------------------------------------- #
logger = logging.getLogger(__name__)
if not logger.handlers:
    # Simple console handler, nur aktiv wenn das Modul eigenständig verwendet wird
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s – %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _parse_line(row: List[str], line_no: int) -> AgentDefinition:
    """
    Parse eine CSV‑Zeile in ein :class:`AgentDefinition`‑Objekt.

    Parameters
    ----------
    row: List[str]
        Bereits gesplittete und getrimmte Spalten.
    line_no: int
        1‑basierte Zeilennummer (für Fehlermeldungen).

    Returns
    -------
    AgentDefinition
        Das erzeugte, validierte Objekt.

    Raises
    ------
    ValueError
        Wenn die Zeile nicht exakt drei nicht‑leere Spalten enthält.
    """
    if len(row) != 3:
        raise ValueError(f"Zeile {line_no}: Erwartet 3 Spalten, erhalten {len(row)}")
    name, workspace, ki_model = (col.strip() for col in row)

    if not all([name, workspace, ki_model]):
        raise ValueError(f"Zeile {line_no}: Leeres Feld gefunden")

    logger.debug("Parsed Agent – name=%s, workspace=%s, ki_model=%s", name, workspace, ki_model)
    return AgentDefinition(name=name, workspace=workspace, ki_model=ki_model)


def parse_agent_file(path: Path | str) -> AgentDefinitionList:
    """
    Öffnet *path*, liest alle Agent‑Definitionen und gibt sie als Liste zurück.

    Leere Zeilen und Kommentarzeilen (beginnend mit ``#``) werden übersprungen.

    Parameters
    ----------
    path: Path | str
        Pfad zur CSV‑Datei.

    Returns
    -------
    List[AgentDefinition]

    Raises
    ------
    FileNotFoundError
        Wenn *path* nicht existiert oder kein reguläres File ist.
    ValueError
        Bei syntaktischen Fehlern in einer Zeile (inkl. Zeilennummer).
    """
    file_path = Path(path)

    if not file_path.is_file():
        raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")

    agents: List[AgentDefinition] = []
    with file_path.open(newline="", encoding="utf-8") as fp:
        reader = csv.reader(fp)
        for line_no, raw_row in enumerate(reader, start=1):
            # Kommentar‑ oder Leerzeile?
            if not raw_row or (len(raw_row) == 1 and raw_row[0].strip().startswith("#")):
                logger.debug("Ignoriere Kommentar/Leere Zeile %s", line_no)
                continue
            # Entferne führende/trailing Leerzeichen aus allen Spalten
            stripped_row = [col.strip() for col in raw_row]
            try:
                agent = _parse_line(stripped_row, line_no)
                agents.append(agent)
            except ValueError as exc:
                # Fehler sofort weiterreichen – Caller kann entscheiden, ob er abbrechen will
                logger.error("Parsing‑Fehler in %s: %s", file_path, exc)
                raise

    logger.info("Erfolgreich %d Agent‑Definitionen aus %s geladen", len(agents), file_path)
    return agents
