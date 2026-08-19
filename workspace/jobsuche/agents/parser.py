# agents/parser.py
import json
import re
from typing import Any, List, Dict

# ──────────────────────────────────────────────────────────────
#   Exception‑Hierarchie
# ──────────────────────────────────────────────────────────────
class ParserError(Exception):
    """Basisklasse für alle Parser‑bezogenen Fehler."""
    pass


class EmptyPayloadError(ParserError):
    """Wird ausgelöst, wenn das zu parsende Payload leer ist."""
    pass


class InvalidJsonError(ParserError):
    """Wird ausgelöst, wenn das JSON syntaktisch ungültig ist."""
    pass


class ExtractionError(ParserError):
    """Wird ausgelöst, wenn ein Wert nicht in den gewünschten Typ konvertiert werden kann."""
    pass


# ──────────────────────────────────────────────────────────────
#   Parser‑Funktionen
# ──────────────────────────────────────────────────────────────
def parse_json(payload: str) -> Dict[Any, Any]:
    """
    Wandelt einen JSON‑String in ein Python‑Dictionary um.

    :raises EmptyPayloadError:   wenn ``payload`` leer oder nur Whitespace ist.
    :raises InvalidJsonError:    wenn das JSON syntaktisch fehlerhaft ist.
    :raises TypeError:           wenn ``payload`` kein ``str`` ist.
    """
    if not isinstance(payload, str):
        raise TypeError("payload must be a string")
    if not payload.strip():
        raise EmptyPayloadError("Empty payload")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise InvalidJsonError(str(exc)) from exc


def tokenize(text: str) -> List[str]:
    """
    Zerlegt einen Text in Tokens (Wort‑ähnliche Einheiten).

    :raises TypeError: wenn ``text`` ``None`` oder kein ``str`` ist.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    # Normalisiere Whitespace, entferne führende/trailing Spaces und filtere leere Tokens
    return [tok for tok in re.split(r"\s+", text.strip()) if tok]


def extract_int(value: Any) -> int:
    """
    Extrahiert einen Integer‑Wert aus ``value``.

    Akzeptiert:
      - ``int`` (wird unverändert zurückgegeben)
      - ``str`` bestehend ausschließlich aus Ziffern

    :raises ExtractionError: wenn ``value`` nicht in einen int konvertierbar ist.
    """
    if isinstance(value, bool):
        # bool ist Subclass von int – soll hier nicht akzeptiert werden
        raise ExtractionError(f"Cannot extract int from boolean {value!r}")

    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ExtractionError(f"Cannot extract int from {value!r}")
