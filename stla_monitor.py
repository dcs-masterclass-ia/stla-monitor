"""
STLA Monitor V2 - Multi-marques
- Opel PT + Ford FR
- Détection exhaustive : DNS, TCP, TLS, 3xx/4xx/5xx, contenu KO, timeout
- Alerte Teams Adaptive Card avec diagnostic complet
- Historique persisté sur GitHub
"""

import requests
import time
import logging
import urllib3
import json
import os
import socket
import ssl
from datetime import datetime
from urllib.parse import urlparse
from github import Auth, Github
from playwright.sync_api import sync_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

BRANDS = {
    "Opel PT": {
        "Homepage": "https://www.retoma.opel.pt",
        "Parcours":  "https://www.retoma.opel.pt/retoma",
    },
    "Ford FR": {
        "Homepage":   "https://www.ford-reprise.fr/",
        "Formulaire": "https://www.ford-reprise.fr/form",
    },
    "Aramisauto": {
        "Homepage": "https://www.aramisauto.com/reprise/",
    },
    "La Centrale": {
        "Homepage": "https://www.lacentrale.fr/",
    },
}

# Marques "témoins" — pas d'alerte Teams, juste monitoring passif
REFERENCE_BRANDS = {"Aramisauto", "La Centrale"}

TEAMS_WEBHOOK_URL = "https://default64661b8d1758459ca270b19fe3578e.a7.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/c3181d4e41694cfebd1c7502d219b6a9/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=l0lFm8uGc6kFwT73IzDPQBdNut4ZWgNsaXHosdDEh18"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = "dcs-masterclass-ia/stla-monitor"
GITHUB_FILE  = "status.json"

CHECK_INTERVAL_SECONDS      = 10
RESPONSE_TIME_LIMIT_SECONDS = 8   # Timeout TCP dur — au-delà le serveur est considéré mort
SLOW_THRESHOLD_SECONDS      = 2   # Au-delà : SLOW (dégradé, alerte)
VERY_SLOW_THRESHOLD_SECONDS = 4   # Au-delà : VERY_SLOW (KO)
LOG_FILE    = "stla_monitor.log"
MAX_HISTORY = 100
MAX_CHART   = 100

# Signatures de contenu KO déguisé en 200
ERROR_SIGNATURES = [
    "<Code>AccessDenied</Code>",
    "<Message>Access Denied</Message>",
    "<Error>",
    "AccessDenied",
    "403 Forbidden",
    "503 Service Unavailable",
    "502 Bad Gateway",
    "504 Gateway Timeout",
    "Error 521",
    "Error 522",
    "Error 523",
    "Error 524",
    "cloudflare",
    "This site can't be reached",
    "Application Error",
    "Heroku | Application Error",
]

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

incident_active = {}
history = []
chart_data = {}

for brand, urls in BRANDS.items():
    for page in urls:
        key = f"{brand}:{page}"
        incident_active[key] = False
        chart_data[key] = []

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
        try:
            existing = gh_repo.get_contents(GITHUB_FILE)
            data = json.loads(existing.decoded_content.decode("utf-8"))
            if "chart_data" in data:
                for key in chart_data:
                    if key in data["chart_data"]:
                        chart_data[key] = data["chart_data"][key][-MAX_CHART:]
            if "history" in data:
                history.extend(data["history"][-MAX_HISTORY:])
            log.info("[GitHub] Historique récupéré")
        except Exception:
            log.info("[GitHub] Pas d'historique existant")
    except Exception as e:
        log.error(f"[GitHub] Connexion impossible : {e}")

def take_screenshot(brand, page, url):
    """Prend un screenshot de l'URL en erreur et le pousse sur GitHub."""
    if not gh_repo:
        return None
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_brand = brand.replace(" ", "_").replace("/", "_")
        safe_page = page.replace(" ", "_").replace("/", "_")
        filename = f"screenshots/{safe_brand}_{safe_page}_{timestamp}.png"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            pg = ctx.new_page()
            try:
                pg.goto(url, timeout=15000, wait_until="domcontentloaded")
                pg.wait_for_timeout(2000)
            except Exception:
                pass  # On screenshot même si ça timeout
            screenshot_bytes = pg.screenshot(full_page=False)
            browser.close()

        # Push sur GitHub
        import base64
        content_b64 = base64.b64encode(screenshot_bytes).decode()
        try:
            existing = gh_repo.get_contents(filename)
            gh_repo.update_file(filename, f"screenshot {brand} {page}", screenshot_bytes, existing.sha)
        except Exception:
            gh_repo.create_file(filename, f"screenshot {brand} {page}", screenshot_bytes)

        raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{filename}"
        log.info(f"[Screenshot] Poussé : {filename}")
        return raw_url

    except Exception as e:
        log.error(f"[Screenshot] Erreur : {e}")
        return None


