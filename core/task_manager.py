"""
core/task_manager.py – Analysiert Nutzeraufgaben und zerlegt sie in Teilaufgaben (30 Spezialisten)
"""

import json
import re
import uuid

from config import ENABLE_NICHE_AGENT_FILTER
from core.llm_factory import LLMFactory
from core.message_bus import AgentTask
from core.team_memory import format_team_lessons_for_agents

# ──────────────────────────────────────────────────────────
# Alle verfügbaren Agenten (30 Spezialisten)
# ──────────────────────────────────────────────────────────

# Realer Fund (Team-Retrospektive 2026-09-06): die Liste "Verfügbare Agenten-IDs" im
# DECOMPOSE_SYSTEM_PROMPT unten war bisher ein von Hand gepflegter, zweiter, vom `agents_
# description`-Aufbau in decompose() komplett UNABHÄNGIGER String - beim Live-Abgleich hatte
# sie bereits real gedriftet: `agent_trainer` stand dort als wählbare ID, obwohl er (wie
# `retrospective`) bewusst aus der Beschreibungsliste ausgeschlossen ist und deshalb nie eine
# Erklärung bekam, WANN man ihn einsetzt - das Modell hätte ihn blind wählen können. Jede neue
# Agentenrolle hätte bisher ZWEI unabhängige Stellen erfordert (hier UND diesen String), ohne
# dass ein Vergessen der zweiten je auffiele. `_DECOMPOSE_EXCLUDED_AGENT_IDS` ist jetzt die
# EINE Stelle, die beide Listen (Beschreibung unten in decompose() UND die ID-Liste im
# System-Prompt) gemeinsam speist.
_DECOMPOSE_EXCLUDED_AGENT_IDS = ("retrospective", "agent_trainer")

# Team-Optimierung (KI-Team-Masterplan, Stufe 3): Nischen-Rollen werden nur dann im
# Zerlegungs-Prompt angeboten, wenn die Anfrage inhaltlich zu ihnen passt.
#
# Realer Fund über die letzten 30 Läufe: `mobile` wurde 0-mal aufgerufen, `i18n`, `finops` und
# `team_lead` je 1-mal, `prompt_engineer` 2-mal, `web_research` und `copywriter` je 3-mal. Diese
# Rollen stehen trotzdem mit Name UND Beschreibung in JEDEM Zerlegungs-Prompt - bei jedem Lauf
# aufs Neue. Das kostet nicht nur Tokens (das Prompt-zu-Completion-Verhältnis lag bei 25:1),
# sondern verwässert auch die Auswahl: Je länger die Liste, desto eher greift das Modell zu einer
# unpassenden Spezialrolle.
#
# Bewusst NICHT gelöscht: Die Rollen bleiben vollwertig und werden eingeblendet, sobald die
# Anfrage ein passendes Stichwort enthält oder die Rolle ausdrücklich benennt. Ein Projekt, das
# wirklich Mehrsprachigkeit braucht, bekommt weiterhin den i18n-Agenten.
_NICHE_AGENT_TRIGGERS: dict[str, tuple[str, ...]] = {
    "mobile": (
        "mobile", "android", "ios", "app-store", "react native", "flutter",
        "smartphone", "cordova", "capacitor", "pwa", "hybrid-app", "ionic",
        "mobile app", "mobil-app", "app-entwicklung",
    ),
    "i18n": ("i18n", "mehrsprach", "übersetz", "ubersetz", "lokalisier", "internationalisier", "sprachen"),
    "finops": ("finops", "kosten", "budget", "hosting", "cloud-kosten", "preis", "abrechnung"),
    "prompt_engineer": ("prompt", "llm", "ki-modell", "sprachmodell", "rag", "embedding", "agent"),
    "copywriter": ("copy", "marketing", "werbe", "landing", "slogan", "texte", "content"),
    "web_research": ("recherch", "research", "vergleich", "marktanalyse", "wettbewerb", "aktuelle"),
    "ml": ("machine learning", "ml-", "modelltraining", "neuronale", "klassifikation", "vorhersage", "ki-modell"),
    "data_engineer": ("etl", "datenpipeline", "data warehouse", "datenstrom", "ingest", "airflow"),
    "image_generator": ("bild", "grafik", "logo", "illustration", "icon"),
    # Team-Verschlankung (Analyse 2026-09-15): `team_lead` überschneidet sich mit planning_lead +
    # product_owner und wurde kaum gewählt; `performance` lag bei 67% Erfolgsquote und war laut
    # Optimization-Advisor über 100 Läufe ungenutzt. Beide nur noch bei fachlichem Bedarf.
    "team_lead": ("teamleiter", "engineering manager", "roadmap", "priorisier", "trade-off", "meilenstein"),
    "performance": (
        "performance", "last", "skalier", "latenz", "durchsatz", "hochverfügbar", "rate-limit",
        "rate limit", "gateway", "benchmark", "concurrent", "gleichzeitig",
    ),
}


