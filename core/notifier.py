"""
core/notifier.py – Optionale externe Benachrichtigung bei Vorfällen, die menschliche
Aufmerksamkeit brauchen (Lauf-Budget erreicht, rote CI, blockiertes Issue, fehlgeschlagener
Dashboard-Job).

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: core/issue_watcher.py (Cron-Poll-
Zyklus) und interface/web_dashboard.py (Hintergrund-Jobs) laufen unbeaufsichtigt – anders als
interface/cli.py sieht in dem Moment, in dem etwas menschliche Aufmerksamkeit braucht, niemand
aktiv zu. Ohne aktiven Blick ins Dashboard/Log/Issue bleibt eine Blockade unbemerkt, bis
jemand zufällig nachschaut.

NOTIFY_WEBHOOK_URL="" (Standard, siehe config.py) deaktiviert das Feature komplett. Gesetzt,
schickt notify_external() einen einfachen JSON-POST ({"text": "..."}) dorthin – kompatibel zu
Slack-Incoming-Webhooks (die gängigste Zielplattform für so etwas). Ein Fehlschlag beim Senden
(Netzwerk, falsche URL, Zielserver down, ...) wird verschluckt – darf NIE einen sonst
erfolgreichen Lauf zum Scheitern bringen, dieselbe Best-Effort-Philosophie wie
memory/run_history.py.record_run(). Bewusst SYNCHRON (kein async def) – Aufrufer in
async-Kontexten nutzen `await asyncio.to_thread(notify_external, ...)`, exakt wie die
bestehenden `await asyncio.to_thread(verifier.ensure_environment)`-Aufrufe.
"""

import httpx

from config import NOTIFY_WEBHOOK_URL

_TIMEOUT_SECONDS = 5.0


def notify_external(event: str, message: str) -> None:
    """
    No-op, wenn kein Webhook konfiguriert ist (Standard). `event` ist ein kurzes Label
    (z.B. "Lauf-Budget erreicht", "CI fehlgeschlagen"), `message` der Detailtext.
    """
    if not NOTIFY_WEBHOOK_URL:
        return
    try:
        httpx.post(
            NOTIFY_WEBHOOK_URL,
            json={"text": f"🤖 [{event}] {message}"},
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception:
        pass  # Best-effort - ein Benachrichtigungs-Fehlschlag darf den Lauf nie stören.
