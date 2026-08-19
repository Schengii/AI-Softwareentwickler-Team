# tests/test_parser.py
import json
import pytest
from agents import parser

# ----------------------------------------------------------------------
#   Helper – gültiges JSON für mehrere Tests
# ----------------------------------------------------------------------
VALID_JSON = json.dumps({"name": "Alice", "age": 30})
INVALID_JSON = '{"name": "Bob", "age": 25'   # fehlendes schließendes }

# ----------------------------------------------------------------------
#   parse_json – Happy Path
# ----------------------------------------------------------------------
def test_parse_json_valid():
    result = parser.parse_json(VALID_JSON)
    assert isinstance(result, dict)
    assert result == {"name": "Alice", "age": 30}


# ----------------------------------------------------------------------
#   parse_json – Edge / Error Cases
# ----------------------------------------------------------------------
@pytest.mark.parametrize("payload", ["", "   ", "\n\t"])
def test_parse_json_empty_payload(payload):
    """Leeres bzw. nur Whitespace‑Payload → EmptyPayloadError"""
    with pytest.raises(parser.EmptyPayloadError):
        parser.parse_json(payload)


def test_parse_json_invalid_json():
    """Syntaktisch falsches JSON → InvalidJsonError"""
    with pytest.raises(parser.InvalidJsonError) as exc:
        parser.parse_json(INVALID_JSON)
    assert "Expecting" in str(exc.value)  # Teil der json‑Fehlermeldung


def test_parse_json_wrong_type():
    """Payload kein str → TypeError"""
    for bad in [b'{"a":1}', 123, None, {"a": 1}]:
        with pytest.raises(TypeError):
            parser.parse_json(bad)


# ----------------------------------------------------------------------
#   tokenize – Happy Path
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("hello world", ["hello", "world"]),
        ("  leading  and   trailing  ", ["leading", "and", "trailing"]),
        ("single", ["single"]),
        ("", []),
        ("   ", []),
    ],
)
def test_tokenize_variants(text, expected):
    assert parser.tokenize(text) == expected


# ----------------------------------------------------------------------
#   tokenize – Error Cases
# ----------------------------------------------------------------------
def test_tokenize_none():
    """None als Eingabe → TypeError"""
    with pytest.raises(TypeError):
        parser.tokenize(None)


def test_tokenize_non_string():
    """Zahl, List, etc. → TypeError"""
    for bad in [123, 3.14, ["a", "b"], {"key": "value"}]:
        with pytest.raises(TypeError):
            parser.tokenize(bad)


# ----------------------------------------------------------------------
#   extract_int – Happy Path
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "value,expected",
    [
        (42, 42),
        ("0", 0),
        ("123456", 123456),
    ],
)
def test_extract_int_valid(value, expected):
    assert parser.extract_int(value) == expected


# ----------------------------------------------------------------------
#   extract_int – Edge / Error Cases
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_value",
    [
        "42.0",          # Float‑String
        "abc",           # Nicht‑digit String
        3.14,            # Float
        None,            # NoneType
        True,            # bool (Subklasse von int, aber nicht erlaubt)
        False,
        [],              # List
        {},              # Dict
    ],
)
def test_extract_int_invalid(bad_value):
    with pytest.raises(parser.ExtractionError):
        parser.extract_int(bad_value)