# ──────────────────────────────────────────────────────────
# Meta-Prompt-Schutzfilter
# ──────────────────────────────────────────────────────────
# Realer Fund (Nutzeranfrage, KI-Team-Härtungsrunde 2026-09-11): Nutzer fügen gelegentlich
# versehentlich einen Framework-Verbesserungs-Auftrag ("Du bist Lead-Entwickler für das
# Framework ...") statt eines echten Software-Projektauftrags in die CLI ein - eine
# Verwechslung, die naheliegt, weil beide Auftragsarten über dieselbe Eingabeaufforderung
# laufen. Ohne Filter versucht das Team, aus reinen Framework-Instruktionen (die auf CODE
# in `core/`/`agents/` abzielen, nicht auf ein neues Projekt in `workspace/`) krampfhaft ein
# Softwareprojekt zu bauen - vollständig sinnlos verbrauchte Agenten-Läufe. Die Erkennung
# prüft bewusst nur den ANFANG der Eingabe (nicht irgendwo mittendrin, sonst würden auch
# legitime Projektaufträge über "KI-Team"/"Framework-Verbesserung" fälschlich blockiert) und
# bleibt eine reine Textmustererkennung ohne LLM-Aufruf - ein Meta-Prompt darf nicht erst
# Tokens kosten, um als solcher erkannt zu werden.
_META_PROMPT_PREFIX_MARKERS: tuple[str, ...] = (
    "du bist lead-entwickler für das framework",
    "du bist lead-architekt für das framework",
    "du bist der lead-entwickler für das framework",
    "analysiere die arbeit von meinem ki-team",
    "analysiere die arbeit meines ki-teams",
    "schreibe mir einen prompt für claude",
    "implementiere folgende optimierungen am framework",
    "implementiere folgende optimierungen ausschließlich im framework-code",
)


def is_framework_meta_prompt(user_request: str) -> bool:
    """
    True, wenn `user_request` mit einer typischen Framework-Meta-Anweisung BEGINNT statt
    einen echten Software-Projektauftrag zu beschreiben (siehe Modul-Kommentar oben).

    Bewusst ein reiner Präfix-Check auf die ersten ~200 Zeichen (kleingeschrieben, Whitespace
    normalisiert) - ein Meta-Auftrag benennt sich fast immer gleich im ersten Satz selbst
    ("Du bist Lead-Entwickler für das Framework ..."), ein Treffer irgendwo mitten im Text
    wäre dagegen zu unspezifisch und würde legitime Projektaufträge blockieren, die das
    Framework nur beiläufig erwähnen.
    """
    normalized = " ".join((user_request or "").strip().lower().split())[:200]
    return any(normalized.startswith(marker) for marker in _META_PROMPT_PREFIX_MARKERS)


META_PROMPT_WARNING = (
    "⚠️ Hinweis: Diese Eingabe ist ein Meta-Auftrag zur Verbesserung des Frameworks und kein "
    "Software-Projekt. Bitte führe solche Prompts direkt im Claude-Code-Terminal aus."
)


def _relevant_agent_ids(user_request: str, enable_filter: bool = True) -> set[str]:
    """
    IDs der Nischen-Rollen, die für DIESE Anfrage NICHT angeboten werden sollen.

    Eine Rolle bleibt im Prompt, wenn die Anfrage eines ihrer Stichworte enthält ODER ihre ID
    ausdrücklich nennt (damit "nutze den i18n-Agenten" immer funktioniert). `enable_filter=False`
    schaltet die Filterung komplett ab - dann verhält sich die Zerlegung exakt wie zuvor.
    """
    if not enable_filter:
        return set()
    text = (user_request or "").lower()
    return {
        agent_id
        for agent_id, triggers in _NICHE_AGENT_TRIGGERS.items()
        if agent_id not in text and not any(trigger in text for trigger in triggers)
    }

