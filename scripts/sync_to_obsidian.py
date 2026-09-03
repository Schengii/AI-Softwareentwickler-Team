"""
scripts/sync_to_obsidian.py – Manuelles Ausführen des Obsidian-Syncs

Verwendung:
    python scripts/sync_to_obsidian.py [--force] [--vault <pfad>] [--target <pfad>]
"""

import argparse
import sys
from pathlib import Path

# Sicherstellen, dass das Projektverzeichnis im sys.path liegt
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.obsidian_sync import sync_project_to_obsidian


def main():
    parser = argparse.ArgumentParser(
        description="Synchronisiert Kern-Dateien des AI-Softwareentwickler-Teams in den Obsidian-Vault als Claude-Gedächtnis."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Erzwingt das Überschreiben aller Dateien, auch wenn unverändert.",
    )
    parser.add_argument(
        "--vault",
        type=str,
        default=None,
        help="Benutzerdefinierter Pfad zum Obsidian-Vault (Standard aus config).",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Zielunterverzeichnis im Vault (Standard aus config).",
    )

    args = parser.parse_args()

    print("🚀 Starte Synchronisation in den Obsidian-Vault...")
    result = sync_project_to_obsidian(
        vault_path=args.vault,
        target_dir=args.target,
        force=args.force,
    )

    print(result.format_summary())

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
