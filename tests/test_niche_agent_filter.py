"""
tests/test_niche_agent_filter.py – Nischen-Rollen nur bei passender Anfrage anbieten

Regressionsschutz für einen Fund der KI-Team-Masterplan-Analyse: Über die letzten 30 Läufe wurde
`mobile` 0-mal aufgerufen, `i18n`/`finops`/`team_lead` je 1-mal, `prompt_engineer` 2-mal. Alle
standen trotzdem mit Name UND Beschreibung in JEDEM Zerlegungs-Prompt – bei einem
Prompt-zu-Completion-Verhältnis von 25:1 ein spürbarer Dauerkostenfaktor, der zusätzlich die
Rollenauswahl verwässert.

Wichtig: Die Rollen dürfen NICHT verschwinden. Sie müssen erscheinen, sobald die Anfrage
inhaltlich zu ihnen passt oder sie ausdrücklich benennt.
"""

import pytest

from core.task_manager import (
    _DECOMPOSE_EXCLUDED_AGENT_IDS,
    _NICHE_AGENT_TRIGGERS,
    AVAILABLE_AGENTS,
    _relevant_agent_ids,
)


class TestAusblenden:
    def test_standard_backend_anfrage_blendet_nischen_aus(self):
        ausgeblendet = _relevant_agent_ids("Erstelle eine FastAPI Notizen-API mit SQLite und Tests.")
        assert "mobile" in ausgeblendet
        assert "i18n" in ausgeblendet
        assert "finops" in ausgeblendet

    def test_kernrollen_werden_nie_ausgeblendet(self):
        """backend/tester/architect & Co. müssen IMMER wählbar bleiben."""
        ausgeblendet = _relevant_agent_ids("Irgendeine beliebige Aufgabe.")
        for kern in ("backend", "frontend", "tester", "architect", "database", "security", "devops"):
            assert kern not in ausgeblendet

    def test_filter_laesst_sich_abschalten(self):
        assert _relevant_agent_ids("Beliebige Anfrage", enable_filter=False) == set()


class TestEinblenden:
    @pytest.mark.parametrize("anfrage,rolle", [
        ("Baue eine mehrsprachige Oberflaeche", "i18n"),
        ("Erstelle eine Android-App", "mobile"),
        ("Erstelle eine Cordova Hybrid-App mit Barcode-Scanner", "mobile"),
        ("Entwickle eine PWA mit Offline-Storage", "mobile"),
        ("Baue eine Capacitor App", "mobile"),
        ("Wie hoch sind die Hosting-Kosten?", "finops"),
        ("Schreibe Marketing-Texte fuer die Landing-Page", "copywriter"),
        ("Baue eine ETL-Datenpipeline", "data_engineer"),
        ("Recherchiere aktuelle Wettbewerber", "web_research"),
        ("Erzeuge ein Logo", "image_generator"),
    ])
    def test_passendes_stichwort_blendet_die_rolle_ein(self, anfrage, rolle):
        assert rolle not in _relevant_agent_ids(anfrage)

    @pytest.mark.parametrize("rolle", sorted(_NICHE_AGENT_TRIGGERS))
    def test_ausdrueckliche_nennung_der_rolle_wirkt_immer(self, rolle):
        """"Nutze den i18n-Agenten" muss zuverlaessig funktionieren."""
        assert rolle not in _relevant_agent_ids(f"Bitte nutze den {rolle}-Agenten fuer diese Aufgabe.")

    def test_grossschreibung_ist_egal(self):
        assert "mobile" not in _relevant_agent_ids("Baue eine ANDROID-App")


class TestKonsistenz:
    def test_alle_nischen_rollen_existieren_wirklich(self):
        """Ein Tippfehler in _NICHE_AGENT_TRIGGERS wuerde sonst still wirkungslos bleiben."""
        for rolle in _NICHE_AGENT_TRIGGERS:
            assert rolle in AVAILABLE_AGENTS, f"Unbekannte Rolle in _NICHE_AGENT_TRIGGERS: {rolle}"

    def test_dauerhaft_ausgeschlossene_rollen_sind_keine_nischenrollen(self):
        """Sonst gaebe es zwei konkurrierende Mechanismen fuer dieselbe Rolle."""
        assert not set(_NICHE_AGENT_TRIGGERS) & set(_DECOMPOSE_EXCLUDED_AGENT_IDS)

    def test_jede_nischen_rolle_hat_mindestens_einen_trigger(self):
        for rolle, trigger in _NICHE_AGENT_TRIGGERS.items():
            assert trigger, f"Rolle {rolle} hat keine Stichworte"

    def test_es_bleiben_genuegend_rollen_uebrig(self):
        """Absicherung gegen einen zu aggressiven Filter."""
        ausgeblendet = set(_DECOMPOSE_EXCLUDED_AGENT_IDS) | _relevant_agent_ids("Baue eine Web-API")
        assert len(AVAILABLE_AGENTS) - len(ausgeblendet) >= 20