AVAILABLE_AGENTS = {
    # ── Phase 1: Führung, Planung & Recherche ─────────────
    "team_lead": {
        "name": "Teamleiter (Engineering Manager)",
        "phase": 1,
        "description": "Definiert Projektziele, DoD, Trade-Off-Entscheidungen und steuert den Team-Fokus.",
    },
    "product_owner": {
        "name": "Product Owner",
        "phase": 1,
        "description": "Definiert Produktvision, MVP-Scope (MoSCoW), Release-Roadmap und User Journeys.",
    },
    "business_analyst": {
        "name": "Business Analyst",
        "phase": 1,
        "description": "Analysiert Anforderungen, erstellt User Stories und Akzeptanzkriterien (Given/When/Then).",
    },
    "web_research": {
        "name": "Web-Recherche Specialist",
        "phase": 1,
        # Realer Fund (Analyse 2026-09-06): web_research wurde in 200 Laeufen NIE gewaehlt.
        # Ursache: die Beschreibung war zu abstrakt - wann genau einsetzen? Jetzt konkrete
        # Trigger: neuer Tech-Stack (unbekannte Versionen), viele Abhaengigkeiten (CDN/NPM),
        # oder wenn aktuelle Docs wichtig sind (Breaking Changes, neue API). Via Tavily-
        # Live-Search liefert dieser Agent echte, aktuelle Package-Versionen statt veraltetes
        # LLM-Wissen - besonders wertvoll bei Python-Paketen, die sich haeufig aendern.
        "description": (
            "Recherchiert via Tavily Live-Search aktuelle Package-Versionen, Breaking Changes "
            "und CDN-Links. Einsetzen bei: (1) neuem Tech-Stack mit unbekannten Versionen, "
            "(2) Abhaengigkeiten die sich haeufig aendern (FastAPI, Next.js, React, Pydantic), "
            "(3) wenn aktuelle Dokumentation wichtiger ist als LLM-Wissensbasis. "
            "Liefert verifizierte requirements.txt-Versionen statt veralteter Defaults."
        ),
    },

    # ── Phase 2: Architektur & FinOps ─────────────────────
    "architect": {
        "name": "Software-Architekt",
        "phase": 2,
        "description": "Entwirft Systemarchitektur, API-Contracts, Komponenten-Blueprints und ADRs.",
    },
    "finops": {
        "name": "Cost & FinOps Engineer",
        "phase": 2,
        # Realer Fund (Analyse 2026-09-06): finops wurde in 200 Laeufen NIE gewaehlt.
        # Einsetzen wenn externe APIs, Cloud-Hosting oder AI-Modell-Aufrufe im Spiel sind -
        # typischer Fall: ein Nutzer baut einen SaaS-Service und weiss nicht, ob Hetzner-VM,
        # Railway oder Fly.io guenstiger ist, oder ob er lieber serverless (Vercel) geht.
        "description": (
            "Kalkuliert Cloud-Kosten (AWS/GCP/Hetzner/Railway/Fly.io), TCO, Serverless vs. "
            "VM-Hosting und AI-Token-Budgets. Einsetzen bei: (1) Projekten mit externen "
            "API-Aufrufen (OpenAI, Stripe, SendGrid), (2) wenn Hosting-Entscheidung offen ist, "
            "(3) SaaS-Produkte mit vielen Nutzern. Liefert konkrete Kostenvergleiche."
        ),
    },

    # ── Phase 2: Vorab-Design, UI/UX & Media ──────────────
    "ui_ux": {
        "name": "UI/UX Designer",
        "phase": 2,
        "description": "Wireframes, Design-Systeme, Farbpaletten und Design-Tokens.",
    },
    "image_generator": {
        "name": "Bild- & Grafik-Designer",
        "phase": 2,
        # Team-Optimierung (Fortsetzung der Analyse 2026-09-06, unused_agent-Fund): war seit
        # mind. 100 Laeufen nie gewaehlt - dieselbe Ursache wie bei accessibility/finops/
        # web_research/performance: die Beschreibung nannte NUR die Faehigkeit, nicht WANN sie
        # gebraucht wird. Jetzt konkrete Trigger statt "erstellt SVG-Grafiken" als reine
        # Tätigkeitsbeschreibung.
        "description": (
            "Erstellt SVG-Logos, Icons und optimierte Bild-Prompts (Imagen 3/Midjourney) für "
            "Hero-Bilder und Banner. Einsetzen bei: (1) Landingpages/Marketing-Seiten ohne "
            "eigenes Branding, (2) UI mit Icon-Bedarf statt reinem Text, (3) explizitem "
            "Logo-/Grafik-Wunsch. NICHT bei reinen Backend-/CLI-/API-Projekten ohne UI."
        ),
    },
    "copywriter": {
        "name": "Copywriter & Content Specialist",
        "phase": 2,
        # Team-Optimierung (Fortsetzung der Analyse 2026-09-06, unused_agent-Fund): siehe
        # image_generator oben - gleiche Ursache, gleicher Fix.
        "description": (
            "Schreibt Landingpage-Prosa, UI-Microcopy (Button-Labels, Fehlermeldungen, "
            "Leerzustände) und SEO-Texte/FAQs. Einsetzen bei: (1) öffentlich sichtbaren "
            "Seiten, die echten Fließtext statt Lorem-Ipsum/technischer Labels brauchen, "
            "(2) Marketing-/Landingpages, (3) FAQ- oder Hilfe-Inhalten. NICHT bei internen "
            "Tools/APIs ohne Endnutzer-Text."
        ),
    },

    # ── Phase 3: Kern-Entwicklung ─────────────────────────
    "frontend": {
        "name": "Frontend-Entwickler",
        "phase": 3,
        "description": "Implementiert React, Vue, Next.js, HTML/CSS und interaktive Web-UIs.",
    },
    "backend": {
        "name": "Backend-Entwickler",
        "phase": 3,
        "description": "Entwickelt REST/FastAPI/Node Server-Logik, Authentifizierung und APIs.",
    },
    "database": {
        "name": "Datenbank-Entwickler",
        "phase": 3,
        "description": "Entwirft SQL/NoSQL Datenmodelle, ORM-Schemas, Indizes und Migrationen.",
    },
    "api_integration": {
        "name": "API & Integration Specialist",
        "phase": 3,
        "description": "OpenAPI 3.1 Specs, GraphQL, Webhooks mit HMAC-Sicherheit, Stripe, OAuth2.",
    },
    "data_engineer": {
        "name": "Data Engineer",
        "phase": 3,
        # Team-Optimierung (Fortsetzung der Analyse 2026-09-06, unused_agent-Fund): siehe
        # image_generator/copywriter oben - Abgrenzung zu 'backend' (reine CRUD-API) und
        # 'database' (Schema/Migrationen) war bisher nicht explizit, der Planer griff bei
        # Datenverarbeitung offenbar reflexhaft zu 'backend'.
        "description": (
            "Event-Streaming (Kafka/RabbitMQ), Redis-Caching-Layer und ETL-/Batch-Pipelines "
            "mit mehreren Datenquellen. Einsetzen bei: (1) Message-Queues/Event-Bus statt "
            "reinem Request-Response, (2) Caching-Layer für teure Berechnungen/Anfragen, "
            "(3) Datenverarbeitung über mehrere Schritte/Quellen hinweg. Abgrenzung: einzelne "
            "CRUD-Endpunkte macht 'backend', Schema/Migrationen macht 'database'."
        ),
    },
    "mobile": {
        "name": "Mobile- & App-Entwickler",
        "phase": 3,
        # Team-Optimierung: Mobile-Agent deckt Cross-Platform, Hybrid (Cordova/Capacitor/PWA)
        # und natives iOS/Android ab. Wird bei allen mobilen Applikationen und Device-APIs gewählt.
        "description": (
            "Spezialist für mobile Apps: Cross-Platform (React Native, Flutter), Hybrid-Apps "
            "(Capacitor, Apache Cordova, Ionic) und Progressive Web Apps (PWA) sowie natives "
            "iOS (Swift) und Android (Kotlin). Einsetzen bei: (1) Smartphone-/Tablet-Apps jeglicher "
            "Art, (2) Hybrid- & Web-to-App-Projekten (Cordova/Capacitor/PWA/config.xml), "
            "(3) Offline-First-Speicherung, Barcode-/Kamera-Scanning oder nativen Geräte-APIs. "
            "Arbeitet bei Web-basierten Hybrid-Apps Hand-in-Hand mit 'frontend'."
        ),
    },
    "ml": {
        "name": "KI/ML-Entwickler",
        "phase": 3,
        # Team-Optimierung (Fortsetzung der Analyse 2026-09-06, unused_agent-Fund): Abgrenzung
        # zu 'prompt_engineer' fehlte bisher (beide klangen wie derselbe Themenbereich) - macht
        # es dem Planer schwer, den passenderen der beiden zu wählen.
        "description": (
            "Baut RAG-Pipelines, Embeddings/Vector-Stores und klassische ML-Modelle "
            "(Klassifikation/Regression). Einsetzen bei: (1) Retrieval-Augmented Generation "
            "über eigene Dokumente/Daten, (2) Vektor-Suche/Ähnlichkeitssuche, (3) eigenem "
            "trainiertem/statistischem Modell. Abgrenzung zu 'prompt_engineer': dieser baut "
            "keine eigene Pipeline, sondern gestaltet nur Prompts/Guardrails für LLM-Aufrufe."
        ),
    },
    "prompt_engineer": {
        "name": "Prompt Engineer & AI Architect",
        "phase": 3,
        # Team-Optimierung (Fortsetzung der Analyse 2026-09-06, unused_agent-Fund): siehe ml
        # oben - gleiche Abgrenzung, umgekehrte Richtung.
        "description": (
            "Entwirft System-Prompts, Few-Shot-Vorlagen und Guardrails FÜR die generierte "
            "APP (nicht für das KI-Team selbst). Einsetzen bei: (1) die App macht selbst "
            "LLM-Aufrufe (Chatbot, AI-Feature, Content-Generierung), (2) Schutz gegen Prompt-"
            "Injection bei nutzergesteuerten Eingaben nötig ist. Abgrenzung zu 'ml': baut "
            "selbst keine RAG-/Embedding-Pipeline, nur die Prompt-/Guardrail-Schicht darum."
        ),
    },
    "performance": {
        "name": "Performance-Ingenieur",
        "phase": 3,
        # Realer Fund (Analyse 2026-09-06): performance wurde in 200 Laeufen NIE gewaehlt.
        # Einsetzen immer wenn eine REST-API mit mehr als 3 Endpunkten entsteht - generierte
        # APIs werden nie auf echte Last getestet und brechen unter Echtzeitbedingungen zusammen.
        # Locust/k6-Lasttests sind das Aequivalent von pytest fuer APIs - ohne sie ist
        # "fertig" nur Code-Review, kein echter Qualitaetsnachweis.
        "description": (
            "Schreibt Locust- oder k6-Lasttests und analysiert Bottlenecks. Einsetzen bei: "
            "(1) REST-APIs mit mehr als 3 Endpunkten, (2) Services mit Datenbankanbindung, "
            "(3) wenn Antwortzeiten oder gleichzeitige Nutzer relevant sind. "
            "Liefert tests/load/locustfile.py mit Szenarien fuer 50-100 gleichzeitige Nutzer."
        ),
    },

    # ── Phase 4: Content, Doku & Barrierefreiheit ─────────
    "accessibility": {
        "name": "Accessibility & a11y Specialist",
        "phase": 4,
        # Realer Fund (Analyse 2026-09-06): accessibility wurde in 200 Laeufen NIE gewaehlt.
        # Ursache: die Beschreibung klang wie ein Audit-Service, nicht wie ein Entwickler-
        # Partner. Tatsaechlich pruefte dieser Agent bisher generierte HTML-Templates auf
        # WCAG 2.2 und ergaenzte ARIA-Attribute - das ist bei JEDEM Frontend-Projekt
        # sinnvoll, nicht nur bei explizitem Barrierefreiheits-Auftrag.
        "description": (
            "Prueft alle HTML-Templates auf WCAG 2.2 AA und ergaenzt ARIA-Attribute, "
            "Tastaturnavigation und Screenreader-Labels. Einsetzen bei: JEDEM Projekt mit "
            "HTML-Dateien oder React/Vue-Templates. Besonders wichtig bei: Login-Formulare, "
            "Buttons, Tabellen, Modals und dynamischen Inhalten."
        ),
    },
    "i18n": {
        "name": "Internationalisierungs-Spezialist",
        "phase": 4,
        # Team-Optimierung (Fortsetzung der Analyse 2026-09-06, unused_agent-Fund): dieselbe
        # Ursache wie bei accessibility (siehe dort) - "Mehrsprachigkeit" klingt nach einem
        # optionalen Zusatz statt einem Trigger, wann er gebraucht wird.
        "description": (
            "Mehrsprachigkeit (i18n/l10n), RTL-Unterstützung und locale-abhängige Formate "
            "(Datum, Währung, Zahlen). Einsetzen bei: (1) explizitem Mehrsprachigkeits-Wunsch, "
            "(2) öffentlich/global adressierten Produkten (SaaS, Landingpage) auch ohne "
            "expliziten Wunsch, (3) RTL-Sprachen (Arabisch/Hebräisch) im Zielmarkt."
        ),
    },
    "documentation": {
        "name": "Dokumentant",
        "phase": 4,
        "description": "API-Dokumentation, Inline-Kommentare und Architekturguides.",
    },
    "readme": {
        "name": "README & Tech-Writer",
        "phase": 4,
        "description": "Erstellt professionelle README.md, Quickstart-Guides und Projektübersichten.",
    },

    # ── Phase 5: Infrastruktur & Qualität ─────────────────
    "devops": {
        "name": "DevOps-Ingenieur",
        "phase": 5,
        "description": "Dockerfile, docker-compose, CI/CD GitHub Actions Pipelines, K8s.",
    },
    "tester": {
        "name": "QA-Tester",
        "phase": 5,
        "description": "Unit-Tests (pytest), Integrationstests und E2E-Testpläne.",
    },
    "security": {
        "name": "Sicherheits-Analyst",
        "phase": 5,
        "description": "OWASP Top 10, Auth-Audits, Input-Sanitization, Security-Headers.",
    },
    "resilience_guard": {
        "name": "Resilience-Guard (QA & Fault-Tolerance)",
        "phase": 5,
        "description": "Circuit Breaker, Retries mit Backoff/Jitter, Ausfalltoleranz, Graceful Degradation & Chaos Tests.",
    },

    # ── Phase 6: Review, Refactoring, Compliance & Hygiene ─
    "code_reviewer": {
        "name": "Code-Reviewer",
        "phase": 6,
        "description": "Qualitätskontrolle, Konsistenzprüfung, Code-Scoring und Bug-Detektion.",
    },
    "refactoring": {
        "name": "Refactoring Specialist",
        "phase": 6,
        "description": "Beseitigt Code Smells, refaktoriert Module und sichert strikte Typsicherheit.",
    },
    "compliance": {
        "name": "Legal & Compliance Specialist",
        "phase": 6,
        "description": "DSGVO/GDPR-Audits, Lizenzprüfung (GPL vs MIT), WCAG 2.1 Barrierefreiheit.",
    },
    "project_cleaner": {
        "name": "Projekt-Hygiene & Struktur-Wächter",
        "phase": 6,
        "description": "Bereinigt alte/tote Dateien, verhindert Projekt-Bloat und optimiert Ordnerstrukturen.",
    },

    # ── Phase 6: Ausbildung, Retrospektive & Evolution ─────
    "agent_trainer": {
        "name": "Ausbilder & Agent-Optimizer",
        "phase": 6,
        "description": "Optimiert System-Prompts, analysiert Fehler der Agenten und bildet neue Rollen aus.",
    },
    "retrospective": {
        "name": "Retrospektive & Lessons Learned Agent",
        "phase": 6,
        "description": "Erstellt die Abschluss-Retrospektive (Was lief gut/schlecht, Lessons Learned).",
    },
    "github": {
        "name": "GitHub-Agent",
        "phase": 5,
        "description": "Generiert Commit-Messages und führt automatische Git-Pushes durch.",
    },
}

