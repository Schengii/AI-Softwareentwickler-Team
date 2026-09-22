from typing import Any, Dict, List, Optional, Set
from app.core.vault import VaultManager


class GraphBuilder:
    def __init__(self, vault_manager: VaultManager):
        self.vault_manager = vault_manager

    async def build_graph(self) -> Dict[str, Any]:
        """
        Baut den globalen Notizen-Graphen basierend auf Wikilinks auf.
        Liefert nodes, edges, unlinked_notes und unresolved_links.
        """
        notes = await self.vault_manager.list_notes()
        
        # Mappings zur schnellen Auflösung von Wikilinks:
        # 1. Titel -> rel_path
        # 2. Dateiname (ohne .md) -> rel_path
        # 3. rel_path -> rel_path
        title_to_path: Dict[str, str] = {}
        stem_to_path: Dict[str, str] = {}
        nodes: List[Dict[str, Any]] = []

        for note in notes:
            path = note["path"]
            title = note["title"] or path
            stem = path.rsplit("/", 1)[-1].replace(".md", "")
            
            title_to_path[title.lower()] = path
            stem_to_path[stem.lower()] = path
            title_to_path[path.lower()] = path

            nodes.append({
                "id": path,
                "label": title,
                "title": title,
                "path": path,
                "tags": note.get("tags", []),
                "type": note.get("frontmatter", {}).get("type", "note"),
                "size": len(note.get("wikilinks", [])) + 1
            })

        edges: List[Dict[str, Any]] = []
        edge_keys: Set[str] = set()
        unresolved_links: List[Dict[str, str]] = []
        connected_node_ids: Set[str] = set()

        for note in notes:
            source_path = note["path"]
            for link in note.get("wikilinks", []):
                target_raw = link["target"].strip()
                target_lower = target_raw.lower()

                target_path = None
                if target_lower in stem_to_path:
                    target_path = stem_to_path[target_lower]
                elif target_lower in title_to_path:
                    target_path = title_to_path[target_lower]
                elif target_lower.endswith(".md") and target_lower[:-3] in stem_to_path:
                    target_path = stem_to_path[target_lower[:-3]]

                if target_path:
                    edge_key = f"{source_path}->{target_path}"
                    if edge_key not in edge_keys:
                        edge_keys.add(edge_key)
                        edges.append({
                            "source": source_path,
                            "target": target_path,
                            "type": "wikilink",
                            "alias": link.get("alias")
                        })
                        connected_node_ids.add(source_path)
                        connected_node_ids.add(target_path)
                else:
                    unresolved_links.append({
                        "source": source_path,
                        "target": target_raw
                    })

        orphans = [n["id"] for n in nodes if n["id"] not in connected_node_ids]

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_notes": len(nodes),
                "total_links": len(edges),
                "orphaned_notes": len(orphans),
                "unresolved_links": len(unresolved_links)
            },
            "unresolved_links": unresolved_links
        }

    async def get_backlinks(self, target_path: str) -> List[Dict[str, Any]]:
        """
        Ermittelt alle Notizen, die per Wikilink auf die gegebene Notiz verweisen.
        """
        graph = await self.build_graph()
        target_clean = target_path.strip().lstrip("/")
        if not target_clean.endswith(".md"):
            target_clean = f"{target_clean}.md"

        backlinks = []
        for edge in graph["edges"]:
            if edge["target"] == target_clean:
                backlinks.append({
                    "source": edge["source"],
                    "alias": edge.get("alias")
                })
        return backlinks
