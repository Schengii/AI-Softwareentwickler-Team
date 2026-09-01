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
schickt notify_external() einen JSON-POST dorthin – kompatibel zu Slack-Incoming-Webhooks
(die gängigste Zielplattform für so etwas). Ein Fehlschlag beim Senden (Netzwerk, falsche URL,
Zielserver down, ...) wird verschluckt – darf NIE einen sonst erfolgreichen Lauf zum Scheitern
bringen, dieselbe Best-Effort-Philosophie wie memory/run_history.py.record_run(). Bewusst
SYNCHRON (kein async def) – Aufrufer in async-Kontexten nutzen
`await asyncio.to_thread(notify_external, ...)`, exakt wie die bestehenden
`await asyncio.to_thread(verifier.ensure_environment)`-Aufrufe.

Realer Fund: das Payload war bisher ein einziger flacher {"text": "..."} String – in Slack
selbst kam das als unformatierter Fließtext ohne jede visuelle Hervorhebung an, obwohl Slack
für genau diesen Zweck ein eigenes Nachrichtenformat (Block Kit) mit fett/Struktur/Farbe
anbietet. _build_slack_payload() nutzt jetzt echtes Block Kit: fett hervorgehobenes Event-
Label, farbiger Rand je nach erkanntem Schweregrad (an bekannten Schlagworten wie
"fehlgeschlagen"/"blockiert"/"Budget erreicht" grob erkannt, kein Anspruch auf Vollständigkeit)
und ein Kontext-Footer mit Zeitstempel. Das oberste "text"-Feld bleibt IMMER zusätzlich gesetzt
– Slacks eigene Fallback-Konvention für Clients/Push-Vorschauen, die Block Kit nicht rendern.
Bewusst NICHT umgesetzt: Threads/Mentions – beides bräuchte die `chat.postMessage`-API mit
einem echten Bot-Token statt einer simplen Webhook-URL, ein anderes Auth-Modell als das
aktuelle, rein URL-basierte Setup.
"""

from datetime import datetime

import httpx

from config import NOTIFY_WEBHOOK_URL

_TIMEOUT_SECONDS = 5.0

# Grobe, rein textbasierte Schweregrad-Erkennung für die Slack-Randfarbe (Block-Kit-
# "attachments"-Farbe) - kein separater severity-Parameter an der Aufrufstelle nötig, jeder
# bestehende notify_external()-Aufruf (core/issue_watcher.py, interface/web_dashboard.py, ...)
# funktioniert unverändert weiter. Reihenfolge relevant: "kritisch" liegt vor "warnung", da eine
# Nachricht theoretisch auf mehrere Muster gleichzeitig passen könnte.
_SEVERITY_MARKERS: tuple[tuple[str, str], ...] = (
    ("#dc2626", ("fehlgeschlagen", "blockiert", "rot", "kritisch", "erreicht", "abgebrochen")),
    ("#d97706", ("warnung", "achtung", "nicht bestanden")),
)
_DEFAULT_COLOR = "#2563eb"


def _severity_color(event: str, message: str) -> str:
    haystack = f"{event} {message}".lower()
    for color, markers in _SEVERITY_MARKERS:
        if any(marker in haystack for marker in markers):
            return color
    return _DEFAULT_COLOR


def _build_slack_payload(event: str, message: str) -> dict:
    """
    Baut ein Slack-Block-Kit-Payload statt eines flachen Text-Strings - "text" bleibt als
    Slack-eigenes Fallback-Feld zusätzlich gesetzt (Push-Vorschau, Clients ohne Block-Kit-
    Rendering). Fremd-Webhooks, die nur ein einfaches "text"-Feld auswerten, funktionieren
    dadurch unverändert weiter (additiv, kein Breaking Change am Payload-Vertrag).
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {
        "text": f"🤖 [{event}] {message}",
        "attachments": [{
            "color": _severity_color(event, message),
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*🤖 {event}*\n{message}"}},
                {"type": "context", "elements": [
                    {"type": "mrkdwn", "text": f"KI-Softwareentwickler-Team · {timestamp}"},
                ]},
            ],
        }],
    }


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
            json=_build_slack_payload(event, message),
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception:
        pass  # Best-effort - ein Benachrichtigungs-Fehlschlag darf den Lauf nie stören.
