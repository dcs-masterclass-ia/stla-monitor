"""
STLA Front V2 - Moniteur de disponibilité
- Vérifie 2 URLs toutes les 10 secondes
- Pousse status.json sur GitHub (avec historique des temps de réponse)
- Alerte Teams en cas de KO
"""

import requests
import time
import logging
import urllib3
import json
import os
import socket
from datetime import datetime
from github import Auth, Github

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

URLS = {
    "Homepage": "https://www.retoma.opel.pt",
    "Parcours":  "https://www.retoma.opel.pt/retoma",
}

TEAMS_WEBHOOK_URL = "https://default64661b8d1758459ca270b19fe3578e.a7.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/c3181d4e41694cfebd1c7502d219b6a9/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=l0lFm8uGc6kFwT73IzDPQBdNut4ZWgNsaXHosdDEh18"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = "dcs-masterclass-ia/stla-monitor"
GITHUB_FILE  = "status.json"

CHECK_INTERVAL_SECONDS      = 10
RESPONSE_TIME_LIMIT_SECONDS = 5
LOG_FILE    = "stla_monitor.log"
MAX_HISTORY = 50
MAX_CHART   = 100  # points de courbe conservés

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
chart_data = {name: [] for name in URLS}  # {"time": "...", "elapsed": 0.17}

# ─────────────────────────────────────────────
# GITHUB
# ─────────────────────────────────────────────

gh_repo = None

def init_github():
    global gh_repo
    try:
        g = Github(auth=Auth.Token(GITHUB_TOKEN))
        gh_repo = g.get_repo(GITHUB_REPO)
        log.info(f"[GitHub] Connecté au repo {GITHUB_REPO}")

        # Récupère les données existantes pour ne pas perdre l'historique
        try:
            existing = gh_repo.get_contents(GITHUB_FILE)
            data = json.loads(existing.decoded_content.decode("utf-8"))
            if "chart_data" in data:
                for name in URLS:
                    if name in data["chart_data"]:
                        chart_data[name] = data["chart_data"][name][-MAX_CHART:]
            if "history" in data:
                history.extend(data["history"][-MAX_HISTORY:])
            log.info("[GitHub] Historique récupéré depuis status.json")
        except Exception:
            log.info("[GitHub] Pas d'historique existant, démarrage à zéro")

    except Exception as e:
        log.error(f"[GitHub] Connexion impossible : {e}")

def push_status(statuses):
    if not gh_repo:
        return
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    payload = {
        "updated_at": now,
        "statuses": statuses,
        "history": history[-MAX_HISTORY:],
        "chart_data": {name: pts[-MAX_CHART:] for name, pts in chart_data.items()},
        "avg_response": {
            name: round(sum(p["elapsed"] for p in pts[-20:]) / len(pts[-20:]), 2) if pts else 0
            for name, pts in chart_data.items()
        }
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        try:
            existing = gh_repo.get_contents(GITHUB_FILE)
            gh_repo.update_file(GITHUB_FILE, f"Monitor update {now}", content, existing.sha)
        except Exception as e:
            if "422" in str(e) or "sha" in str(e).lower():
                # Récupère le SHA manquant et réessaie
                try:
                    existing = gh_repo.get_contents(GITHUB_FILE)
                    gh_repo.update_file(GITHUB_FILE, f"Monitor update {now}", content, existing.sha)
                except Exception:
                    gh_repo.create_file(GITHUB_FILE, f"Monitor init {now}", content)
            else:
                gh_repo.create_file(GITHUB_FILE, f"Monitor init {now}", content)
        log.info("[GitHub] status.json mis à jour")
    except Exception as e:
        log.error(f"[GitHub] Erreur push : {e}")

# ─────────────────────────────────────────────
# ALERTE TEAMS
# ─────────────────────────────────────────────

def send_teams_alert(name, url, reason, is_recovery=False, details=None):
    if is_recovery:
        title = f"✅ STLA — {name} est de nouveau accessible"
        color = "00FF00"
        status_text = "Retour en ligne"
    else:
        title = f"🚨 STLA — {name} est KO !"
        color = "FF0000"
        status_text = reason

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # Construction du corps texte avec tous les détails
    lines = [
        f"**{title}**",
        f"",
        f"🌐 **URL** : {url}",
        f"⚠️ **Statut** : {status_text}",
        f"🕐 **Heure** : {now_str}",
    ]

    if details:
        lines.append("")
        lines.append("**── Diagnostic ──**")
        if details.get("ip"):
            lines.append(f"🔍 **IP résolue** : {details['ip']}")
        if details.get("dns_elapsed") is not None:
            lines.append(f"⏱ **Résolution DNS** : {details['dns_elapsed']}s")
        if details.get("elapsed_http") is not None:
            lines.append(f"⏱ **Temps HTTP** : {details['elapsed_http']}s")
        if details.get("elapsed_total") is not None:
            lines.append(f"⏱ **Temps total** : {details['elapsed_total']}s")
        if details.get("http_status"):
            lines.append(f"📡 **HTTP Status** : {details['http_status']}")
        if details.get("error_type"):
            lines.append(f"🔴 **Type d'erreur** : {details['error_type']}")
        if details.get("headers"):
            h = details["headers"]
            lines.append(f"🖥 **Serveur** : {h.get('server', '—')}")
            lines.append(f"📦 **X-Cache** : {h.get('x-cache', '—')}")
            lines.append(f"☁️ **CF-Ray** : {h.get('cf-ray', '—')}")
        if details.get("body_preview"):
            lines.append(f"📄 **Extrait erreur** : {details['body_preview'][:200]}")
        if details.get("error_detail"):
            lines.append(f"🔧 **Détail technique** : {details['error_detail'][:200]}")

    body_text = "\n".join(lines)

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
                        "color": "Good" if is_recovery else "Attention",
                        "wrap": True
                    },
                    {
                        "type": "TextBlock",
                        "text": body_text,
                        "wrap": True,
                        "spacing": "Medium"
                    }
                ]
            }
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

