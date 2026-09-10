"""
core/obsidian_sync.py – Automatische Synchronisation und Backup von Projektdateien
in den Obsidian-Vault als Langzeitgedächtnis für Claude und Nachschlagewerk.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import (
    BASE_DIR,
    OBSIDIAN_AUTO_SYNC,
    OBSIDIAN_SYNC_FILES,
    OBSIDIAN_TARGET_DIR,
    OBSIDIAN_VAULT_PATH,
)
from core.git_runtime import non_interactive_git_env


@dataclass
class ObsidianSyncResult:
    """Ergebnis eines Synchronisationslaufs nach Obsidian."""
    success: bool
    target_dir: Path
    synced_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    failed_files: dict[str, str] = field(default_factory=dict)
    index_updated: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def format_summary(self) -> str:
        """Erzeugt eine übersichtliche Textzusammenfassung für Terminal & Logs."""
        lines = [
            f"🧠 Obsidian-Sync ({self.timestamp})",
            f"📂 Zielordner: {self.target_dir}",
        ]
        if self.synced_files:
            lines.append(f"  ✅ Aktualisiert ({len(self.synced_files)}): {', '.join(self.synced_files)}")
        if self.skipped_files:
            lines.append(f"  ⏭️ Unverändert ({len(self.skipped_files)}): {', '.join(self.skipped_files)}")
        if self.failed_files:
            lines.append("  ❌ Fehler:")
            for fname, err in self.failed_files.items():
                lines.append(f"     - {fname}: {err}")
        if self.index_updated:
            lines.append("  📝 Gedächtnis-Index '00_PROJEKT_GEDAECHTNIS.md' aktualisiert.")
        return "\n".join(lines)


def get_obsidian_destination(
    vault_path: str | Path | None = None,
    target_dir: str | Path | None = None,
) -> Path:
    """Ermittelt den absoluten Zielpfad im Obsidian-Vault."""
    vault = Path(vault_path or OBSIDIAN_VAULT_PATH)
    rel_target = Path(target_dir or OBSIDIAN_TARGET_DIR)
    if rel_target.is_absolute():
        return rel_target
    return vault / rel_target


def compute_sha256(file_path: Path) -> str:
    """Berechnet den SHA-256 Hash einer Datei."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _get_current_git_info(base_dir: Path) -> dict[str, str]:
    """Liest Branch und Commit-Hash des Projekts aus, falls git verfügbar ist."""
    info = {"branch": "unknown", "commit": "unknown"}
    try:
        # Timeout + nicht-interaktive Umgebung: ein hängendes git darf den Sync nie blockieren
        # (siehe core/git_runtime.py).
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=base_dir,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            env=non_interactive_git_env(),
        ).strip()
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=base_dir,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            env=non_interactive_git_env(),
        ).strip()
        info["branch"] = branch
        info["commit"] = commit
    except Exception:
        pass
    return info


def _create_markdown_wrapper(file_name: str, content: str, timestamp: str) -> str:
    """Erstellt für Nicht-Markdown-Dateien (.env.example, .gitignore) ein lesbares .md Pendant."""
    syntax = "ini" if "env" in file_name.lower() else "gitignore" if "gitignore" in file_name.lower() else "text"

    return f"""---
type: project-backup
source_file: {file_name}
last_synced: {timestamp}
tags:
  - backup
  - memory
  - ai-team
---

# 📄 Backup: `{file_name}`

> [!info] Automatisch synchronisiert aus dem Projekt `AI-Softwareentwickler-Team` am {timestamp}.
> Diese Datei dient als Volltext-Gedächtnis für Claude und als Suchindex in Obsidian.

```{syntax}
{content}
```
"""


