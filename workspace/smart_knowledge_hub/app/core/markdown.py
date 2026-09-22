import re
from typing import Any, Dict, List, Optional, Set, Tuple
import yaml


WIKILINK_PATTERN = re.compile(r"\[\[([^\[\]\|\#\n]+)(?:#[^\[\]\|\n]+)?(?:\|([^\[\]\n]+))?\]\]")
INLINE_TAG_PATTERN = re.compile(r"(?<!\S)#([a-zA-Z0-9_\-\/]+)(?!\S)")
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class ParsedNote:
    def __init__(
        self,
        raw_content: str,
        content: str,
        frontmatter: Dict[str, Any],
        wikilinks: List[Dict[str, str]],
        tags: List[str],
        title: Optional[str] = None
    ):
        self.raw_content = raw_content
        self.content = content
        self.frontmatter = frontmatter
        self.wikilinks = wikilinks
        self.tags = tags
        self.title = title or frontmatter.get("title") or ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "frontmatter": self.frontmatter,
            "wikilinks": self.wikilinks,
            "tags": self.tags,
            "content": self.content,
            "raw_content": self.raw_content
        }


def parse_markdown(raw_text: str, default_title: str = "") -> ParsedNote:
    """
    Parst Frontmatter (YAML), Markdown-Body, Wikilinks und Tags aus einem Markdown-String.
    """
    frontmatter: Dict[str, Any] = {}
    content = raw_text

    fm_match = FRONTMATTER_PATTERN.match(raw_text)
    if fm_match:
        yaml_content = fm_match.group(1)
        try:
            parsed_yaml = yaml.safe_load(yaml_content)
            if isinstance(parsed_yaml, dict):
                frontmatter = parsed_yaml
        except Exception:  # noqa: BLE001 - Robuste Behandlung von unvollständigem YAML
            frontmatter = {}
        content = raw_text[fm_match.end():]

    # Wikilinks extrahieren
    wikilinks: List[Dict[str, str]] = []
    seen_targets: Set[str] = set()
    for match in WIKILINK_PATTERN.finditer(content):
        target = match.group(1).strip()
        alias = match.group(2).strip() if match.group(2) else target
        if target and target not in seen_targets:
            seen_targets.add(target)
            wikilinks.append({"target": target, "alias": alias})

    # Tags sammeln
    tags_set: Set[str] = set()
    fm_tags = frontmatter.get("tags", [])
    if isinstance(fm_tags, list):
        for t in fm_tags:
            if t:
                tags_set.add(str(t).lstrip("#").strip())
    elif isinstance(fm_tags, str):
        for t in fm_tags.split(","):
            cleaned = t.strip().lstrip("#")
            if cleaned:
                tags_set.add(cleaned)

    # Inline-Tags
    for match in INLINE_TAG_PATTERN.finditer(content):
        tag_val = match.group(1).strip()
        if tag_val:
            tags_set.add(tag_val)

    # Titel bestimmen: Frontmatter > erste H1 (# Titel) > default_title
    title = str(frontmatter.get("title", "")).strip()
    if not title:
        h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1).strip()
        else:
            title = default_title

    return ParsedNote(
        raw_content=raw_text,
        content=content,
        frontmatter=frontmatter,
        wikilinks=wikilinks,
        tags=sorted(list(tags_set)),
        title=title
    )


def serialize_markdown(content: str, frontmatter: Optional[Dict[str, Any]] = None) -> str:
    """
    Serialisiert Frontmatter und Markdown-Content zu einem konsistenten Dateiinhalt.
    """
    if not frontmatter:
        return content

    yaml_str = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    clean_content = content.lstrip("\n")
    return f"---\n{yaml_str}\n---\n\n{clean_content}"