def push_status(statuses):
    if not gh_repo:
        return
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    payload = {
        "updated_at": now,
        "statuses": statuses,
        "history": history[-MAX_HISTORY:],
        "chart_data": {k: v[-MAX_CHART:] for k, v in chart_data.items()},
        "avg_response": {
            k: round(sum(p["elapsed"] for p in v[-20:]) / len(v[-20:]), 2) if v else 0
            for k, v in chart_data.items()
        }
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        try:
            existing = gh_repo.get_contents(GITHUB_FILE)
            gh_repo.update_file(GITHUB_FILE, f"Monitor {now}", content, existing.sha)
        except Exception as e:
            if "sha" in str(e).lower() or "422" in str(e):
                try:
                    existing = gh_repo.get_contents(GITHUB_FILE)
                    gh_repo.update_file(GITHUB_FILE, f"Monitor {now}", content, existing.sha)
                except Exception:
                    gh_repo.create_file(GITHUB_FILE, f"Monitor {now}", content)
            else:
                gh_repo.create_file(GITHUB_FILE, f"Monitor {now}", content)
        log.info("[GitHub] status.json mis à jour")
    except Exception as e:
        log.error(f"[GitHub] Erreur push : {e}")

# ─────────────────────────────────────────────
# DIAGNOSTIC COMPLET
# ─────────────────────────────────────────────

def resolve_dns(hostname):
    try:
        t = time.time()
        ip = socket.gethostbyname(hostname)
        return ip, round(time.time() - t, 3), None
    except socket.gaierror as e:
        return None, round(time.time() - time.time(), 3), str(e)

def check_url(brand, page, url):
    parsed = urlparse(url)
    hostname = parsed.hostname
    details = {"brand": brand, "page": page}

    # 1. Résolution DNS
    t0 = time.time()
    ip, dns_elapsed, dns_error = resolve_dns(hostname)
    details["dns_elapsed"] = dns_elapsed
    details["ip"] = ip or "NON RÉSOLU"

    if not ip:
        elapsed = round(time.time() - t0, 2)
        details["error_type"] = "DNS_FAILURE"
        details["error_detail"] = dns_error
        return False, f"Erreur DNS : {dns_error}", elapsed, details

    # 2. Requête HTTP
    t1 = time.time()
    try:
        # Headers différents pour les sites référence (anti-bot)
        if brand in REFERENCE_BRANDS:
            req_headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
            }
        else:
            req_headers = {
                "User-Agent": "Mozilla/5.0 (compatible; STLA-Monitor/2.0)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        response = requests.get(
            url,
            timeout=RESPONSE_TIME_LIMIT_SECONDS,  # TCP timeout dur à 8s
            allow_redirects=True,
            verify=False,
            headers=req_headers
        )
        elapsed_http = round(time.time() - t1, 2)
        elapsed_total = round(time.time() - t0, 2)

        details["http_status"]   = response.status_code
        details["elapsed_http"]  = elapsed_http
        details["elapsed_total"] = elapsed_total
        details["final_url"]     = response.url  # après redirections
        details["redirect_count"] = len(response.history)
        details["headers"] = {
            "server":        response.headers.get("Server", "—"),
            "content-type":  response.headers.get("Content-Type", "—"),
            "cache-control": response.headers.get("Cache-Control", "—"),
            "x-cache":       response.headers.get("X-Cache", "—"),
            "cf-ray":        response.headers.get("CF-Ray", "—"),
            "x-powered-by":  response.headers.get("X-Powered-By", "—"),
        }

        # 3xx — redirections excessives ou inattendues
        if len(response.history) > 5:
            details["error_type"] = "TOO_MANY_REDIRECTS"
            return False, f"Trop de redirections ({len(response.history)})", elapsed_total, details

        # 4xx
        if 400 <= response.status_code < 500:
            details["error_type"] = f"HTTP_{response.status_code}"
            details["body_preview"] = response.text[:300].strip()
            return False, f"Erreur client HTTP {response.status_code}", elapsed_total, details

        # 5xx
        if response.status_code >= 500:
            details["error_type"] = f"HTTP_{response.status_code}"
            details["body_preview"] = response.text[:300].strip()
            return False, f"Erreur serveur HTTP {response.status_code}", elapsed_total, details

        # Réponse très lente → KO
        if elapsed_http > VERY_SLOW_THRESHOLD_SECONDS:
            details["error_type"] = "VERY_SLOW"
            return False, f"Réponse très lente : {elapsed_http}s (seuil KO : {VERY_SLOW_THRESHOLD_SECONDS}s)", elapsed_total, details

        # Réponse dégradée → warning mais OK
        if elapsed_http > SLOW_THRESHOLD_SECONDS:
            details["error_type"] = "SLOW"
            details["warning"] = True
            # On continue — pas un KO, juste un warning loggé

        # Contenu KO déguisé en 200
        body = response.text[:3000]
        for sig in ERROR_SIGNATURES:
            if sig.lower() in body.lower():
                details["error_type"] = "CONTENT_KO"
                details["triggered_signature"] = sig
                details["body_preview"] = body[:300].strip()
                return False, f"Contenu KO — '{sig}' détecté (HTTP {response.status_code})", elapsed_total, details

        details["error_type"] = None
        return True, f"OK ({response.status_code}) en {elapsed_http}s", elapsed_total, details

    except requests.exceptions.SSLError as e:
        elapsed = round(time.time() - t1, 2)
        details["error_type"] = "SSL_ERROR"
        details["error_detail"] = str(e)[:300]
        return False, "Erreur SSL / certificat invalide", elapsed, details

    except requests.exceptions.ConnectionError as e:
        elapsed = round(time.time() - t1, 2)
        err = str(e)
        if "NameResolutionError" in err or "getaddrinfo" in err:
            details["error_type"] = "DNS_FAILURE"
        elif "Connection refused" in err:
            details["error_type"] = "CONNECTION_REFUSED"
        elif "RemoteDisconnected" in err:
            details["error_type"] = "REMOTE_DISCONNECTED"
        else:
            details["error_type"] = "CONNECTION_ERROR"
        details["error_detail"] = err[:300]
        return False, f"Erreur connexion ({details['error_type']})", elapsed, details

    except requests.exceptions.Timeout:
        elapsed = round(time.time() - t1, 2)
        details["error_type"] = "TIMEOUT"
        return False, f"Pas de réponse du serveur après {RESPONSE_TIME_LIMIT_SECONDS}s (TCP timeout)", elapsed, details

    except requests.exceptions.TooManyRedirects:
        elapsed = round(time.time() - t1, 2)
        details["error_type"] = "TOO_MANY_REDIRECTS"
        return False, "Trop de redirections", elapsed, details

    except Exception as e:
        elapsed = round(time.time() - t1, 2)
        details["error_type"] = "UNKNOWN"
        details["error_detail"] = str(e)[:300]
        return False, f"Erreur inconnue : {type(e).__name__}", elapsed, details

