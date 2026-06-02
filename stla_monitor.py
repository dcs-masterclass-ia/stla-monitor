"""
STLA Front V2 - Moniteur de disponibilité
- Vérifie 2 URLs toutes les 10 secondes
- Pousse status.json sur GitHub
- Alerte Teams en cas de KO
"""

import requests
import time
import logging
import urllib3
import json
import base64
from datetime import datetime
from github import Github

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────
# CONFIGURATION — mets tes vraies valeurs ici
# ─────────────────────────────────────────────

URLS = {
    "Homepage": "https://www.retoma.opel.pt",
    "Parcours":  "https://www.retoma.opel.pt/retoma",
}

TEAMS_WEBHOOK_URL = "https://default64661b8d1758459ca270b19fe3578e.a7.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/c3181d4e41694cfebd1c7502d219b6a9/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=l0lFm8uGc6kFwT73IzDPQBdNut4ZWgNsaXHosdDEh18"

GITHUB_TOKEN    = "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"   # ← colle ton token ici
GITHUB_REPO     = "dcs-masterclass-ia/stla-monitor"  # ← ex: "maximefoureau/stla-monitor"
GITHUB_FILE     = "status.json"

CHECK_INTERVAL_SECONDS   = 10
RESPONSE_TIME_LIMIT_SECONDS = 5
LOG_FILE = "stla_monitor.log"
MAX_HISTORY = 50  # nombre max d'incidents gardés en mémoire

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ÉTAT
# ─────────────────────────────────────────────

incident_active = {name: False for name in URLS}
history = []
response_times = {name: [] for name in URLS}

# ─────────────────────────────────────────────
# GITHUB
# ─────────────────────────────────────────────

gh_repo = None
gh_file_sha = None

def init_github():
    global gh_repo
    try:
        g = Github(GITHUB_TOKEN)
        gh_repo = g.get_repo(GITHUB_REPO)
        log.info(f"[GitHub] Connecté au repo {GITHUB_REPO}")
    except Exception as e:
        log.error(f"[GitHub] Connexion impossible : {e}")

def push_status(statuses):
    global gh_file_sha
    if not gh_repo:
        return
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    payload = {
        "updated_at": now,
        "statuses": statuses,
        "history": history[-MAX_HISTORY:],
        "avg_response": {
            name: round(sum(times[-20:]) / len(times[-20:]), 2) if times else 0
            for name, times in response_times.items()
        }
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        try:
            existing = gh_repo.get_contents(GITHUB_FILE)
            gh_repo.update_file(GITHUB_FILE, f"Monitor update {now}", content, existing.sha)
        except Exception:
            gh_repo.create_file(GITHUB_FILE, f"Monitor init {now}", content)
        log.info("[GitHub] status.json mis à jour")
    except Exception as e:
        log.error(f"[GitHub] Erreur push : {e}")

# ─────────────────────────────────────────────
# ALERTE TEAMS
# ─────────────────────────────────────────────

def send_teams_alert(name, url, reason, is_recovery=False):
    if is_recovery:
        title = f"✅ STLA — {name} est de nouveau accessible"
        color = "00FF00"
        status_text = "Retour en ligne"
    else:
        title = f"🚨 STLA — {name} est KO !"
        color = "FF0000"
        status_text = reason

    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color,
        "summary": title,
        "sections": [{
            "activityTitle": title,
            "facts": [
                {"name": "URL",    "value": url},
                {"name": "Statut", "value": status_text},
                {"name": "Heure",  "value": datetime.now().strftime("%d/%m/%Y %H:%M:%S")},
            ],
            "markdown": True
        }]
    }
    try:
        resp = requests.post(TEAMS_WEBHOOK_URL, json=payload, timeout=10, verify=False)
        if resp.status_code in (200, 202):
            log.info(f"[Teams] Alerte envoyée pour {name}")
        else:
            log.warning(f"[Teams] Échec — HTTP {resp.status_code}")
    except Exception as e:
        log.error(f"[Teams] Erreur : {e}")

# ─────────────────────────────────────────────
# CHECK URL
# ─────────────────────────────────────────────

def check_url(name, url):
    start = time.time()
    try:
        response = requests.get(url, timeout=RESPONSE_TIME_LIMIT_SECONDS,
                                allow_redirects=True, verify=False,
                                headers={"User-Agent": "STLA-Monitor/1.0"})
        elapsed = round(time.time() - start, 2)
        if elapsed > RESPONSE_TIME_LIMIT_SECONDS:
            return False, f"Temps de réponse trop long : {elapsed}s", elapsed
        if response.status_code >= 400:
            return False, f"HTTP {response.status_code}", elapsed
        return True, f"OK ({response.status_code}) en {elapsed}s", elapsed
    except requests.exceptions.ConnectionError as e:
        elapsed = round(time.time() - start, 2)
        if "NameResolutionError" in str(e) or "getaddrinfo" in str(e):
            return False, "Erreur DNS", elapsed
        return False, f"Erreur connexion", elapsed
    except requests.exceptions.Timeout:
        elapsed = round(time.time() - start, 2)
        return False, f"Timeout", elapsed
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        return False, f"Erreur : {e}", elapsed

# ─────────────────────────────────────────────
# BOUCLE PRINCIPALE
# ─────────────────────────────────────────────

def run():
    init_github()
    log.info("═" * 60)
    log.info("  STLA Monitor démarré")
    log.info(f"  URLs : {', '.join(URLS.keys())}")
    log.info(f"  Intervalle : {CHECK_INTERVAL_SECONDS}s")
    log.info("═" * 60)

    while True:
        statuses = {}
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        for name, url in URLS.items():
            ok, reason, elapsed = check_url(name, url)
            response_times[name].append(elapsed)

            statuses[name] = {
                "ok": ok,
                "reason": reason,
                "elapsed": elapsed,
                "checked_at": now,
                "url": url
            }

            if ok:
                log.info(f"[{name}] ✅ {reason}")
                if incident_active[name]:
                    incident_active[name] = False
                    history.append({"time": now, "name": name, "type": "recovery", "detail": "Retour en ligne"})
                    send_teams_alert(name, url, reason, is_recovery=True)
            else:
                log.warning(f"[{name}] ❌ {reason}")
                if not incident_active[name]:
                    incident_active[name] = True
                    history.append({"time": now, "name": name, "type": "ko", "detail": reason})
                    send_teams_alert(name, url, reason)

        push_status(statuses)
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Monitoring arrêté.")