def resolve_ip(hostname):
    """Tente de résoudre l'IP du hostname."""
    try:
        ip = socket.gethostbyname(hostname)
        return ip
    except socket.gaierror:
        return None

def check_url(name, url):
    from urllib.parse import urlparse
    hostname = urlparse(url).hostname
    details = {}

    # Résolution DNS
    t_dns_start = time.time()
    ip = resolve_ip(hostname)
    details["dns_elapsed"] = round(time.time() - t_dns_start, 3)
    details["ip"] = ip if ip else "NON RÉSOLU"

    if not ip:
        elapsed = details["dns_elapsed"]
        details["error_type"] = "DNS"
        return False, "Erreur DNS — impossible de résoudre le nom de domaine", elapsed, details

    # Requête HTTP
    start = time.time()
    try:
        response = requests.get(url, timeout=RESPONSE_TIME_LIMIT_SECONDS,
                                allow_redirects=True, verify=False,
                                headers={"User-Agent": "STLA-Monitor/1.0"})
        elapsed = round(time.time() - start, 2)
        total_elapsed = round(details["dns_elapsed"] + elapsed, 2)

        details["http_status"] = response.status_code
        details["elapsed_http"] = elapsed
        details["elapsed_total"] = total_elapsed
        details["headers"] = {
            "server": response.headers.get("Server", "—"),
            "content-type": response.headers.get("Content-Type", "—"),
            "cache-control": response.headers.get("Cache-Control", "—"),
            "x-cache": response.headers.get("X-Cache", "—"),
            "cf-ray": response.headers.get("CF-Ray", "—"),
        }

        # Temps de réponse trop long
        if elapsed > RESPONSE_TIME_LIMIT_SECONDS:
            details["error_type"] = "TIMEOUT_SOFT"
            return False, f"Temps de réponse trop long : {elapsed}s", elapsed, details

        # Erreur HTTP
        if response.status_code >= 400:
            details["error_type"] = f"HTTP_{response.status_code}"
            body_preview = response.text[:300].strip().replace("\n", " ")
            details["body_preview"] = body_preview
            return False, f"HTTP {response.status_code}", elapsed, details

        # Contenu KO déguisé en 200
        body = response.text[:2000]
        error_signatures = [
            "<Code>AccessDenied</Code>",
            "<Message>Access Denied</Message>",
            "<Error>",
            "AccessDenied",
            "503 Service Unavailable",
            "502 Bad Gateway",
            "403 Forbidden",
        ]
        for sig in error_signatures:
            if sig in body:
                details["error_type"] = "CONTENT_KO"
                details["body_preview"] = body[:300].strip().replace("\n", " ")
                return False, f"Contenu KO — '{sig}' détecté (HTTP {response.status_code})", elapsed, details

        details["error_type"] = None
        return True, f"OK ({response.status_code}) en {elapsed}s", elapsed, details

    except requests.exceptions.ConnectionError as e:
        elapsed = round(time.time() - start, 2)
        details["elapsed_http"] = elapsed
        details["error_type"] = "CONNECTION_ERROR"
        details["error_detail"] = str(e)[:200]
        return False, "Erreur de connexion", elapsed, details

    except requests.exceptions.Timeout:
        elapsed = round(time.time() - start, 2)
        details["elapsed_http"] = elapsed
        details["error_type"] = "TIMEOUT"
        return False, f"Timeout après {RESPONSE_TIME_LIMIT_SECONDS}s", elapsed, details

    except Exception as e:
        elapsed = round(time.time() - start, 2)
        details["error_type"] = "UNKNOWN"
        details["error_detail"] = str(e)[:200]
        return False, f"Erreur inattendue : {e}", elapsed, details

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
        now_short = datetime.now().strftime("%H:%M:%S")

        for name, url in URLS.items():
            ok, reason, elapsed, details = check_url(name, url)

            # Ajoute le point à la courbe
            chart_data[name].append({"time": now_short, "elapsed": elapsed})
            if len(chart_data[name]) > MAX_CHART:
                chart_data[name].pop(0)

            statuses[name] = {
                "ok": ok,
                "reason": reason,
                "elapsed": elapsed,
                "checked_at": now,
                "url": url,
                "details": details
            }

            if ok:
                log.info(f"[{name}] ✅ {reason}")
                if incident_active[name]:
                    incident_active[name] = False
                    history.append({"time": now, "name": name, "type": "recovery", "detail": "Retour en ligne"})
                    send_teams_alert(name, url, reason, is_recovery=True, details=details)
            else:
                log.warning(f"[{name}] ❌ {reason}")
                if not incident_active[name]:
                    incident_active[name] = True
                    history.append({"time": now, "name": name, "type": "ko", "detail": reason, "diagnostics": details})
                    send_teams_alert(name, url, reason, details=details)

        push_status(statuses)
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Monitoring arrêté.")