def _generate_memory_index(
    target_dir: Path,
    file_records: list[dict[str, str]],
    timestamp: str,
    git_info: dict[str, str],
) -> None:
    """Erstellt oder aktualisiert die zentrale Gedächtnis-Notiz '00_PROJEKT_GEDAECHTNIS.md'."""
    index_path = target_dir / "00_PROJEKT_GEDAECHTNIS.md"

    rows = []
    for r in file_records:
        md_link = f"[[{r['target_name']}]]"
        rows.append(f"| {md_link} | `{r['original_name']}` | {r['size_str']} | {r['status']} |")

    table_content = "\n".join(rows) if rows else "| *Keine Dateien synchronisiert* | - | - | - |"

    content = f"""---
type: projekt-gedaechtnis
project: AI-Softwareentwickler-Team
last_synced: {timestamp}
git_branch: {git_info.get('branch', 'unknown')}
git_commit: {git_info.get('commit', 'unknown')}
tags:
  - ai-team
  - memory
  - backup
  - status
---

# 🧠 Projekt-Gedächtnis: AI-Softwareentwickler-Team

> [!note] Claude-Gedächtnis & Wissensspeicher
> Dieses Verzeichnis wird automatisch aus dem Live-Projekt synchronisiert.
> Es enthält alle Kern-Konfigurationen, Architektur-Pläne, den aktuellen Zwischenstand
> und das Änderungsprotokoll des 33-köpfigen KI-Entwickler-Teams.
> 
> **Letzter Sync:** `{timestamp}` | **Git:** `{git_info.get('branch', 'unknown')}@{git_info.get('commit', 'unknown')}`

---

## 📂 Synchronisierte Dokumente

| Obsidian-Notiz | Originaldatei | Größe | Status |
| :--- | :--- | :--- | :--- |
{table_content}

---

## 🎯 Schnelleinstieg für Claude
- **Architektur & Agenten-Hierarchie:** [[ARCHITECTURE.md]] (Erklärt die 6 Fachbereiche & 33 Rollen)
- **Letzter Entwicklungs- & Teststand:** [[ZWISCHENSTAND_KI_TEAM_PROJEKT.md]] (Detaillierter Lauf-Status)
- **Projekt-Handbuch & CLI-Befehle:** [[README.md]]
- **Umgebungsvariablen-Vorlage (KEINE echten Secrets):** [[.env.example.md]]
- **Changelog & Historie realer Bugfixes:** [[CHANGELOG.md]]
- **Übergeordnete Lernprojekt-Notiz:** [[AI-Softwareentwickler-Team - Übersicht]]

---
*Automatisch generiert durch `core/obsidian_sync.py`.*
"""
    index_path.write_text(content, encoding="utf-8")


def sync_project_to_obsidian(
    vault_path: str | Path | None = None,
    target_dir: str | Path | None = None,
    files_to_sync: list[str] | None = None,
    force: bool = False,
) -> ObsidianSyncResult:
    """Synchronisiert Projektdateien in den angegebenen Obsidian-Vault.
    
    Args:
        vault_path: Pfad zum Obsidian-Vault (Standard aus config).
        target_dir: Zielordner im Vault (Standard aus config).
        files_to_sync: Liste von Dateinamen im Projekt-Wurzelverzeichnis.
        force: Wenn True, werden auch unveränderte Dateien überschrieben.
    """
    dest_path = get_obsidian_destination(vault_path, target_dir)
    src_base = Path(BASE_DIR)
    file_list = files_to_sync or OBSIDIAN_SYNC_FILES

    result = ObsidianSyncResult(
        success=True,
        target_dir=dest_path,
    )

    try:
        dest_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        result.success = False
        result.failed_files["[DIRECTORY]"] = f"Zielordner konnte nicht erstellt werden: {e}"
        return result

    file_records: list[dict[str, str]] = []
    git_info = _get_current_git_info(src_base)

    for file_name in file_list:
        # Realer Fund: OBSIDIAN_SYNC_FILES enthielt ".env" als Standardwert - der Sync kopiert
        # Dateien unredigiert, dadurch landeten ECHTE, aktive API-Keys im Vault, außerhalb des
        # durch dieses Repo kontrollierten .gitignore-Schutzes (ein Obsidian-Vault wird
        # typischerweise über einen eigenen, hier nicht kontrollierten Dienst verteilt -
        # Obsidian Sync, iCloud, Dropbox, Plugins). Der Konfigurations-Default wurde auf
        # ".env.example" umgestellt, aber ein zusätzlicher harter Guard HIER schützt auch
        # gegen eine künftige Fehlkonfiguration (z.B. OBSIDIAN_SYNC_FILES per .env versehentlich
        # wieder auf ".env" gesetzt) - Secrets gehören NIE in ein Sync-Ziel, das dieses Projekt
        # nicht kontrolliert, unabhängig davon, was konfiguriert wurde. Bewusst exakter
        # Dateiname-Vergleich (keine Endung/Substring-Prüfung): ".env.example" bleibt erlaubt.
        if file_name == ".env":
            result.failed_files[file_name] = "Sicherheitssperre: '.env' enthält echte Secrets und wird NIE synchronisiert (siehe '.env.example')."
            continue

        src_file = src_base / file_name
        if not src_file.exists():
            continue

        try:
            # 1:1 Rohdatei im Ziel
            dest_file = dest_path / file_name
            src_hash = compute_sha256(src_file)
            dest_hash = compute_sha256(dest_file) if dest_file.exists() else None

            changed = force or (src_hash != dest_hash)

            if changed:
                shutil.copy2(src_file, dest_file)
                result.synced_files.append(file_name)
                status_label = "Aktualisiert"
            else:
                result.skipped_files.append(file_name)
                status_label = "Aktuell"

            # Falls keine Markdown-Datei (.env.example, .gitignore, ...): Erzeuge zusätzlich .md Pendant
            is_markdown = file_name.lower().endswith(".md")
            target_display_name = file_name
            if not is_markdown:
                md_target_name = f"{file_name}.md"
                md_dest_file = dest_path / md_target_name
                content = src_file.read_text(encoding="utf-8", errors="replace")
                wrapped_content = _create_markdown_wrapper(file_name, content, result.timestamp)
                md_dest_file.write_text(wrapped_content, encoding="utf-8")
                target_display_name = md_target_name

            # Metadaten für den Index erfassen
            size_bytes = src_file.stat().st_size
            size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1048576 else f"{size_bytes / 1048576:.2f} MB"
            file_records.append({
                "original_name": file_name,
                "target_name": target_display_name,
                "size_str": size_str,
                "status": status_label,
            })

        except Exception as e:
            result.failed_files[file_name] = str(e)
            result.success = False

    # Gedächtnis-Index schreiben
    try:
        _generate_memory_index(dest_path, file_records, result.timestamp, git_info)
        result.index_updated = True
    except Exception as e:
        result.failed_files["00_PROJEKT_GEDAECHTNIS.md"] = f"Index-Erstellung fehlgeschlagen: {e}"

    return result