# ─────────────────────────────────────────────
# ALERTE TEAMS
# ─────────────────────────────────────────────

def send_teams_alert(brand, page, url, reason, is_recovery=False, details=None, screenshot_url=None):
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    emoji = "✅" if is_recovery else "🚨"
    title = f"{emoji} {brand} — {page} {'est de nouveau en ligne' if is_recovery else 'est KO'}"

    lines = [
        f"🌐 **URL** : {url}",
        f"⚠️ **Statut** : {'Retour en ligne' if is_recovery else reason}",
        f"🕐 **Heure** : {now_str}",
    ]

    if details and not is_recovery:
        lines.append("")
        lines.append("**── Diagnostic ──**")
        lines.append(f"🔴 **Type** : {details.get('error_type', '—')}")
        lines.append(f"🔍 **IP résolue** : {details.get('ip', '—')}")
        lines.append(f"⏱ **DNS** : {details.get('dns_elapsed', '—')}s")
        if details.get("elapsed_http") is not None:
            lines.append(f"⏱ **HTTP** : {details.get('elapsed_http')}s")
        if details.get("elapsed_total") is not None:
            lines.append(f"⏱ **Total** : {details.get('elapsed_total')}s")
        if details.get("http_status"):
            lines.append(f"📡 **HTTP Status** : {details.get('http_status')}")
        if details.get("redirect_count"):
            lines.append(f"↪️ **Redirections** : {details.get('redirect_count')}")
        if details.get("final_url") and details.get("final_url") != url:
            lines.append(f"🔗 **URL finale** : {details.get('final_url')}")
        if details.get("headers"):
            h = details["headers"]
            lines.append(f"🖥 **Serveur** : {h.get('server', '—')}")
            lines.append(f"📦 **X-Cache** : {h.get('x-cache', '—')}")
            lines.append(f"☁️ **CF-Ray** : {h.get('cf-ray', '—')}")
        if details.get("triggered_signature"):
            lines.append(f"🔎 **Signature KO** : {details.get('triggered_signature')}")
        if details.get("body_preview"):
            lines.append(f"📄 **Extrait** : {details['body_preview'][:200]}")
        if details.get("error_detail"):
            lines.append(f"🔧 **Technique** : {details['error_detail'][:200]}")

    body_text = "\n".join(lines)
    color = "Good" if is_recovery else "Attention"

    card_body = [
        {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "color": color, "wrap": True},
        {"type": "TextBlock", "text": body_text, "wrap": True, "spacing": "Medium"}
    ]

    if screenshot_url and not is_recovery:
        card_body.append({
            "type": "Image",
            "url": screenshot_url,
            "size": "Large",
            "style": "default",
            "spacing": "Medium",
            "altText": f"Screenshot de {page} en erreur"
        })
        card_body.append({
            "type": "ActionSet",
            "actions": [{
                "type": "Action.OpenUrl",
                "title": "Voir le screenshot complet",
                "url": screenshot_url
            }]
        })

    payload = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": card_body
            }
        }]
    }

    try:
        resp = requests.post(TEAMS_WEBHOOK_URL, json=payload, timeout=10, verify=False)
        if resp.status_code in (200, 202):
            log.info(f"[Teams] Alerte envoyée — {brand} {page}")
        else:
            log.warning(f"[Teams] Échec — HTTP {resp.status_code} : {resp.text[:200]}")
    except Exception as e:
        log.error(f"[Teams] Erreur : {e}")