# Realer Fund aus einem echten End-to-End-Testlauf: diese Agenten werden laut den
# DECOMPOSE_SYSTEM_PROMPT-Regeln unten NUR bei echter Komplexität eingeplant (architect/
# security/compliance sind dort explizit "NICHT optional, sobald..."-Fälle, die übrigen
# signalisieren von sich aus einen größeren Aufgabenzuschnitt) - taucht auch nur EINER davon
# im Plan auf, ist die Aufgabe per Definition NICHT trivial.
_COMPLEXITY_SIGNAL_AGENT_IDS = {
    "architect", "security", "compliance", "finops", "performance",
    "data_engineer", "ml", "mobile", "product_owner", "business_analyst", "web_research",
}

# Ab dieser Gesamtzahl an eingeplanten Spezialisten gilt eine Aufgabe nicht mehr als "klein"
# genug, um die Teamleiter-Koordination zu überspringen - selbst wenn kein einzelner Agent
# ein Komplexitäts-Signal ist, deutet eine breite Aufgabenverteilung auf echten
# Abstimmungsbedarf hin.
_MICRO_TASK_MAX_AGENTS = 4


def is_micro_task(agent_tasks: list["AgentTask"]) -> bool:
    """
    Rein deterministische Klassifikation aus dem BEREITS erstellten Aufgabenplan - KEIN
    zusätzlicher LLM-Aufruf, keine neue Schätzung. Nutzt genau die Agenten-Auswahl, die
    decompose() (siehe DECOMPOSE_SYSTEM_PROMPT unten) ohnehin schon für die Zwecke von
    "welche Spezialisten sind wirklich nötig" trifft, nur ein zweites Mal ausgewertet für
    "wie viel Teamleiter-Koordination braucht dieser Plan wirklich".
    """
    if len(agent_tasks) > _MICRO_TASK_MAX_AGENTS:
        return False
    return not any(t.agent_id in _COMPLEXITY_SIGNAL_AGENT_IDS for t in agent_tasks)


