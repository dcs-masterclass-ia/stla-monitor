"""
STLA Monitor V2 - Multi-marques
- Opel PT + Ford FR + Aramisauto (référence)
- Détection exhaustive : DNS, TCP, TLS, 3xx/4xx/5xx, contenu KO, timeout
- Alerte Teams Adaptive Card avec diagnostic complet + screenshot Playwright
- Historique persisté sur GitHub
- Push temps réel vers Render WebSocket
"""

import requests
import time
import logging
import urllib3
import json
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse
from github import Auth, Github
from playwright.sync_api import sync_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

BRANDS = {
    # ── PORTUGAL ──
    "Opel PT":      {"Homepage": "https://www.retoma.opel.pt",             "Parcours": "https://www.retoma.opel.pt/pagina-modelo"},
    "Abarth PT":    {"Homepage": "https://www.retoma.abarth.pt",           "Parcours": "https://www.retoma.abarth.pt/modelo"},
    "AlfaRomeo PT": {"Homepage": "https://www.retoma.alfaromeo.pt",        "Parcours": "https://www.retoma.alfaromeo.pt/modelo"},
    "Citroen PT":   {"Homepage": "https://www.retoma-citroen.pt",          "Parcours": "https://www.retoma-citroen.pt/pagina-modelo"},
    "DS PT":        {"Homepage": "https://retoma.dsautomobiles.pt",        "Parcours": "https://retoma.dsautomobiles.pt/pagina-modelo"},
    "Fiat PT":      {"Homepage": "https://www.retoma.fiat.pt",             "Parcours": "https://www.retoma.fiat.pt/modelo"},
    "FiatPro PT":   {"Homepage": "https://www.retoma.fiatprofessional.pt", "Parcours": "https://www.retoma.fiatprofessional.pt/modelo"},
    "Jeep PT":      {"Homepage": "https://www.retoma.jeep.pt",             "Parcours": "https://www.retoma.jeep.pt/modelo"},
    "Peugeot PT":   {"Homepage": "https://www.retoma.peugeot.pt",          "Parcours": "https://www.retoma.peugeot.pt/pagina-modelo"},
    # ── FRANCE ──
    "Opel FR":      {"Homepage": "https://www.reprise.opel.fr",            "Parcours": "https://www.reprise.opel.fr/page-modele"},
    "AlfaRomeo FR": {"Homepage": "https://reprise.alfaromeo.fr",           "Parcours": "https://reprise.alfaromeo.fr/page-modele"},
    "Citroen FR":   {"Homepage": "https://www.reprise.citroen.fr",         "Parcours": "https://www.reprise.citroen.fr/page-modele"},
    "DS FR":        {"Homepage": "https://www.reprise.dsautomobiles.fr",   "Parcours": "https://www.reprise.dsautomobiles.fr/page-modele"},
    "Fiat FR":      {"Homepage": "https://reprise.fiat.fr",                "Parcours": "https://reprise.fiat.fr/page-modele"},
    "FiatPro FR":   {"Homepage": "https://reprise.fiatprofessional.com",   "Parcours": "https://reprise.fiatprofessional.com/page-modele"},
    "Jeep FR":      {"Homepage": "https://reprise.jeep.fr",                "Parcours": "https://reprise.jeep.fr/page-modele"},
    "Lancia FR":    {"Homepage": "https://reprise.lancia.fr/",             "Parcours": "https://reprise.lancia.fr/page-modele"},
    "Peugeot FR":   {"Homepage": "https://www.reprise.peugeot.fr",         "Parcours": "https://www.reprise.peugeot.fr/page-modele"},
    # ── ESPAGNE ──
    "Abarth ES":    {"Homepage": "https://tasacion.abarth.es",             "Parcours": "https://tasacion.abarth.es/pagina-modelo"},
    "AlfaRomeo ES": {"Homepage": "https://tasacion.alfaromeo.es",          "Parcours": "https://tasacion.alfaromeo.es/pagina-modelo"},
    "Citroen ES":   {"Homepage": "https://www.tasacion.citroen.es",        "Parcours": "https://www.tasacion.citroen.es/pagina-modelo"},
    "DS ES":        {"Homepage": "https://www.tasacion.dsautomobiles.es",  "Parcours": "https://www.tasacion.dsautomobiles.es/pagina-modelo"},
    "Fiat ES":      {"Homepage": "https://tasacion.fiat.es",               "Parcours": "https://tasacion.fiat.es/pagina-modelo"},
    "FiatPro ES":   {"Homepage": "https://tasacion.fiatprofessional.es",   "Parcours": "https://tasacion.fiatprofessional.es/pagina-modelo"},
    "Jeep ES":      {"Homepage": "https://tasacion.jeep.es",               "Parcours": "https://tasacion.jeep.es/pagina-modelo"},
    "Opel ES":      {"Homepage": "https://www.tasacion.opel.es",           "Parcours": "https://www.tasacion.opel.es/pagina-modelo"},
    "Peugeot ES":   {"Homepage": "https://tasacion.peugeot.es",            "Parcours": "https://tasacion.peugeot.es/pagina-modelo"},
    # ── ITALIE ──
    "Abarth IT":    {"Homepage": "https://www.valutazioneusato.abarth.it",       "Parcours": "https://www.valutazioneusato.abarth.it/modello"},
    "AlfaRomeo IT": {"Homepage": "https://www.valutazioneusato.alfaromeo.it",    "Parcours": "https://www.valutazioneusato.alfaromeo.it/modello"},
    "Citroen IT":   {"Homepage": "https://www.valutazioneusato.citroen.it",      "Parcours": "https://www.valutazioneusato.citroen.it/modello"},
    "DS IT":        {"Homepage": "https://valutazioneusato.dsautomobiles.it",    "Parcours": "https://valutazioneusato.dsautomobiles.it/modello"},
    "Fiat IT":      {"Homepage": "https://www.valutazioneusato.fiat.it",         "Parcours": "https://www.valutazioneusato.fiat.it/modello"},
    "Jeep IT":      {"Homepage": "https://www.valutazioneusato.jeep-official.it","Parcours": "https://www.valutazioneusato.jeep-official.it/modello"},
    "Lancia IT":    {"Homepage": "https://valutazioneusato.lancia.it",           "Parcours": "https://valutazioneusato.lancia.it/modello"},
    "Opel IT":      {"Homepage": "https://www.valutazioneusato.opel.it",         "Parcours": "https://www.valutazioneusato.opel.it/modello"},
    "Peugeot IT":   {"Homepage": "https://www.valutiamoiltuousato.peugeot.it",   "Parcours": "https://www.valutiamoiltuousato.peugeot.it/modello"},
    # ── ALLEMAGNE ──
    "AlfaRomeo DE": {"Homepage": "https://autoankauf.alfaromeo.de",        "Parcours": "https://autoankauf.alfaromeo.de/modell"},
    "Citroen DE":   {"Homepage": "https://www.citroen-kauft-ihr-auto.de",  "Parcours": "https://www.citroen-kauft-ihr-auto.de/modell"},
    "DS DE":        {"Homepage": "https://www.autoankauf.dsautomobiles.de","Parcours": "https://www.autoankauf.dsautomobiles.de/modell"},
    "Opel DE":      {"Homepage": "https://www.opel-kauft-dein-auto.de",    "Parcours": "https://www.opel-kauft-dein-auto.de/modell"},
    "Peugeot DE":   {"Homepage": "https://www.autoankauf.peugeot.de",      "Parcours": "https://www.autoankauf.peugeot.de/modell"},
    "Spoticar DE":  {"Homepage": "https://autoankauf.spoticar.de",         "Parcours": "https://autoankauf.spoticar.de/modell"},
    # ── AUTRICHE ──
    "Citroen AT":   {"Homepage": "https://www.citroen-kauft-ihr-auto.at",      "Parcours": "https://www.citroen-kauft-ihr-auto.at/Modell-Seite"},
    "Opel AT":      {"Homepage": "https://opel-kauft-dein-auto.opel.at",       "Parcours": "https://opel-kauft-dein-auto.opel.at/Modell-Seite"},
    "Peugeot AT":   {"Homepage": "https://www.wir-kaufen-ihr-auto.peugeot.at", "Parcours": "https://www.wir-kaufen-ihr-auto.peugeot.at/Modell-Seite"},
    # ── BELGIQUE FR ──
    "Abarth BE":    {"Homepage": "https://reprise.abarthbelgium.be",            "Parcours": "https://reprise.abarthbelgium.be/page-modele"},
    "AlfaRomeo BE": {"Homepage": "https://reprise.alfaromeo.be",                "Parcours": "https://reprise.alfaromeo.be/page-modele"},
    "Citroen BE":   {"Homepage": "https://reprise.citroen.be",                  "Parcours": "https://reprise.citroen.be/page-modele"},
    "DS BE":        {"Homepage": "https://reprise.dsautomobiles.be",            "Parcours": "https://reprise.dsautomobiles.be/page-modele"},
    "Fiat BE":      {"Homepage": "https://reprise.fiat.be",                     "Parcours": "https://reprise.fiat.be/page-modele"},
    "FiatPro BE":   {"Homepage": "https://reprisebelgique.fiatprofessional.com","Parcours": "https://reprisebelgique.fiatprofessional.com/page-modele"},
    "Jeep BE":      {"Homepage": "https://reprise.jeep.be",                     "Parcours": "https://reprise.jeep.be/page-modele"},
    "Lancia BE":    {"Homepage": "https://reprise.lancia.be",                   "Parcours": "https://reprise.lancia.be/page-modele"},
    "Opel BE":      {"Homepage": "https://www.reprise.opel.be",                 "Parcours": "https://www.reprise.opel.be/page-modele"},
    "Peugeot BE":   {"Homepage": "https://reprise.peugeot.be",                  "Parcours": "https://reprise.peugeot.be/page-modele"},
    "Leapmotor BE": {"Homepage": "https://reprise.leapmotor-international.be",  "Parcours": "https://reprise.leapmotor-international.be/page-modele"},
    # ── BELGIQUE NL ──
    "Abarth BE-NL":    {"Homepage": "https://overname.abarthbelgium.be",           "Parcours": "https://overname.abarthbelgium.be/pagina-model"},
    "AlfaRomeo BE-NL": {"Homepage": "https://overname.alfaromeo.be",               "Parcours": "https://overname.alfaromeo.be/pagina-model"},
    "Citroen BE-NL":   {"Homepage": "https://overname.citroen.be",                 "Parcours": "https://overname.citroen.be/pagina-model"},
    "DS BE-NL":        {"Homepage": "https://overname.dsautomobiles.be",           "Parcours": "https://overname.dsautomobiles.be/pagina-model"},
    "Fiat BE-NL":      {"Homepage": "https://overname.fiat.be",                    "Parcours": "https://overname.fiat.be/pagina-model"},
    "FiatPro BE-NL":   {"Homepage": "https://overname.fiatprofessional.com",       "Parcours": "https://overname.fiatprofessional.com/pagina-model"},
    "Jeep BE-NL":      {"Homepage": "https://overname.jeep.be",                    "Parcours": "https://overname.jeep.be/pagina-model"},
    "Lancia BE-NL":    {"Homepage": "https://overname.lancia.be",                  "Parcours": "https://overname.lancia.be/pagina-model"},
    "Opel BE-NL":      {"Homepage": "https://www.overname.opel.be",                "Parcours": "https://www.overname.opel.be/pagina-model"},
    "Peugeot BE-NL":   {"Homepage": "https://overname.peugeot.be",                 "Parcours": "https://overname.peugeot.be/pagina-model"},
    "Leapmotor BE-NL": {"Homepage": "https://overname.leapmotor-international.be", "Parcours": "https://overname.leapmotor-international.be/pagina-model"},
    # ── POLOGNE ──
    "AlfaRomeo PL": {"Homepage": "https://odkup.alfaromeo.pl",  "Parcours": "https://odkup.alfaromeo.pl/strona-model"},
    "Citroen PL":   {"Homepage": "https://odkup.citroen.pl",    "Parcours": "https://odkup.citroen.pl/strona-model"},
    "Fiat PL":      {"Homepage": "https://odkup.fiat.pl",       "Parcours": "https://odkup.fiat.pl/strona-model"},
    "Jeep PL":      {"Homepage": "https://odkup.jeep.pl",       "Parcours": "https://odkup.jeep.pl/strona-model"},
    "Opel PL":      {"Homepage": "https://www.odkup.opel.pl",   "Parcours": "https://www.odkup.opel.pl/strona-model"},
    "Peugeot PL":   {"Homepage": "https://odkup.peugeot.pl",    "Parcours": "https://odkup.peugeot.pl/strona-model"},
    # ── LUXEMBOURG ──
    "Abarth LU":    {"Homepage": "https://reprise.abarth.lu",                    "Parcours": "https://reprise.abarth.lu/page-modele"},
    "AlfaRomeo LU": {"Homepage": "https://reprise.alfaromeo.lu",                 "Parcours": "https://reprise.alfaromeo.lu/page-modele"},
    "Citroen LU":   {"Homepage": "https://reprise.citroen.lu",                   "Parcours": "https://reprise.citroen.lu/page-modele"},
    "DS LU":        {"Homepage": "https://reprise.dsautomobiles.lu",             "Parcours": "https://reprise.dsautomobiles.lu/page-modele"},
    "Fiat LU":      {"Homepage": "https://reprise.fiat.lu",                      "Parcours": "https://reprise.fiat.lu/page-modele"},
    "FiatPro LU":   {"Homepage": "https://repriseluxembourg.fiatprofessional.com","Parcours": "https://repriseluxembourg.fiatprofessional.com/page-modele"},
    "Jeep LU":      {"Homepage": "https://reprise.jeep.lu",                      "Parcours": "https://reprise.jeep.lu/page-modele"},
    "Lancia LU":    {"Homepage": "https://reprise.lancia.lu",                    "Parcours": "https://reprise.lancia.lu/page-modele"},
    "Opel LU":      {"Homepage": "https://www.reprise.opel.lu",                  "Parcours": "https://www.reprise.opel.lu/page-modele"},
    "Peugeot LU":   {"Homepage": "https://reprise.peugeot.lu",                   "Parcours": "https://reprise.peugeot.lu/page-modele"},
    "Leapmotor LU": {"Homepage": "https://reprise.leapmotor-international.lu",   "Parcours": "https://reprise.leapmotor-international.lu/page-modele"},
    # ── UK ──
    "DS UK":        {"Homepage": "https://www.tradein.dsautomobiles.co.uk",      "Parcours": "https://www.tradein.dsautomobiles.co.uk/model"},
    # ── OEM ──
    "Ford FR":      {"Homepage": "https://www.ford-reprise.fr/",           "Formulaire": "https://www.ford-reprise.fr/form"},
    # ── RÉFÉRENCES ──
    "Aramisauto":   {"Homepage": "https://www.aramisauto.com/reprise/"},
}

