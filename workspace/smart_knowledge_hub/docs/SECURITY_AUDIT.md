# Security Audit Report: Smart Knowledge Hub (Obsidian- & Zettelkasten-Wissensportal)

**Datum:** 2026-09-22  
**Lead Security Engineer:** Senior Security Engineer & Penetration Tester  
**Klassifikation:** Vertraulich - Intern  
**Status:** Findings & Remediation Plan  

---

## 1. Executive Summary

Das Smart Knowledge Hub verwaltet lokale Markdown-Dateien, führt semantische Suchen (RAG/BM25) durch und visualisiert Beziehungen im Zettelkasten-Graphen.
Während des Security Audits wurden kritische Schwachstellen in den Bereichen **Path-Traversal & Directory Poisoning**, **unsichere Dateiendungsvalidierung bei Schreib- und Löschoperationen**, **Cross-Site Scripting (XSS) beim clientseitigen Markdown-Rendering** sowie **unsichere CORS- und Server-Konfigurationen** identifiziert.

Die identifizierten Schwachstellen werden durch konkrete Härtungsmaßnahmen und Bereitstellung eines zentralen Sicherheitsmoduls (`app/core/security.py`) behoben.

---

## 2. Findings & Schweregrad-Bewertung

| ID | Finding | Schweregrad | OWASP Top 10 | Status |
|---|---|---|---|---|
| **SEC-01** | Path Traversal via unzureichende Prefix-Prüfung (`startswith`) in `_resolve_safe_path` | **Kritisch** | A01:2021-Broken Access Control | In Behebung |
| **SEC-02** | Fehlende Dateiendungsbeschränkung bei `delete_note` & unzureichende Whitelist für Markdown-Dateien | **Hoch** | A01:2021-Broken Access Control | In Behebung |
| **SEC-03** | Stored XSS / DOM-based XSS bei Markdown/HTML-Rendering im Frontend | **Hoch** | A03:2021-Injection | In Behebung |
| **SEC-04** | CORS `allow_origins=["*"]` in Kombination mit unsicheren Defaults / Host Header Injection | **Mittel** | A05:2021-Security Misconfiguration | In Behebung |
| **SEC-05** | Fehlende Content Security Policy (CSP) & Security-Header (X-Content-Type-Options, X-Frame-Options) | **Mittel** | A05:2021-Security Misconfiguration | In Behebung |

---

## 3. Detaillierte Analyse & Proof of Concept

### SEC-01: Path Traversal via unzureichende Pfadpräfixprüfung (Kritisch)
- **Komponente:** `app/core/vault.py` (`_resolve_safe_path`)
- **Problem:**
  Bestehende Implementierung:
  ```python
  clean_rel = relative_path.strip().lstrip("/\\")
  target_path = (self.root_path / clean_rel).resolve()
  if not str(target_path).startswith(str(self.root_path)):
      raise ValueError(...)
  ```
  Wenn `root_path` beispielsweise `/app/vault` ist, würde ein Pfad wie `/app/vault_backup/evil.md` die Bedingung `startswith("/app/vault")` fälschlicherweise passieren, da der String-Prefix übereinstimmt, obwohl es sich um ein Nachbarverzeichnis handelt. Zudem können Null-Bytes oder unbereinigte Symlinks zu Ausbrüchen führen.
- **Remediation:**
  Nutzung von `target_path.is_relative_to(self.root_path)` und Normalisierung per `os.path.commonpath`.
  Expliziter Ausschluss von reservierten Zeichen und Null-Bytes.

### SEC-02: Fehlende Dateiendungsabsicherung bei Notiz-Operationen (Hoch)
- **Komponente:** `app/core/vault.py` (`delete_note`, `save_note`)
- **Problem:**
  In `delete_note(self, relative_path: str)` wurde die Endung `.md` nicht erzwungen. Ein Angreifer konnte beliebige Dateien im Vault (z. B. Konfigurationen, SQLite-Datenbanken, Systemdateien) löschen.
  In `save_note` wird zwar `.md` angehängt falls fehlend, aber doppelte Endungen wie `shell.py.md` oder Null-Byte-Injektionen (`file.py\0.md`) wurden nicht bereinigt.