DECOMPOSE_SYSTEM_PROMPT = """Du bist ein erfahrener Principal Software-Architekt und Engineering Lead.
Analysiere die Aufgabe und wähle NUR die wirklich notwendigen Spezialisten aus, um maximale Token-Effizienz zu gewährleisten.

Antworte NUR mit einem gültigen JSON-Objekt. Keine Erklärungen davor oder danach.

Das JSON-Format ist exakt wie folgt:
{
  "needs_clarification": false,
  "clarifying_questions": [],
  "task_summary": "3-8 Wörter, technischer Imperativ im Perfekt (z.B. 'FastAPI Health-Check-Endpoint implementiert', 'Taschenrechner-GUI mit Core/GUI-Trennung erstellt'). NIEMALS die Nutzeranfrage wörtlich wiederholen, zitieren oder paraphrasieren, auch nicht in Teilen - beschreibe WAS entstehen wird, nicht WAS der Nutzer geschrieben hat. Dieser Text erscheint u.a. als Git-Commit-Message.",
  "project_slug": "kurzer_projekt_ordnername_ohne_sonderzeichen",
  "required_agents": [
    {
      "agent_id": "<agent_id aus der Liste>",
      "task": "Präzise, token-effiziente Aufgabenbeschreibung für diesen Agenten"
    }
  ]
}

Rückfrage statt Raten (wie ein erfahrener Senior-Entwickler): Setze "needs_clarification"
auf true und liste 1-3 knappe, konkrete Fragen in "clarifying_questions" (required_agents
dann leer), wenn die Aufgabe SO unklar ist, dass unterschiedliche vertretbare Interpretationen
zu grundverschieden Ergebnissen führen würden, oder eine für die Umsetzung ZWINGENDE Angabe
komplett fehlt (z.B. welches Zielsystem, welche Datenquelle, welcher Kernzweck der Anwendung).
NICHT für gewöhnliche Unterspezifikation nutzen, die ein erfahrener Entwickler sinnvoll selbst
entscheiden würde (z.B. Styling-Details, exakte Bibliotheksversion) - im Zweifel lieber eine
vernünftige Annahme treffen und im task_summary kurz erwähnen, statt nachzufragen.

Verfügbare Agenten-IDs:
__AVAILABLE_AGENT_IDS__

Wichtige Regeln:
- Wähle NUR die zwingend erforderlichen Agenten aus (Token-Sparsamkeit)
- Halte die Aufgabenbeschreibungen klar und fokussiert
- Plane INKREMENTELL wie ein echtes Team: die Aufgabe von backend/frontend beginnt mit einem
  lauffähigen Kern (Einstiegspunkt + ein vollständiger End-to-End-Pfad inkl. Test), erst danach
  folgen weitere Features. Nenne in der backend-Aufgabe ausdrücklich, welcher Pfad zuerst
  lauffähig sein muss - ein Budget-Abbruch soll immer einen startbaren Stand hinterlassen
- Die tester-Aufgabe beschreibt die zu prüfenden Akzeptanzkriterien (Verhalten laut Auftrag und
  interface_contract.json), damit die Tests parallel zur Implementierung entstehen können
- code_reviewer bei Code-Generierung einschließen
- tester einbeziehen, wenn echte Programmlogik entsteht (Funktionen/Klassen mit Verhalten,
  nicht nur Konfiguration/Text) - ausgelieferter Code ohne jeden Test ist nicht Ziel dieses Teams
- security einbeziehen, sobald Authentifizierung/Autorisierung, Nutzer-/Personendaten,
  Zahlungsdaten, Datei-Uploads oder ein nach außen erreichbarer Netzwerk-Endpunkt entstehen -
  das ist NICHT optional, sondern genauso verpflichtend wie code_reviewer bei Code-Generierung
- compliance einbeziehen, sobald personenbezogene Daten (DSGVO-Relevanz), neue
  Drittanbieter-Abhängigkeiten mit unklarer/restriktiver Lizenz oder regulierte Bereiche
  (z.B. Finanzen, Gesundheit) betroffen sind - ebenfalls NICHT optional
- architect einbeziehen, sobald eine echte Technologie-/Architektur-Entscheidung mit
  mehreren vertretbaren Alternativen zu treffen ist (z.B. Wahl der Datenpersistenz,
  Monolith vs. Microservices, REST vs. GraphQL, Wahl des Datenbanksystems, Auth-Strategie) -
  NICHT optional, auch wenn die Aufgabe sonst klein wirkt; ohne echte Alternative (z.B. reine
  Konfigurationsänderung, triviale Erweiterung um einen weiteren Endpunkt nach bereits
  etabliertem Muster) bleibt architect dagegen weiterhin weggelassen
- project_cleaner einbeziehen, wenn Verzeichnisstrukturen aufgeräumt oder schlank gehalten werden sollen
- Wenn die Aufgabe ein bestehendes Projekt (oder einen Pfad wie 'workspace/<name>') nennt oder referenziert,
  nutze EXAKT diesen bestehenden 'project_slug'. Erfinde NIEMALS abgeleitete Slugs wie '<name>_repair',
  '<name>_fix' oder '<name>_patch'.
- web_research einbeziehen, wenn ein neuer Tech-Stack gewählt wird (unbekannte Package-Versionen),
  Abhängigkeiten sich häufig ändern (FastAPI, Pydantic, Next.js, React) oder aktuelle Docs wichtiger
  sind als das LLM-Wissen - liefert verifizierte requirements.txt-Versionen via Tavily Live-Search
- performance (falls in der Liste angeboten) einbeziehen, wenn der Auftrag ausdrücklich Last,
  Skalierung, Latenz oder Rate-Limiting verlangt - Locust/k6-Lasttests sind dann Qualitätsnachweis
- accessibility einbeziehen, sobald HTML-Dateien oder React/Vue-Komponenten entstehen - WCAG 2.2
  ARIA-Attribute und Tastaturnavigation gehören genauso zur Fertigstellung wie Tests
- finops einbeziehen, wenn externe APIs (OpenAI, Stripe, SendGrid) genutzt werden, die Hosting-
  Wahl offen ist oder ein SaaS-Produkt für viele Nutzer entstehen soll
- data_engineer einbeziehen, sobald Message-Queues (Kafka, RabbitMQ), Event-Streaming, Redis-Caching-Layer
  oder Multi-Source ETL-Pipelines entstehen (Abgrenzung: einfache CRUD-APIs macht backend)
- mobile einbeziehen, sobald eine App für iOS, Android, Flutter oder React Native gewünscht ist oder
  native Device-APIs/Offline-Fähigkeit gefordert sind (Abgrenzung: responsive Websites macht frontend)
- ml einbeziehen, sobald RAG-Pipelines, Vector-Embeddings, Ähnlichkeitssuche oder klassische ML-Modelle
  (Klassifikation, Regression) entstehen
- prompt_engineer einbeziehen, sobald die zu bauende App selbst LLM-Aufrufe/Chatbots anbietet und
  spezifische System-Prompts oder Schutz gegen Prompt-Injection benötigt
- copywriter einbeziehen, sobald öffentliche Seiten/Landingpages echten Fließtext, UI-Microcopy
  oder FAQ-Inhalte benötigen (verhindert unprofessionelles Lorem-Ipsum)
- image_generator einbeziehen, sobald Icons, SVG-Logos oder Banner für UIs/Landingpages benötigt werden
- i18n einbeziehen, sobald Mehrsprachigkeit, Lokalisierung oder RTL-Unterstützung relevant sind
- Berücksichtige die bekannten Team-Lektionen. Plane bei Projekten mit APIs oder Web-UIs
  zwingend den Haupteinstiegspunkt (main.py bzw. main.ts/index.html) explizit als Teilaufgabe
  für den zuständigen Entwickler ein, um "missing_entrypoint"-Blocker zu vermeiden.
"""


