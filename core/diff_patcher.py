"""
core/diff_patcher.py – Unified-Diff & Hunk-Patcher Engine für chirurgische Code-Refactorings

Erlaubt es Agenten, bestehende Dateien gezielt per Unified-Diff oder Search/Replace-Blöcken
zu modifizieren, anstatt hunderte Zeilen unberührten Code neu zu generieren.
Spart bis zu 70 % Tokens bei Code-Modifikationen und schützt vor versehentlichem Codeverlust.
"""

from __future__ import annotations

import re
from pathlib import Path


def apply_search_replace_patch(original_text: str, patch_text: str) -> tuple[bool, str, str]:
    """Wendet einen oder mehrere SEARCH/REPLACE Blöcke auf den Quelltext an.
    
    Format:
    <<<<<<< SEARCH
    alter code
    =======
    neuer code
    >>>>>>> REPLACE
    """
    pattern = re.compile(
        r"<<<<<<<\s*SEARCH\r?\n([\s\S]*?)\r?\n=======\r?\n([\s\S]*?)\r?\n>>>>>>>\s*REPLACE",
        re.MULTILINE,
    )

    matches = list(pattern.finditer(patch_text))
    if not matches:
        return False, original_text, "Keine gültigen SEARCH/REPLACE Blöcke im Patch gefunden."

    current_text = original_text
    applied_count = 0

    for i, match in enumerate(matches, 1):
        search_block = match.group(1)
        replace_block = match.group(2)

        if search_block in current_text:
            # Ersetze nur das erste Vorkommen dieses spezifischen Blocks
            current_text = current_text.replace(search_block, replace_block, 1)
            applied_count += 1
        else:
            # Fuzzy-Versuch: Normalisiere Zeilenenden
            norm_search = "\n".join(line.rstrip() for line in search_block.splitlines())
            norm_current = "\n".join(line.rstrip() for line in current_text.splitlines())

            if norm_search in norm_current:
                # Wende auf normalisierten Text an
                norm_replace = "\n".join(line.rstrip() for line in replace_block.splitlines())
                current_text = norm_current.replace(norm_search, norm_replace, 1)
                applied_count += 1
            else:
                snippet = search_block[:100].replace("\n", "\\n")
                return False, original_text, f"Block {i} konnte nicht zugeordnet werden. Suchmuster nicht gefunden:\n'{snippet}...'"

    return True, current_text, f"{applied_count} Block/Blöcke erfolgreich angewendet."