REFERENCE_BRANDS = {
    "Aramisauto",
    # Sites bloqués par WAF — nécessitent Playwright
    "Abarth PT", "AlfaRomeo PT", "Citroen PT", "DS PT", "Fiat PT", "FiatPro PT", "Jeep PT", "Peugeot PT", "Opel PT",
    "Abarth ES", "AlfaRomeo ES", "Citroen ES", "DS ES", "Fiat ES", "FiatPro ES", "Jeep ES", "Opel ES", "Peugeot ES",
    "Abarth IT", "AlfaRomeo IT", "Citroen IT", "DS IT", "Fiat IT", "Jeep IT", "Lancia IT", "Opel IT", "Peugeot IT",
    "AlfaRomeo DE", "Citroen DE", "DS DE", "Opel DE", "Peugeot DE", "Spoticar DE",
    "Citroen AT", "Opel AT", "Peugeot AT",
    "Abarth BE", "AlfaRomeo BE", "Citroen BE", "DS BE", "Fiat BE", "FiatPro BE", "Jeep BE", "Lancia BE", "Opel BE", "Peugeot BE", "Leapmotor BE",
    "Abarth BE-NL", "AlfaRomeo BE-NL", "Citroen BE-NL", "DS BE-NL", "Fiat BE-NL", "FiatPro BE-NL", "Jeep BE-NL", "Lancia BE-NL", "Opel BE-NL", "Peugeot BE-NL", "Leapmotor BE-NL",
    "AlfaRomeo PL", "Citroen PL", "Fiat PL", "Jeep PL", "Opel PL", "Peugeot PL",
    "Abarth LU", "AlfaRomeo LU", "Citroen LU", "DS LU", "Fiat LU", "FiatPro LU", "Jeep LU", "Lancia LU", "Opel LU", "Peugeot LU", "Leapmotor LU",
    "Opel FR", "AlfaRomeo FR", "Citroen FR", "DS FR", "Fiat FR", "FiatPro FR", "Jeep FR", "Lancia FR", "Peugeot FR",
    "DS UK",
}