class TaskManager:
    """Analysiert und zerlegt Nutzeraufgaben in parallelisierbare Teilaufgaben."""

    def __init__(self, model_name: str = "gemini-3.8-flash"):
        self._llm = LLMFactory.create_for_model(model_name)

    async def decompose(
        self,
        user_request: str,
        conversation_context: str | None = None,
        existing_projects: list[str] | None = None,
    ) -> tuple[str, str, list[AgentTask]]:
        # Dauerhaft ausgeschlossene Rollen PLUS die Nischen-Rollen, die zu dieser konkreten
        # Anfrage nicht passen (siehe _NICHE_AGENT_TRIGGERS oben). Beide Listen unten werden aus
        # DERSELBEN Menge gespeist, damit Beschreibung und ID-Liste nie auseinanderdriften.
        ausgeschlossen = set(_DECOMPOSE_EXCLUDED_AGENT_IDS) | _relevant_agent_ids(
            user_request, enable_filter=ENABLE_NICHE_AGENT_FILTER,
        )
        agents_description = "\n".join([
            f"- {agent_id} [Phase {info['phase']}]: {info['description']}"
            for agent_id, info in AVAILABLE_AGENTS.items()
            if agent_id not in ausgeschlossen
        ])
        available_agent_ids = ", ".join(
            agent_id for agent_id in AVAILABLE_AGENTS if agent_id not in ausgeschlossen
        )
        decompose_system_prompt = DECOMPOSE_SYSTEM_PROMPT.replace(
            "__AVAILABLE_AGENT_IDS__", available_agent_ids,
        )

        context_section = ""
        if conversation_context:
            context_section = f"\n\nVorheriger Kontext (gekürzt):\n{conversation_context[:1000]}"

        existing_projects_section = ""
        if existing_projects:
            existing_projects_section = (
                "\n\nBEREITS EXISTIERENDE PROJEKTE IM WORKSPACE:\n"
                + ", ".join(sorted(existing_projects))
                + "\nWICHTIG: Bezieht sich die Nutzeranfrage auf eines dieser Projekte, verwende EXAKT dessen "
                "bestehenden 'project_slug' (kein Suffix wie '_repair' oder '_fix')!"
            )

        # Selbstlernen in der Planungsphase (Fehleranalyse 2026-09-13): bisher kannten nur die
        # einzelnen Entwickler-Agenten (agents/orchestrator/__init__.py.team_lessons_context)
        # vergangene Team-Lektionen, der Planer selbst zerlegte Aufgaben ohne dieses Wissen -
        # ein wiederkehrender Blocker wie "missing_entrypoint" wurde so nie schon in der
        # Zerlegung als eigene Teilaufgabe vorgesehen, sondern erst nachträglich von einem
        # einzelnen Agenten (falls überhaupt) bemerkt.
        team_lessons_section = ""
        team_lessons_text = format_team_lessons_for_agents(limit=5)
        if team_lessons_text:
            team_lessons_section = (
                "\n\nBEKANNTE TEAM-LEKTIONEN AUS FRÜHEREN FEHLERN:\n" + team_lessons_text
            )

        prompt = f"""Analysiere folgende Nutzeranfrage und erstelle einen effizienten Aufgabenplan:

NUTZERANFRAGE:
{user_request}
{context_section}
{existing_projects_section}
{team_lessons_section}

VERFÜGBARE AGENTEN:
{agents_description}

Erstelle jetzt das JSON mit den Teilaufgaben."""

        try:
            raw_json = await self._llm.generate_json(prompt, decompose_system_prompt)
        except Exception as e:
            # Wie in ResultAggregator.synthesize(): nicht crashen, sondern einen klaren,
            # nutzerverständlichen Grund liefern statt eines rohen Stacktraces. Orchestrator.
            # process() behandelt eine leere agent_tasks-Liste bereits als regulären Fall.
            return f"⚠️ Aufgabenanalyse fehlgeschlagen (alle konfigurierten Modelle/Provider aktuell nicht erreichbar: {e})", "project", []

        plan = self._parse_plan(raw_json)

        # Rückfrage statt Raten: wie ein erfahrener Senior-Entwickler nachfragen, statt bei
        # einer grundlegend unklaren Anfrage einfach die naheliegendste Interpretation zu
        # bauen (real beobachtet: vage Prompts wie "Ich möchte, dass ihr das Projekt weiter
        # verbessert" führten zu frei erfundenen, thematisch beliebigen Demo-Projekten statt
        # einer Rückfrage). agent_tasks bleibt bewusst leer - dieselbe, bereits vorhandene
        # Behandlung wie bei einem Provider-Totalausfall (siehe Orchestrator.process()),
        # nur mit "❓" statt "⚠️" als Präfix, damit der Aufrufer zwischen "echter Fehler"
        # und "brauche eine Antwort vom Menschen" unterscheiden kann.
        if plan.get("needs_clarification") and plan.get("clarifying_questions"):
            questions = "\n".join(f"{i}. {q}" for i, q in enumerate(plan["clarifying_questions"], 1))
            return (
                f"❓ Bevor ich das Team loslasse, brauche ich noch eine Präzisierung:\n\n{questions}",
                "project", [],
            )

        task_summary = plan.get("task_summary", "Aufgabe wird bearbeitet...")
        project_slug = plan.get("project_slug", "project")
        required_agents = plan.get("required_agents", [])

        agent_tasks = []
        for agent_info in required_agents:
            agent_id = agent_info.get("agent_id", "")
            if agent_id not in AVAILABLE_AGENTS:
                continue

            agent_tasks.append(AgentTask(
                task_id=str(uuid.uuid4())[:8],
                agent_id=agent_id,
                description=agent_info.get("task", ""),
                context=user_request[:1500],
            ))

        return task_summary, project_slug, agent_tasks

    def _parse_plan(self, raw_json: str) -> dict:
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_json)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        return {"task_summary": "Aufgabe analysiert", "project_slug": "project", "required_agents": []}