# ─────────────────────────────────────────────
# BOUCLE PRINCIPALE
# ─────────────────────────────────────────────

def run():
    init_github()
    log.info("═" * 60)
    log.info("  STLA Monitor V2 démarré")
    for brand, urls in BRANDS.items():
        log.info(f"  {brand} : {', '.join(urls.keys())}")
    log.info(f"  Intervalle : {CHECK_INTERVAL_SECONDS}s")
    log.info("═" * 60)

    while True:
        statuses = {}
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        now_short = datetime.now().strftime("%H:%M:%S")

        for brand, urls in BRANDS.items():
            statuses[brand] = {}
            for page, url in urls.items():
                key = f"{brand}:{page}"
                ok, reason, elapsed, details = check_url(brand, page, url)

                chart_data[key].append({"time": now_short, "elapsed": elapsed})
                if len(chart_data[key]) > MAX_CHART:
                    chart_data[key].pop(0)

                statuses[brand][page] = {
                    "ok": ok, "reason": reason, "elapsed": elapsed,
                    "checked_at": now, "url": url, "details": details
                }

                icon = "✅" if ok else "❌"
                log.info(f"[{brand}][{page}] {icon} {reason}")

                if ok:
                    if incident_active.get(key):
                        incident_active[key] = False
                        history.append({"time": now, "brand": brand, "page": page, "type": "recovery", "detail": "Retour en ligne", "is_reference": brand in REFERENCE_BRANDS})
                        if brand not in REFERENCE_BRANDS:
                            send_teams_alert(brand, page, url, reason, is_recovery=True, details=details)
                else:
                    if not incident_active.get(key):
                        incident_active[key] = True
                        screenshot_url = None
                        if brand not in REFERENCE_BRANDS:
                            screenshot_url = take_screenshot(brand, page, url)
                            send_teams_alert(brand, page, url, reason, is_recovery=False, details=details, screenshot_url=screenshot_url)
                        history.append({"time": now, "brand": brand, "page": page, "type": "ko", "detail": reason, "diagnostics": details, "screenshot": screenshot_url, "is_reference": brand in REFERENCE_BRANDS})

        push_status(statuses)
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Monitoring arrêté.")
