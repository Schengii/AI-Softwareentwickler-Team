import pytest
from app.core.markdown import parse_markdown, serialize_markdown, ParsedNote


def test_parse_markdown_basic_content():
    """Prüft das Parsen von einfachem Markdown-Text ohne Frontmatter."""
    text = "# Titel der Notiz\n\nDies ist ein Absatz mit Inhalt."
    parsed = parse_markdown(text)

    assert isinstance(parsed, ParsedNote)
    assert parsed.title == "Titel der Notiz"
    assert parsed.frontmatter == {}
    assert "Dies ist ein Absatz" in parsed.content
    assert parsed.wikilinks == []
    assert parsed.tags == []


def test_parse_markdown_with_frontmatter():
    """Prüft YAML-Frontmatter mit Tags, Typ und Datum."""
    raw = """---
title: Architektur Übersicht
tags: [architecture, backend, adr]
type: permanent
created: 2026-09-22
---

# Architektur Übersicht

Hier steht der Inhalt.
"""
    parsed = parse_markdown(raw)

    assert parsed.title == "Architektur Übersicht"
    assert parsed.frontmatter.get("type") == "permanent"
    assert "architecture" in parsed.tags
    assert "backend" in parsed.tags
    assert "adr" in parsed.tags
    assert "Hier steht der Inhalt." in parsed.content


def test_parse_markdown_with_wikilinks_and_aliases():
    """Prüft die Extraktion von [[Wikilinks]] und [[Ziel|Alias]]."""
    text = """
Wir verlinken auf [[Zettelkasten Methodik]] und auch auf [[Architecture Principles|Prinzipien]].
Zusätzlich [[Zettelkasten Methodik]] als Duplikat und ein Anker [[Notiz#Sektion]].
"""
    parsed = parse_markdown(text)
    links = parsed.wikilinks

    assert len(links) == 3
    targets = [link["target"] for link in links]
    assert "Zettelkasten Methodik" in targets
    assert "Architecture Principles" in targets
    assert "Notiz" in targets

    alias_link = next(l for l in links if l["target"] == "Architecture Principles")
    assert alias_link["alias"] == "Prinzipien"


def test_parse_markdown_with_inline_tags():
    """Prüft das Extrahieren von Inline-Hashtags (#tag)."""
    text = """
# Notiz

Notiztext mit #wichtig und #projekt/alpha Tags.
Auch #tag-mit-bindestrich soll erkannt werden.
"""
    parsed = parse_markdown(text)

    assert "wichtig" in parsed.tags
    assert "projekt/alpha" in parsed.tags
    assert "tag-mit-bindestrich" in parsed.tags


def test_parse_markdown_corrupt_yaml_fallback():
    """Prüft das robuste Verhalten bei syntaktisch ungültigem Frontmatter-YAML."""
    corrupt_text = """---
title: [unclosed list
tags: {broken yaml
---

# Unbeirrt weiterlesen
Inhalt bleibt erhalten.
"""
    parsed = parse_markdown(corrupt_text)

    # Soll nicht crashen, sondern leeres Frontmatter und Fallback-Titel wählen
    assert parsed.frontmatter == {}
    assert parsed.title == "Unbeirrt weiterlesen"
    assert "Inhalt bleibt erhalten." in parsed.content


def test_serialize_markdown_with_frontmatter():
    """Prüft die Serialisierung von Markdown mit Frontmatter."""
    fm = {"title": "Test Note", "tags": ["unit-test"]}
    body = "# Test Note\n\nBody-Text"
    serialized = serialize_markdown(body, fm)

    assert serialized.startswith("---")
    assert "title: Test Note" in serialized
    assert "unit-test" in serialized
    assert body in serialized

    # Re-parse Roundtrip
    reparsed = parse_markdown(serialized)
    assert reparsed.title == "Test Note"
    assert "unit-test" in reparsed.tags
    assert "Body-Text" in reparsed.content


def test_serialize_markdown_without_frontmatter():
    """Prüft Serialisierung ohne Frontmatter."""
    body = "Reiner Text ohne Metadaten."
    assert serialize_markdown(body, None) == body
