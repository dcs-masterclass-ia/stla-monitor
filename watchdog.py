"""
UAS Monitoring — Watchdog
Ping le Web Service Render toutes les 5 min
Alerte Teams si KO, recovery si retour en ligne
"""

import os
import time
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ── CONFIG ──
RENDER_URL     = os.environ.get("RENDER_URL", "https://stla-monitor.onrender.com/")
TEAMS_WEBHOOK  = os.environ.get("TEAMS_WEBHOOK", "")
CHECK_INTERVAL = 300   # 5 minutes
TIMEOUT        = 15    # secondes
MAX_FAILURES   = 2     # alerter après N échecs consécutifs

# ── STATE ──
consecutive_failures = 0
is_down = False
last_alert_time = 0

def now_str():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")

def send_teams(title: str, message: str, color: str = "attention"):
    """Envoie une carte Teams via webhook."""
    if not TEAMS_WEBHOOK:
        log.warning("[Teams] Webhook non configuré")
        return
    payload = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": title,
                        "weight": "Bolder",
                        "size": "Medium",
                        "color": color
                    },
                    {
                        "type": "TextBlock",
                        "text": message,
                        "wrap": True
                    },
                    {
                        "type": "TextBlock",
                        "text": f"🕐 {now_str()}",
                        "isSubtle": True,
                        "size": "Small"
                    }
                ]
            }
        }]
    }
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            TEAMS_WEBHOOK,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            log.info(f"[Teams] Alerte envoyée : {title}")
    except Exception as e:
        log.error(f"[Teams] Erreur envoi : {e}")

def check_render() -> tuple[bool, float, str]:
    """
    Ping Render — retourne (ok, elapsed, reason)
    """
    start = time.time()
    try:
        req = urllib.request.Request(
            RENDER_URL,
            headers={"User-Agent": "UAS-Watchdog/1.0"},
            method="HEAD"
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            elapsed = time.time() - start
            status = r.status
            if status == 200:
                return True, elapsed, f"HTTP {status} en {elapsed:.2f}s"
            else:
                return False, elapsed, f"HTTP {status} inattendu"
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start
        if e.code in (200, 204, 301, 302):
            return True, elapsed, f"HTTP {e.code}"
        return False, elapsed, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        elapsed = time.time() - start
        return False, elapsed, f"URLError: {e.reason}"
    except Exception as e:
        elapsed = time.time() - start
        return False, elapsed, f"Erreur: {str(e)[:100]}"

def main():
    global consecutive_failures, is_down, last_alert_time

    log.info(f"[Watchdog] Démarrage — ping {RENDER_URL} toutes les {CHECK_INTERVAL}s")

    # Alerte de démarrage
    send_teams(
        "✅ UAS Watchdog démarré",
        f"Surveillance de `{RENDER_URL}` toutes les **{CHECK_INTERVAL // 60} minutes**.",
        color="good"
    )

    while True:
        ok, elapsed, reason = check_render()

        if ok:
            log.info(f"[Ping] OK — {reason}")
            if is_down:
                # Recovery
                is_down = False
                consecutive_failures = 0
                send_teams(
                    "✅ UAS Monitoring — Retour en ligne",
                    f"Le service est de nouveau opérationnel.\n\n**Réponse :** {reason}",
                    color="good"
                )
            else:
                consecutive_failures = 0
        else:
            consecutive_failures += 1
            log.warning(f"[Ping] ÉCHEC ({consecutive_failures}/{MAX_FAILURES}) — {reason}")

            if consecutive_failures >= MAX_FAILURES and not is_down:
                is_down = True
                send_teams(
                    "🚨 UAS Monitoring — Service KO",
                    f"Le serveur Render ne répond plus après **{consecutive_failures} tentatives**.\n\n"
                    f"**URL :** `{RENDER_URL}`\n"
                    f"**Raison :** {reason}\n\n"
                    f"Vérifiez les logs Render immédiatement.",
                    color="attention"
                )

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