TEAMS_WEBHOOK_URL = "https://default64661b8d1758459ca270b19fe3578e.a7.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/c3181d4e41694cfebd1c7502d219b6a9/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=l0lFm8uGc6kFwT73IzDPQBdNut4ZWgNsaXHosdDEh18"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = "dcs-masterclass-ia/stla-monitor"
GITHUB_FILE  = "status.json"

RENDER_URL = "https://stla-monitor.onrender.com/update"

CHECK_INTERVAL_SECONDS      = 10
RESPONSE_TIME_LIMIT_SECONDS = 8
SLOW_THRESHOLD_SECONDS      = 2
VERY_SLOW_THRESHOLD_SECONDS = 4
LOG_FILE    = "stla_monitor.log"
MAX_HISTORY = 1000
MAX_CHART   = 10080  # 7 jours de checks toutes les 10s

ERROR_SIGNATURES = [
    "<Code>AccessDenied</Code>", "<Message>Access Denied</Message>",
    "<Error>", "AccessDenied", "403 Forbidden",
    "503 Service Unavailable", "502 Bad Gateway", "504 Gateway Timeout",
    "Error 521", "Error 522", "Error 523", "Error 524",
    "Application Error", "Heroku | Application Error",
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

def push_status(statuses):
    if not gh_repo:
        return
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    payload = build_payload(statuses, now)
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

def build_payload(statuses, now):
    return {
        "updated_at": now,
        "statuses": statuses,
        "history": history[-MAX_HISTORY:],
        "chart_data": {k: v[-MAX_CHART:] for k, v in chart_data.items()},
        "avg_response": {
            k: round(sum(p["elapsed"] for p in v[-20:]) / len(v[-20:]), 2) if v else 0
            for k, v in chart_data.items()
        }
    }

# ─────────────────────────────────────────────
# RENDER PUSH
# ─────────────────────────────────────────────

def push_to_render(statuses):
    try:
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        payload = build_payload(statuses, now)
        resp = requests.post(RENDER_URL, json=payload, timeout=5, verify=False)
        if resp.status_code == 200:
            log.info(f"[Render] Données envoyées — {resp.json().get('clients', 0)} client(s)")
    except Exception as e:
        log.warning(f"[Render] Erreur : {e}")

# ─────────────────────────────────────────────
# SCREENSHOT
# ─────────────────────────────────────────────

def take_screenshot(brand, page, url):
    if not gh_repo:
        return None
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = lambda s: s.replace(" ", "_").replace("/", "_")
        filename = f"screenshots/{safe(brand)}_{safe(page)}_{timestamp}.png"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
            pg = ctx.new_page()
            try:
                pg.goto(url, timeout=15000, wait_until="domcontentloaded")
                pg.wait_for_timeout(2000)
            except Exception:
                pass
            screenshot_bytes = pg.screenshot(full_page=False)
            browser.close()
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
        lines.append(f"🔍 **IP** : {details.get('ip', '—')}")
        lines.append(f"⏱ **DNS** : {details.get('dns_elapsed', '—')}s")
        if details.get("elapsed_http") is not None:
            lines.append(f"⏱ **HTTP** : {details.get('elapsed_http')}s")
        if details.get("http_status"):
            lines.append(f"📡 **Status** : {details.get('http_status')}")
        if details.get("headers"):
            h = details["headers"]
            if h.get("server") and h["server"] != "—":
                lines.append(f"🖥 **Serveur** : {h['server']}")
            if h.get("cf-ray") and h["cf-ray"] != "—":
                lines.append(f"☁️ **CF-Ray** : {h['cf-ray']}")
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
        card_body.append({"type": "Image", "url": screenshot_url, "size": "Large", "spacing": "Medium"})
        card_body.append({"type": "ActionSet", "actions": [{"type": "Action.OpenUrl", "title": "Voir screenshot", "url": screenshot_url}]})

    payload = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard", "version": "1.4",
                "body": card_body
            }
        }]
    }

    try:
        resp = requests.post(TEAMS_WEBHOOK_URL, json=payload, timeout=10, verify=False)
        if resp.status_code in (200, 202):
            log.info(f"[Teams] Alerte envoyée — {brand} {page}")
        else:
            log.warning(f"[Teams] Échec — HTTP {resp.status_code}")
    except Exception as e:
        log.error(f"[Teams] Erreur : {e}")