def auto_sync_if_enabled() -> ObsidianSyncResult | None:
    """Führt automatische Synchronisation durch, sofern in config aktiviert."""
    if not OBSIDIAN_AUTO_SYNC:
        return None
    return sync_project_to_obsidian()


_SYNC_HEALTH_TICKET_ID = "obsidian-sync-health"


def record_sync_health_ticket(result: ObsidianSyncResult | None, exception: Exception | None = None) -> None:
    """
    Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, echter Fund): interface/cli.py rief
    auto_sync_if_enabled() bisher in einem try/except auf, das einen Fehlschlag NUR auf der
    Konsole ausgab (`console.print(f"⚠️ Obsidian-Sync fehlgeschlagen: {e}")`) - unsichtbar für
    jeden autonomen Lauf ohne Terminal-Zuschauer und ohne jede Spur, sobald die nächste
    Konsolenzeile den Hinweis verdrängt hat. Das externe Gedächtnis (core/obsidian_sync.py
    synchronisiert README/CHANGELOG/ARCHITECTURE/Zwischenstand in den Obsidian-Vault) driftet
    dadurch unbemerkt vom Live-Code weg, wenn z.B. der Vault-Pfad zeitweise nicht erreichbar ist
    (externe Sync-Software, USB-Laufwerk, Netzwerkpfad).

    Legt bei einem Fehlschlag (Exception ODER result.success=False) ein stabiles Backlog-Ticket
    an/aktualisiert es - sichtbar im Kanban-Board statt nur einer flüchtigen Konsolenzeile.
    Schließt es automatisch wieder, sobald ein späterer Sync erfolgreich war (mechanische
    Tatsachenfeststellung, dasselbe Prinzip wie core/optimization_advisor.py.close_resolved_
    unused_agent_tickets()). Best-effort: ein Fehler beim Ticket-Schreiben selbst darf den Sync-
    Aufruf nie zum Absturz bringen.
    """
    from core.backlog_store import get_ticket, upsert_ticket

    failed = exception is not None or (result is not None and not result.success)
    try:
        if failed:
            detail = str(exception) if exception is not None else "; ".join(
                f"{f}: {err}" for f, err in (result.failed_files.items() if result else [])
            ) or "Unbekannter Fehler"
            upsert_ticket(
                ticket_id=_SYNC_HEALTH_TICKET_ID, title="Obsidian-Gedächtnis-Sync fehlgeschlagen",
                source="orchestrator", status="blocked", project_slug="_team",
                detail=f"Externes Gedächtnis driftet vom Live-Code weg: {detail}",
            )
        elif result is not None and result.success and get_ticket(_SYNC_HEALTH_TICKET_ID) is not None:
            # Nur schliessen, wenn zuvor tatsaechlich ein Fehlschlag-Ticket existierte - sonst
            # legt jeder einzelne erfolgreiche Sync ein nutzloses "done"-Ticket ohne vorherigen
            # Befund an.
            upsert_ticket(
                ticket_id=_SYNC_HEALTH_TICKET_ID, title="Obsidian-Gedächtnis-Sync fehlgeschlagen",
                source="orchestrator", status="done", project_slug="_team",
                detail="Ein späterer Sync-Lauf war wieder erfolgreich - automatisch geschlossen.",
            )
    except Exception:
        # Wie im Docstring beschrieben: ein fehlgeschlagenes Ticket-Update darf den eigentlichen
        # Sync-Vorgang nie beeinträchtigen.
        pass
