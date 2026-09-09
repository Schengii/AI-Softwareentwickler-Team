"""
tests/test_eval_runner_integrity.py – Der Benchmark muss durchfallen KÖNNEN

Regressionsschutz für den dritten Kernbefund der KI-Team-Masterplan-Analyse: In
evals/eval_history.json standen 50 Läufe – 50× bestanden, 50× `total_tokens: 0`. Ursache waren
drei Defekte in evals/runner.py:

1. `verification_ok` wurde per Substring-Match auf dem Report-TEXT bestimmt, und der geprüfte
   Marker "🧪 Verifikations-Protokoll" steht in JEDEM Bericht – auch in gescheiterten.
2. `total_tokens` wurde mit 0 initialisiert und nie zugewiesen.
3. Die Datei-Existenzprüfung lief gegen ein Verzeichnis, das zwischen Läufen nicht geleert
   wurde – Dateien eines früheren Laufs ließen einen späteren, gescheiterten Lauf bestehen.
"""

from unittest.mock import AsyncMock, patch

import pytest

from evals import runner as ev
from evals.tasks import BenchmarkTask


class _FakeOrchestrator:
    """Minimaler Orchestrator-Ersatz mit genau den Feldern, die run_single_task ausliest."""

    def __init__(self, verification_ok: bool, tokens_pro_agent: list[int], report_text: str):
        self.last_verification_ok = verification_ok
        self.last_agent_results = [type("R", (), {"total_tokens": t})() for t in tokens_pro_agent]
        self.process = AsyncMock(return_value=report_text)


# Der Bericht enthält bewusst den Marker, der zuvor jeden Lauf fälschlich als bestanden wertete.
GESCHEITERTER_BERICHT = (
    "### 🧪 Verifikations-Protokoll (echte Dependency-Installation & Testausführung)\n"
    "- 📦 ⚠️ pip install -r requirements.txt (exit_code=1)\n"
)


@pytest.fixture
def task(tmp_path):
    return BenchmarkTask(
        slug="demo", name="Demo", category="micro", prompt="Baue etwas",
        expected_project_name="demo_projekt", expected_files=["main.py"],
    )


@pytest.fixture
def workspace(tmp_path):
    """Leitet den WorkspaceManager auf ein temporäres Verzeichnis um."""
    with patch.object(ev, "WorkspaceManager", lambda: _FakeWorkspace(tmp_path)):
        yield tmp_path


class _FakeWorkspace:
    def __init__(self, base):
        self.base_dir = base

    def get_project_dir(self, name):
        return self.base_dir / name


class TestVerificationOk:
    @pytest.mark.asyncio
    async def test_gescheiterter_lauf_gilt_nicht_mehr_als_bestanden(self, task, workspace):
        """Der eigentliche Kernbefund: derselbe Bericht, der zuvor 'bestanden' ergab."""
        orch = _FakeOrchestrator(verification_ok=False, tokens_pro_agent=[100], report_text=GESCHEITERTER_BERICHT)
        res = await ev.run_single_task(task, orchestrator=orch)
        assert res.verification_ok is False

    @pytest.mark.asyncio
    async def test_bestandener_lauf_wird_korrekt_erkannt(self, task, workspace):
        # Die Datei muss WÄHREND des Laufs entstehen – ein vorab angelegter Altbestand würde
        # (korrekterweise) vorher wegarchiviert, siehe TestFrischesVerzeichnis.
        async def _erzeuge_dateien(*args, **kwargs):
            ziel = workspace / "demo_projekt"
            ziel.mkdir(parents=True, exist_ok=True)
            (ziel / "main.py").write_text("x", encoding="utf-8")
            return "✅ alles gut"

        orch = _FakeOrchestrator(verification_ok=True, tokens_pro_agent=[100], report_text="✅ alles gut")
        orch.process = _erzeuge_dateien
        res = await ev.run_single_task(task, orchestrator=orch)
        assert res.verification_ok is True
        assert res.success is True
        assert res.found_files == ["main.py"]


class TestTokenZaehlung:
    @pytest.mark.asyncio
    async def test_tokens_werden_aus_den_agentenergebnissen_summiert(self, task, workspace):
        orch = _FakeOrchestrator(verification_ok=True, tokens_pro_agent=[1000, 2500, 30], report_text="ok")
        res = await ev.run_single_task(task, orchestrator=orch)
        assert res.total_tokens == 3530

    @pytest.mark.asyncio
    async def test_fehlende_agentenergebnisse_ergeben_null_ohne_absturz(self, task, workspace):
        orch = _FakeOrchestrator(verification_ok=True, tokens_pro_agent=[], report_text="ok")
        orch.last_agent_results = None
        res = await ev.run_single_task(task, orchestrator=orch)
        assert res.total_tokens == 0


class TestFrischesVerzeichnis:
    @pytest.mark.asyncio
    async def test_dateien_eines_frueheren_laufs_zaehlen_nicht_mehr(self, task, workspace):
        """Ein Altbestand darf einen Lauf, der nichts erzeugt, nicht bestehen lassen."""
        alt = workspace / "demo_projekt"
        alt.mkdir()
        (alt / "main.py").write_text("aus einem frueheren Lauf", encoding="utf-8")

        orch = _FakeOrchestrator(verification_ok=False, tokens_pro_agent=[0], report_text=GESCHEITERTER_BERICHT)
        res = await ev.run_single_task(task, orchestrator=orch)

        assert res.missing_files == ["main.py"]
        assert res.success is False
        assert any(p.name.startswith("demo_projekt__eval_archiv_") for p in workspace.iterdir())

    def test_archivierung_ohne_vorhandenes_verzeichnis_ist_ein_no_op(self, workspace):
        ev._archive_previous_project(_FakeWorkspace(workspace), "gibt_es_nicht")
        assert not list(workspace.iterdir())

    def test_fehlgeschlagene_archivierung_bricht_den_benchmark_nicht_ab(self, workspace):
        (workspace / "gesperrt").mkdir()
        meldungen = []
        with patch("pathlib.Path.rename", side_effect=OSError("in Benutzung")):
            ev._archive_previous_project(_FakeWorkspace(workspace), "gesperrt", meldungen.append)
        assert any("konnte nicht archiviert werden" in m for m in meldungen)
