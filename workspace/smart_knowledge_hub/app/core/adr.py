import datetime
import re
from typing import Any

from app.core.vault import VaultManager, vault_manager


class ADRGenerator:
    def __init__(self, vault_manager: VaultManager, adr_subfolder: str = "03 Resources/ADRs"):
        self.vault_manager = vault_manager
        self.adr_subfolder = adr_subfolder

    async def _get_next_adr_number(self) -> int:
        notes = await self.vault_manager.list_notes()
        max_num = 0
        adr_pattern = re.compile(r"(\d{4})-[a-z0-9\-]+\.md$", re.IGNORECASE)
        for note in notes:
            path = note["path"]
            match = adr_pattern.search(path)
            if match:
                num = int(match.group(1))
                max_num = max(max_num, num)
        return max_num + 1

    def _slugify(self, title: str) -> str:
        slug = title.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        return slug.strip("-")

    async def generate_adr(
        self,
        title: str,
        context: str,
        decision: str,
        consequences: str,
        status: str = "Accepted",
        related_notes: list[str] | None = None,
        tags: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Generiert ein Architecture Decision Record (ADR) im Nygard-Format und speichert es im Vault.
        """
        next_num = await self._get_next_adr_number()
        num_str = f"{next_num:04d}"
        slug = self._slugify(title)
        filename = f"{num_str}-{slug}.md"
        relative_path = f"{self.adr_subfolder}/{filename}"

        today_str = datetime.date.today().isoformat()
        
        all_tags = ["adr", "architecture"]
        if tags:
            for t in tags:
                clean_t = t.strip().lstrip("#")
                if clean_t and clean_t not in all_tags:
                    all_tags.append(clean_t)

        related_md = ""
        if related_notes:
            links = [f"- [[{note.strip()}]]" for note in related_notes if note.strip()]
            if links:
                related_md = "\n## Verwandte Notizen & Referenzen\n" + "\n".join(links) + "\n"

        frontmatter = {
            "title": f"ADR-{num_str}: {title}",
            "status": status,
            "date": today_str,
            "type": "adr",
            "tags": all_tags
        }

        content = f"""# ADR-{num_str}: {title}

**Status:** {status}  
**Datum:** {today_str}

## Kontext
{context.strip()}

## Entscheidung
{decision.strip()}

## Konsequenzen
{consequences.strip()}
{related_md}"""

        saved_note = await self.vault_manager.save_note(
            relative_path=relative_path,
            content=content,
            frontmatter=frontmatter
        )

        return {
            "adr_number": next_num,
            "filename": filename,
            "path": saved_note["path"],
            "title": frontmatter["title"],
            "status": status,
            "note": saved_note
        }


ADRService = ADRGenerator
adr_generator = ADRGenerator(vault_manager=vault_manager)
adr_service = adr_generator