# ─────────────────────────────────────────────
# DNS
# ─────────────────────────────────────────────

def resolve_dns(hostname):
    try:
        t = time.time()
        ip = socket.gethostbyname(hostname)
        return ip, round(time.time() - t, 3), None
    except socket.gaierror as e:
        return None, 0, str(e)

# ─────────────────────────────────────────────
# CHECK URL PLAYWRIGHT (références)
# ─────────────────────────────────────────────

def check_url_playwright(brand, page, url):
    details = {"brand": brand, "page": page}
    t0 = time.time()
    hostname = urlparse(url).hostname
    ip, dns_elapsed, dns_error = resolve_dns(hostname)
    details["dns_elapsed"] = dns_elapsed
    details["ip"] = ip or "NON RÉSOLU"
    if not ip:
        details["error_type"] = "DNS_FAILURE"
        details["error_detail"] = dns_error
        return False, f"Erreur DNS : {dns_error}", round(time.time()-t0, 2), details
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            pg = ctx.new_page()
            BLOCKED = ["google-analytics.com","googletagmanager.com","facebook.net",
                "hotjar.com","segment.com","mixpanel.com","criteo.com","doubleclick.net"]
            def block_tracking(route):
                if any(d in route.request.url for d in BLOCKED): route.abort()
                else: route.continue_()
            pg.route("**/*", block_tracking)
            t1 = time.time()
            resp = pg.goto(url, timeout=RESPONSE_TIME_LIMIT_SECONDS*1000, wait_until="domcontentloaded")
            elapsed = round(time.time()-t1, 2)
            total = round(time.time()-t0, 2)
            status = resp.status if resp else 0
            details.update({"http_status": status, "elapsed_http": elapsed, "elapsed_total": total, "error_type": None})
            browser.close()
            if status >= 400:
                details["error_type"] = f"HTTP_{status}"
                return False, f"HTTP {status}", total, details
            if elapsed > VERY_SLOW_THRESHOLD_SECONDS:
                details["error_type"] = "VERY_SLOW"
                return False, f"Réponse très lente : {elapsed}s", total, details
            return True, f"OK ({status}) en {elapsed}s", total, details
    except Exception as e:
        elapsed = round(time.time()-t0, 2)
        details["error_type"] = "PLAYWRIGHT_ERROR"
        details["error_detail"] = str(e)[:200]
        return False, f"Erreur navigateur : {type(e).__name__}", elapsed, details