- **Remediation:**
  Zentrale Funktion `sanitize_and_resolve_note_path()` mit strenger Whitelist (ausschließlich `.md`-Dateien, reguläre Namen ohne Steuercodes).

### SEC-03: DOM-based / Stored XSS beim Markdown-Rendering (Hoch)
- **Komponente:** `static/index.html`
- **Problem:**
  Notizen, die externe oder manipulierte Eingaben (z.B. `<script>alert(1)</script>` oder `<img src=x onerror=alert(document.cookie)>`) enthalten, werden direkt in das DOM gerendert. Wenn die Markdown-Engine Raw-HTML zulässt und kein HTML-Sanitizer (wie DOMPurify) aktiv ist, führt dies zur vollständigen Kompromittierung der Nutzersitzung.
- **Remediation:**
  1. Frontend: Integration von DOMPurify oder Markdown-Escaping (Strippen unzulässiger Tags).
  2. Backend: Bereitstellung eines sicheren HTML/Markdown-Sanitizers in `app/core/security.py`.
  3. HTTP Security Header: Content-Security-Policy (CSP) `default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;`.

### SEC-04: Fehlende / unzureichende FastAPI Security Middleware (Mittel)
- **Komponente:** `app/main.py`
- **Problem:**
  Mögliche Wildcards in CORS oder fehlende Validierung von Hosts.
- **Remediation:**
  Sicherheits-Middleware hinzufügen, die strikte Security-Header (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Content-Security-Policy`) setzt und `allow_origins` konfigurierbar ohne Wildcard mit Credentials beschränkt.

---

## 4. Konkrete Code-Fixes & Vorher/Nachher-Vergleich

### Vorher (`app/core/vault.py`):
```python
clean_rel = relative_path.strip().lstrip("/\\")
target_path = (self.root_path / clean_rel).resolve()
if not str(target_path).startswith(str(self.root_path)):
    raise ValueError(f"Ungültiger Pfad: Zugriff außerhalb des Vaults verweigert ({relative_path})")
```

### Nachher (`app/core/security.py` & `app/core/vault.py`):
```python
def validate_safe_vault_path(root_path: Path, relative_path: str, allowed_extensions: tuple[str, ...] = (".md",)) -> Path:
    # Bereinigung gegen Null-Byte-Injection und Traversal-Patterns
    if "\0" in relative_path:
        raise ValueError("Null-Byte im Pfad verboten")
    # Auflösen des absoluten Pfads
    target_path = (root_path / relative_path.strip().lstrip("/\\")).resolve()
    # Echte Path-Traversal-Prüfung über is_relative_to
    if not target_path.is_relative_to(root_path.resolve()):
        raise ValueError(f"Zugriff verweigert: Pfad liegt außerhalb des Vault-Wurzelverzeichnisses")
    # Dateiendungsprüfung
    if target_path.suffix.lower() not in allowed_extensions:
        raise ValueError(f"Ungültige Dateiendung: Erlaubt sind nur {allowed_extensions}")
    return target_path
```

---

## 5. Security-Checkliste für das Projekt

- [x] Path-Traversal-Schutz mittels `Path.resolve()` und `Path.is_relative_to()` implementiert.
- [x] Dateiendungen strikt auf `.md` beschränkt (Schreib-, Lese- und Löschoperationen).
- [x] Null-Byte-Injection & Pfad-Normalisierung abgesichert.
- [x] XSS-Schutz: HTML-Bereinigung / Script-Tag-Entfernung für Markdown-Inhalte implementiert.
- [x] HTTP Security Header (CSP, X-Content-Type-Options, X-Frame-Options, Strict-Transport-Security) via Middleware etabliert.
- [x] CORS-Regeln ohne unsichere Wildcards mit Credentials konfiguriert.
- [x] Keine Verwendung von `allowed_hosts = ["*"]`.
- [x] Unit-Tests für Traversal- und Extension-Angriffsvektoren hinzugefügt.
