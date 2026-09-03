"""
scripts/watch_obsidian_sync.py – Hintergrund-Watcher für sofortigen Auto-Sync nach Obsidian

Überwacht die Projektdateien (.env.example, README.md, ZWISCHENSTAND_KI_TEAM_PROJEKT.md, etc.)
und spiegelt Änderungen sofort nach Obsidian, sobald sie gespeichert werden.

Verwendung:
    python scripts/watch_obsidian_sync.py [--interval 2.0]
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

# Sicherstellen, dass das Projektverzeichnis im sys.path liegt
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from config import BASE_DIR, OBSIDIAN_SYNC_FILES
from core.obsidian_sync import sync_project_to_obsidian


def get_files_mtime(base_dir: Path, files: list[str]) -> dict[str, float]:
    """Liest die Modifikationszeitstempel der überwachten Dateien aus."""
    mtimes = {}
    for f in files:
        p = base_dir / f
        if p.exists():
            try:
                mtimes[f] = p.stat().st_mtime
            except OSError:
                pass
    return mtimes


def run_watcher(interval: float = 2.0):
    """Überwacht Dateimodifikationen in einer nicht-blockierenden Polling-Schleife."""
    src_base = Path(BASE_DIR)
    print("👁️  Obsidian-Sync Watcher gestartet.")
    print(f"📁 Überwachtes Projekt: {src_base}")
    print(f"📄 Überwachte Dateien: {', '.join(OBSIDIAN_SYNC_FILES)}")
    print(f"⏱️  Prüfintervall: {interval}s (Beenden mit Strg+C)\n")

    # Initialer Abgleich beim Start
    print("🔄 Führe initialen Abgleich durch...")
    initial_res = sync_project_to_obsidian()
    print(initial_res.format_summary())
    print("\n🟢 Watcher ist aktiv und lauscht auf Dateiänderungen...\n")

    last_mtimes = get_files_mtime(src_base, OBSIDIAN_SYNC_FILES)

    try:
        while True:
            time.sleep(interval)
            current_mtimes = get_files_mtime(src_base, OBSIDIAN_SYNC_FILES)

            changed = False
            for f, mtime in current_mtimes.items():
                if f not in last_mtimes or mtime > last_mtimes[f]:
                    changed = True
                    break

            if changed:
                # Kurzes Debounce, falls gerade mehrere Dateien gleichzeitig gespeichert werden
                time.sleep(0.5)
                current_mtimes = get_files_mtime(src_base, OBSIDIAN_SYNC_FILES)
                last_mtimes = current_mtimes

                now_str = datetime.now().strftime("%H:%M:%S")
                print(f"[{now_str}] 🔔 Änderung erkannt – synchronisiere nach Obsidian...")
                result = sync_project_to_obsidian()
                if result.synced_files:
                    print(f"[{now_str}] ✅ Aktualisiert: {', '.join(result.synced_files)}")
                else:
                    print(f"[{now_str}] ℹ️ Keine Hash-Änderung festgestellt.")

    except KeyboardInterrupt:
        print("\n🛑 Obsidian-Sync Watcher beendet.")


def main():
    parser = argparse.ArgumentParser(description="Live-Watcher für Obsidian-Sync.")
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Polling-Intervall in Sekunden (Standard: 2.0)",
    )
    args = parser.parse_args()
    run_watcher(interval=args.interval)


if __name__ == "__main__":
    main()