# ─────────────────────────────────────────────
# CHECK URL (requests)
# ─────────────────────────────────────────────

def check_url(brand, page, url):
    hostname = urlparse(url).hostname
    details = {"brand": brand, "page": page}
    t0 = time.time()
    ip, dns_elapsed, dns_error = resolve_dns(hostname)
    details["dns_elapsed"] = dns_elapsed
    details["ip"] = ip or "NON RÉSOLU"
    if not ip:
        details["error_type"] = "DNS_FAILURE"
        details["error_detail"] = dns_error
        return False, f"Erreur DNS : {dns_error}", round(time.time()-t0, 2), details
    t1 = time.time()
    try:
        response = requests.get(url, timeout=RESPONSE_TIME_LIMIT_SECONDS,
            allow_redirects=True, verify=False,
            headers={"User-Agent": "Mozilla/5.0 (compatible; STLA-Monitor/2.0)",
                     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
        elapsed_http = round(time.time()-t1, 2)
        elapsed_total = round(time.time()-t0, 2)
        details.update({
            "http_status": response.status_code,
            "elapsed_http": elapsed_http,
            "elapsed_total": elapsed_total,
            "redirect_count": len(response.history),
            "final_url": response.url,
            "headers": {
                "server": response.headers.get("Server", "—"),
                "content-type": response.headers.get("Content-Type", "—"),
                "x-cache": response.headers.get("X-Cache", "—"),
                "cf-ray": response.headers.get("CF-Ray", "—"),
            }
        })
        if len(response.history) > 5:
            details["error_type"] = "TOO_MANY_REDIRECTS"
            return False, f"Trop de redirections ({len(response.history)})", elapsed_total, details
        if 400 <= response.status_code < 500:
            details["error_type"] = f"HTTP_{response.status_code}"
            details["body_preview"] = response.text[:300].strip()
            return False, f"Erreur client HTTP {response.status_code}", elapsed_total, details
        if response.status_code >= 500:
            details["error_type"] = f"HTTP_{response.status_code}"
            details["body_preview"] = response.text[:300].strip()
            return False, f"Erreur serveur HTTP {response.status_code}", elapsed_total, details
        if elapsed_http > VERY_SLOW_THRESHOLD_SECONDS:
            details["error_type"] = "VERY_SLOW"
            return False, f"Réponse très lente : {elapsed_http}s", elapsed_total, details
        body = response.text[:3000]
        for sig in ERROR_SIGNATURES:
            if sig.lower() in body.lower():
                details["error_type"] = "CONTENT_KO"
                details["triggered_signature"] = sig
                details["body_preview"] = body[:300].strip()
                return False, f"Contenu KO — '{sig}' détecté", elapsed_total, details
        details["error_type"] = None
        return True, f"OK ({response.status_code}) en {elapsed_http}s", elapsed_total, details
    except requests.exceptions.SSLError as e:
        details["error_type"] = "SSL_ERROR"
        details["error_detail"] = str(e)[:300]
        return False, "Erreur SSL", round(time.time()-t1, 2), details
    except requests.exceptions.ConnectionError as e:
        err = str(e)
        elapsed = round(time.time()-t1, 2)
        if "NameResolutionError" in err or "getaddrinfo" in err:
            details["error_type"] = "DNS_FAILURE"
        elif "Connection refused" in err:
            details["error_type"] = "CONNECTION_REFUSED"
        else:
            details["error_type"] = "CONNECTION_ERROR"
        details["error_detail"] = err[:300]
        return False, f"Erreur connexion ({details['error_type']})", elapsed, details
    except requests.exceptions.Timeout:
        details["error_type"] = "TIMEOUT"
        return False, f"Pas de réponse après {RESPONSE_TIME_LIMIT_SECONDS}s", round(time.time()-t1, 2), details
    except Exception as e:
        details["error_type"] = "UNKNOWN"
        details["error_detail"] = str(e)[:300]
        return False, f"Erreur : {type(e).__name__}", round(time.time()-t1, 2), details

# ─────────────────────────────────────────────
# BOUCLE PRINCIPALE
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# CHECK IMMAT (France uniquement)
# Saisit une immat, clique sur js-submit-plate,
# vérifie qu'on arrive sur /pormenores-veiculo ou /page-modele
# ─────────────────────────────────────────────

IMMAT_FR = "GJ100ZP"  # Immat FR valide pour décodage

FR_BRANDS = {
    "Opel FR", "AlfaRomeo FR", "Citroen FR", "DS FR",
    "Fiat FR", "FiatPro FR", "Jeep FR", "Lancia FR", "Peugeot FR"
}

# Pages de succès après décodage immat
IMMAT_SUCCESS_SLUGS = [
    "/details-vehicule",
]

def check_immat_fr(brand, homepage_url):
    """
    Vérifie le décodage immat sur les sites FR :
    1. Charge la homepage
    2. Ferme la CMP
    3. Saisit l'immat dans #registration
    4. Clique #js-submit-plate
    5. Vérifie qu'on arrive sur une page de résultat (pas homepage)
    """
    t0 = time.time()
    details = {"brand": brand, "page": "Immat", "error_type": None}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            pg = ctx.new_page()

            # 1. Charger la homepage
            pg.goto(homepage_url, timeout=15000, wait_until="domcontentloaded")
            pg.wait_for_timeout(2000)

            # 2. Fermer la CMP — deux sélecteurs selon la marque
            # Groupe PSA (Opel, Citroën, DS, Peugeot) : a#_psaihm_continue_without_accepting
            # Groupe STLA (Alfa, Fiat, Jeep, Abarth, Lancia) : button#decline-text
            STLA_CMP_BRANDS = {"AlfaRomeo FR", "Fiat FR", "FiatPro FR", "Jeep FR", "Abarth FR", "Lancia FR"}
            try:
                if brand in STLA_CMP_BRANDS:
                    # STLA (Alfa, Fiat, Jeep, Abarth, Lancia) → Tout accepter
                    cmp = pg.locator("button#acceptAllBtn")
                else:
                    # PSA (Opel, Citroën, DS, Peugeot) → Continuer sans accepter
                    cmp = pg.locator("a#_psaihm_continue_without_accepting")
                cmp.wait_for(timeout=5000, state="visible")
                cmp.click()
                pg.wait_for_timeout(1500)
                log.info(f"[{brand}][Immat] CMP fermée")
            except Exception:
                pass

            # 3. Saisir l'immat
            pg.wait_for_selector("#registration", timeout=10000)
            pg.fill("#registration", IMMAT_FR)
            pg.wait_for_timeout(500)

            # 4. Cliquer le bouton d'estimation
            pg.locator("#js-submit-plate").click(timeout=8000)
            pg.wait_for_timeout(3000)

            # 5. Vérifier l'URL résultante
            final_url = pg.url
            elapsed = round(time.time() - t0, 2)
            browser.close()

            # Succès si on n'est plus sur la homepage et sur une page de résultat
            success = any(slug in final_url for slug in IMMAT_SUCCESS_SLUGS)
            if not success and final_url != homepage_url and final_url != homepage_url + "/":
                # On est quand même allé quelque part — c'est ok
                success = True

            details["final_url"] = final_url
            details["elapsed_http"] = elapsed

            if success:
                return True, f"Décodage immat OK → {final_url.split('/')[-1]}", elapsed, details
            else:
                details["error_type"] = "IMMAT_DECODE_FAILED"
                return False, f"Décodage immat KO — resté sur {final_url}", elapsed, details

    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        details["error_type"] = "IMMAT_ERROR"
        details["error_detail"] = str(e)[:200]
        return False, f"Erreur décodage immat : {type(e).__name__}", elapsed, details

def run():
    init_github()
    # Démarrer le keepalive Render en arrière-plan
    threading.Thread(target=_ping_render, daemon=True).start()
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

        # Construire la liste de toutes les tâches à exécuter
        tasks = []
        for brand, urls in BRANDS.items():
            statuses[brand] = {}
            for page, url in urls.items():
                tasks.append((brand, page, url))

        def check_task(task):
            brand, page, url = task
            if brand in REFERENCE_BRANDS:
                return brand, page, url, check_url_playwright(brand, page, url)
            else:
                return brand, page, url, check_url(brand, page, url)

        # Exécuter en parallèle — max 10 workers simultanés
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(check_task, t): t for t in tasks}
            for future in as_completed(futures):
                try:
                    brand, page, url, (ok, reason, elapsed, details) = future.result()
                    key = f"{brand}:{page}"

                    chart_data[key].append({"time": now, "elapsed": elapsed})
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
                            history.append({"time": now, "brand": brand, "page": page,
                                "type": "recovery", "detail": "Retour en ligne",
                                "is_reference": brand in REFERENCE_BRANDS})
                            if brand not in REFERENCE_BRANDS:
                                send_teams_alert(brand, page, url, reason, is_recovery=True, details=details)
                    else:
                        if not incident_active.get(key):
                            incident_active[key] = True
                            screenshot_url = None
                            if brand not in REFERENCE_BRANDS:
                                screenshot_url = take_screenshot(brand, page, url)
                                send_teams_alert(brand, page, url, reason, details=details, screenshot_url=screenshot_url)
                            history.append({"time": now, "brand": brand, "page": page,
                                "type": "ko", "detail": reason, "diagnostics": details,
                                "screenshot": screenshot_url,
                                "is_reference": brand in REFERENCE_BRANDS})
                except Exception as e:
                    log.error(f"Erreur task : {e}")

        # ── CHECK IMMAT FR ──
        for brand in FR_BRANDS:
            if f"{brand}:Immat" not in chart_data:
                chart_data[f"{brand}:Immat"] = []
            if brand not in statuses:
                continue
            homepage_url = BRANDS[brand].get("Homepage")
            if not homepage_url:
                continue
            ok_i, reason_i, elapsed_i, details_i = check_immat_fr(brand, homepage_url)
            key_i = f"{brand}:Immat"
            statuses[brand]["Immat"] = {
                "ok": ok_i, "reason": reason_i, "elapsed": elapsed_i,
                "checked_at": now, "url": homepage_url, "details": details_i
            }
            chart_data[key_i].append({"time": now, "elapsed": elapsed_i})
            if len(chart_data[key_i]) > MAX_CHART:
                chart_data[key_i].pop(0)
            icon_i = "✅" if ok_i else "❌"
            log.info(f"[{brand}][Immat] {icon_i} {reason_i}")
            if ok_i:
                if incident_active.get(key_i):
                    incident_active[key_i] = False
                    history.append({"time": now, "brand": brand, "page": "Immat",
                        "type": "recovery", "detail": "Décodage immat rétabli"})
                    send_teams_alert(brand, "Immat", homepage_url, reason_i, is_recovery=True, details=details_i)
            else:
                if not incident_active.get(key_i):
                    incident_active[key_i] = True
                    screenshot_url = take_screenshot(brand, "Immat", homepage_url)
                    send_teams_alert(brand, "Immat", homepage_url, reason_i, details=details_i, screenshot_url=screenshot_url)
                    history.append({"time": now, "brand": brand, "page": "Immat",
                        "type": "ko", "detail": reason_i, "diagnostics": details_i,
                        "screenshot": screenshot_url})

        push_status(statuses)
        threading.Thread(target=push_to_render, args=(statuses,), daemon=True).start()
        time.sleep(CHECK_INTERVAL_SECONDS)

# Ping Render toutes les 10 min pour éviter la mise en veille (plan free)
_ping_counter = [0]
def _ping_render():
    while True:
        time.sleep(480)  # 8 minutes
        try:
            requests.get("https://stla-monitor.onrender.com/status", timeout=10, verify=False)
            log.info("[Render] Ping keepalive envoyé")
        except Exception:
            pass

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Monitoring arrêté.")
