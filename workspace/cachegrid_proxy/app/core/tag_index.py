"""Invertierter Tag-Index für $O(1)$-Selektiv-Invalidierung von Cache-Keys."""

from collections import defaultdict


class TagIndex:
    """Verwaltet bidirektionale Zuordnungen zwischen Cache-Keys und Tags."""

    def __init__(self) -> None:
        # tag -> set(keys)
        self._tag_to_keys: dict[str, set[str]] = defaultdict(set)
        # key -> set(tags)
        self._key_to_tags: dict[str, set[str]] = defaultdict(set)

    def associate(self, key: str, tags: list[str] | set[str]) -> None:
        """Verknüpft einen Key mit einer Liste von Tags."""
        if not tags:
            return
        for tag in tags:
            tag_clean = tag.strip()
            if tag_clean:
                self._tag_to_keys[tag_clean].add(key)
                self._key_to_tags[key].add(tag_clean)

    def disassociate_key(self, key: str) -> set[str]:
        """Entfernt einen Key und alle seine Tag-Verknüpfungen.
        
        Gibt die vorher verknüpften Tags zurück.
        """
        tags = self._key_to_tags.pop(key, set())
        for tag in tags:
            if tag in self._tag_to_keys:
                self._tag_to_keys[tag].discard(key)
                if not self._tag_to_keys[tag]:
                    del self._tag_to_keys[tag]
        return tags

    def get_keys_for_tag(self, tag: str) -> set[str]:
        """Liefert alle Keys, die mit dem angegebenen Tag markiert sind."""
        return set(self._tag_to_keys.get(tag, set()))

    def get_tags_for_key(self, key: str) -> set[str]:
        """Liefert alle Tags für einen bestimmten Key."""
        return set(self._key_to_tags.get(key, set()))

    def get_all_tags(self) -> dict[str, int]:
        """Liefert ein Dictionary aller aktiven Tags und ihrer Key-Anzahlen."""
        return {tag: len(keys) for tag, keys in self._tag_to_keys.items()}

    def clear(self) -> None:
        """Leert den gesamten Tag-Index."""
        self._tag_to_keys.clear()
        self._key_to_tags.clear()