def apply_unified_diff(original_text: str, diff_text: str) -> tuple[bool, str, str]:
    """Wendet ein Standard-Unified-Diff (@@ -start,len +start,len @@) auf original_text an."""
    orig_lines = original_text.splitlines(keepends=True)
    diff_lines = diff_text.splitlines()

    # Finde Hunks: Zeilen beginnend mit @@ ... @@
    hunk_indices = [i for i, line in enumerate(diff_lines) if line.startswith("@@")]
    if not hunk_indices:
        return False, original_text, "Keine gültigen @@ Hunk-Header im Diff gefunden."

    # Zerlege diff_lines in Hunks
    hunks = []
    for idx, start_idx in enumerate(hunk_indices):
        end_idx = hunk_indices[idx + 1] if idx + 1 < len(hunk_indices) else len(diff_lines)
        hunks.append(diff_lines[start_idx:end_idx])

    result_lines = list(orig_lines)

    # Wende Hunks von hinten nach vorne an, um Zeilenverschiebung zu minimieren
    # Oder sequenziell mit Offset-Tracking
    hunk_regex = re.compile(r"^@@\s*-(\d+)(?:,(\d+))?\s*\+(\d+)(?:,(\d+))?\s*@@")

    line_offset = 0

    for hunk_idx, hunk in enumerate(hunks, 1):
        header = hunk[0]
        match = hunk_regex.match(header)
        if not match:
            continue

        orig_start = int(match.group(1)) - 1  # 0-basiert
        target_idx = max(0, orig_start + line_offset)

        # Extrahiere Kontext- und Diff-Zeilen
        context_lines_before: list[str] = []
        old_lines_to_remove: list[str] = []
        new_lines_to_add: list[str] = []

        for line in hunk[1:]:
            if line.startswith("-"):
                old_lines_to_remove.append(line[1:])
            elif line.startswith("+"):
                new_lines_to_add.append(line[1:])
            elif line.startswith(" "):
                # Unveränderte Kontextzeile
                if not old_lines_to_remove:
                    context_lines_before.append(line[1:])
                else:
                    # Nach Änderungen
                    pass

        # Finde passende Zeile im Dokument (mit Toleranz für Zeilenverschiebungen)
        search_window_start = max(0, target_idx - 15)
        search_window_end = min(len(result_lines), target_idx + 25)

        found_pos = -1
        # 1. Exakte Suche
        for candidate_pos in range(search_window_start, search_window_end + 1):
            if candidate_pos + len(context_lines_before) <= len(result_lines):
                matches = True
                for c_i, ctx in enumerate(context_lines_before):
                    if result_lines[candidate_pos + c_i].rstrip("\r\n") != ctx.rstrip("\r\n"):
                        matches = False
                        break
                if matches:
                    found_pos = candidate_pos + len(context_lines_before)
                    break

        if found_pos == -1:
            found_pos = target_idx

        # Prüfe ob alte Zeilen an found_pos übereinstimmen
        remove_count = len(old_lines_to_remove)
        actual_slice = result_lines[found_pos:found_pos + remove_count]
        actual_slice_stripped = [line.rstrip("\r\n") for line in actual_slice]
        old_stripped = [line.rstrip("\r\n") for line in old_lines_to_remove]

        if actual_slice_stripped != old_stripped and old_stripped:
            # Versuche in naher Umgebung nach exaktem Match von old_stripped zu suchen
            fuzzy_found = -1
            for pos in range(max(0, found_pos - 20), min(len(result_lines) - len(old_stripped) + 1, found_pos + 20)):
                if [line.rstrip("\r\n") for line in result_lines[pos:pos + len(old_stripped)]] == old_stripped:
                    fuzzy_found = pos
                    break
            if fuzzy_found != -1:
                found_pos = fuzzy_found
            else:
                return (
                    False,
                    original_text,
                    f"Hunk {hunk_idx} konnte nicht angewendet werden: Erwartete Zeilen stimmen nicht überein.\n"
                    f"Erwartet: {old_stripped}\n"
                    f"Gefunden: {actual_slice_stripped}",
                )

        # Ersetze Slice durch neue Zeilen
        formatted_new_lines = [line if line.endswith("\n") else line + "\n" for line in new_lines_to_add]
        result_lines[found_pos:found_pos + remove_count] = formatted_new_lines
        line_offset += len(formatted_new_lines) - remove_count


    return True, "".join(result_lines), f"{len(hunks)} Hunk(s) erfolgreich angewendet."


def patch_content(original_text: str, patch_str: str) -> tuple[bool, str, str]:
    """Erkennt automatisch das Diff-Format (SEARCH/REPLACE oder Unified-Diff) und wendet es an."""
    if "<<<<<<< SEARCH" in patch_str and ">>>>>>> REPLACE" in patch_str:
        return apply_search_replace_patch(original_text, patch_str)
    elif "@@" in patch_str:
        return apply_unified_diff(original_text, patch_str)
    else:
        return False, original_text, "Unbekanntes Diff-Format. Unterstützt werden Unified-Diffs (@@ ... @@) und SEARCH/REPLACE-Blöcke."


def patch_file(file_path: Path | str, patch_str: str) -> tuple[bool, str]:
    """Wendet einen Patch direkt auf eine Datei an."""
    p = Path(file_path).resolve()
    if not p.exists():
        return False, f"Datei existiert nicht: {p}"

    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Konnte Datei nicht lesen: {e}"

    success, patched_content, message = patch_content(content, patch_str)
    if not success:
        return False, message

    try:
        p.write_text(patched_content, encoding="utf-8")
        return True, message
    except Exception as e:
        return False, f"Konnte geänderte Datei nicht schreiben: {e}"
