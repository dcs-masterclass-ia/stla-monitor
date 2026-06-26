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
import urllib.request
import json
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo
TZ_PARIS = ZoneInfo("Europe/Paris")
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
    "Opel AT":      {"Homepage": "https://opel-kauft-dein-auto.opel.at",       "Parcours": "https://opel-kauft-dein-auto.opel.at/Seite-Modell"},
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
    "Ford FR PPR":  {"Homepage": "https://test-ppr-oem-site-factory.shakazoola.com/fr", "Formulaire": "https://test-ppr-oem-site-factory.shakazoola.com/fr/form"},
    "Motor ES":     {"Homepage": "https://tax.motor.es/?layout=iframe"},
    # ── RÉFÉRENCES ──
    "Aramisauto":   {"Homepage": "https://www.aramisauto.com/reprise/"},
}

REFERENCE_BRANDS = {
    "Aramisauto",   # Site de référence
    "Ford FR PPR",  # PPR — pas d'alerte Teams
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

TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL") or os.environ.get("TEAMS_WEBHOOK") or "https://default64661b8d1758459ca270b19fe3578e.a7.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/c3181d4e41694cfebd1c7502d219b6a9/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=l0lFm8uGc6kFwT73IzDPQBdNut4ZWgNsaXHosdDEh18"

SUPABASE_URL = "https://vqkzrvwwtiktofkpmelt.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZxa3pydnd3dGlrdG9ma3BtZWx0Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MTk0MDMwNCwiZXhwIjoyMDk3NTE2MzA0fQ.gav2bMIzDp8Fv7BS1pigxnQUCBAaJ4sxN0eFF8I5tcY"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = "dcs-masterclass-ia/stla-monitor"
GITHUB_FILE  = "status.json"

RENDER_URL = "https://stla-monitor.onrender.com/update"

CHECK_INTERVAL_SECONDS      = 10
RESPONSE_TIME_LIMIT_SECONDS = 8
SLOW_THRESHOLD_SECONDS      = 2
VERY_SLOW_THRESHOLD_SECONDS = 4

# Timeout personnalisé par brand (en secondes)
BRAND_TIMEOUT = {
    "Ford FR": 15,  # API autobiz référentiel ralentit la réponse
}
DEFAULT_TIMEOUT = RESPONSE_TIME_LIMIT_SECONDS  # 8s
LOG_FILE    = "stla_monitor.log"
MAX_HISTORY = 1000
MAX_CHART   = 2160   # 6h de checks toutes les 10s — réduit pour limiter la RAM

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
history_lock = threading.Lock()
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

def load_history_from_incidents():
    """Charge tous les incidents depuis le dossier incidents/ sur GitHub."""
    if not gh_repo:
        return []
    all_incidents = []
    try:
        from datetime import datetime as dt
        today = dt.now(TZ_PARIS)
        dates = [
            (today - __import__('datetime').timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(7)
        ]
        for date in dates:
            try:
                files = gh_repo.get_contents(f"incidents/{date}")
                for f in files:
                    try:
                        incidents = json.loads(f.decoded_content.decode("utf-8"))
                        all_incidents.extend(incidents)
                    except Exception:
                        pass
            except Exception:
                pass
        log.info(f"[GitHub] incidents/ : {len(all_incidents)} incidents chargés")
    except Exception as e:
        log.error(f"[GitHub] Erreur chargement incidents/ : {e}")
    return all_incidents

def init_github():
    global gh_repo
    try:
        g = Github(auth=Auth.Token(GITHUB_TOKEN))
        gh_repo = g.get_repo(GITHUB_REPO)
        log.info(f"[GitHub] Connecté au repo {GITHUB_REPO}")
        try:
            # Lire status.json via raw URL (évite la limite 1MB de get_contents)
            raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_FILE}"
            req = urllib.request.Request(raw_url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())

            if "chart_data" in data:
                for key, values in data["chart_data"].items():
                    chart_data[key] = values[-MAX_CHART:]

            # Toujours charger depuis chart_data.json backup si peu de points
            current_pts = sum(len(v) for v in chart_data.values())
            if current_pts < 5000:
                try:
                    raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/chart_data.json"
                    req = urllib.request.Request(raw_url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        cd_data = json.loads(r.read())
                    for key, values in cd_data.get("chart_data", {}).items():
                        if key not in chart_data or len(values) > len(chart_data.get(key,[])):
                            chart_data[key] = values[-MAX_CHART:]
                    log.info(f"[GitHub] chart_data restauré depuis backup : {len(chart_data)} clés, {sum(len(v) for v in chart_data.values())} points")
                except Exception as e:
                    log.info(f"[GitHub] Pas de backup chart_data : {e}")

            # Charger history depuis status.json
            status_hist = data.get("history", [])

            # Toujours charger depuis incidents/ en fallback
            folder_hist = load_history_from_incidents()

            # Merger les deux — dédupliquer par time+brand+page+type
            seen = set()
            merged = []
            for h in status_hist + folder_hist:
                key = f"{h.get('time')}|{h.get('brand')}|{h.get('page')}|{h.get('type')}"
                if key not in seen:
                    seen.add(key)
                    merged.append(h)

            merged.sort(key=lambda h: h.get("time", ""))

            if merged:
                history.clear()
                history.extend(merged[-MAX_HISTORY:])
                log.info(f"[GitHub] Historique final : {len(history)} entrées")

            # Reconstruire incident_active depuis les incidents/ du jour
            try:
                from datetime import datetime as _dt
                today = _dt.now(TZ_PARIS).strftime("%Y-%m-%d")
                today_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/incidents/{today}"
                today_req = urllib.request.Request(today_url, headers={
                    "Authorization": f"token {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json"
                })
                with urllib.request.urlopen(today_req, timeout=10) as r:
                    files = json.loads(r.read())
                all_today = []
                for f in files:
                    raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/incidents/{today}/{f['name']}"
                    req2 = urllib.request.Request(raw_url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
                    with urllib.request.urlopen(req2, timeout=10) as r2:
                        all_today.extend(json.loads(r2.read()))
                all_today.sort(key=lambda h: h.get("time",""))
                # Trouver le dernier événement par brand:page
                last_event = {}
                for h in all_today:
                    k = f"{h.get('brand')}:{h.get('page')}"
                    last_event[k] = h.get("type")
                for k, etype in last_event.items():
                    incident_active[k] = (etype == "ko")
                    if etype == "ko":
                        log.info(f"[GitHub] Incident actif restauré : {k}")
                log.info(f"[GitHub] incident_active reconstruit : {sum(v for v in incident_active.values())} actifs")
            except Exception as e:
                log.warning(f"[GitHub] Reconstruction incident_active depuis history: {e}")
                # Fallback sur history en mémoire
                last_event = {}
                for h in history:
                    k = f"{h.get('brand')}:{h.get('page')}"
                    last_event[k] = h.get("type")
                for k, etype in last_event.items():
                    if etype == "ko":
                        incident_active[k] = True
                        log.info(f"[GitHub] Incident actif restauré (fallback) : {k}")
        except Exception as e:
            log.error(f"[GitHub] Erreur chargement : {e}")
    except Exception as e:
        log.error(f"[GitHub] Connexion impossible : {e}")

_cycle_counter = [0]

def push_chart_backup():
    """Sauvegarde chart_data dans chart_data.json sur GitHub — merge avec l'existant."""
    if not gh_repo:
        return
    try:
        path = "chart_data.json"
        new_cd = {k: v[-MAX_CHART:] for k, v in chart_data.items()}

        # Lire l'existant via raw URL (évite la limite 1MB de get_contents)
        try:
            raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{path}"
            req = urllib.request.Request(raw_url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                existing_data = json.loads(r.read())
            old_cd = existing_data.get("chart_data", {})

            # Merger
            merged = {}
            for key in set(list(old_cd.keys()) + list(new_cd.keys())):
                seen = set()
                all_pts = []
                for p in (old_cd.get(key, []) + new_cd.get(key, [])):
                    if p["time"] not in seen:
                        seen.add(p["time"])
                        all_pts.append(p)
                all_pts.sort(key=lambda p: p["time"])
                merged[key] = all_pts[-MAX_CHART:]

            # Récupérer le SHA via API (fichier peut être >1MB, on ne lit que le SHA)
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
            api_req = urllib.request.Request(api_url, headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            })
            with urllib.request.urlopen(api_req, timeout=10) as r:
                meta = json.loads(r.read())
            sha = meta["sha"]

            content = json.dumps({"chart_data": merged}, ensure_ascii=False)
            import base64 as b64
            encoded = b64.b64encode(content.encode()).decode()
            body = json.dumps({"message": "chart_data backup", "content": encoded, "sha": sha}).encode()
            put_req = urllib.request.Request(api_url, data=body, headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json"
            }, method="PUT")
            with urllib.request.urlopen(put_req, timeout=30) as r:
                pass
            total = sum(len(v) for v in merged.values())

        except Exception as e:
            # Créer le fichier s'il n'existe pas
            content = json.dumps({"chart_data": new_cd}, ensure_ascii=False)
            import base64 as b64
            encoded = b64.b64encode(content.encode()).decode()
            gh_repo.create_file(path, "chart_data backup", content)
            total = sum(len(v) for v in new_cd.values())

        log.info(f"[GitHub] chart_data backup : {total} points")
    except Exception as e:
        log.error(f"[GitHub] Erreur chart_data backup : {e}")

def get_paused_brands():
    """Récupère les brands en pause depuis Supabase."""
    try:
        import urllib.request
        now_iso = datetime.now(TZ_PARIS).isoformat()
        url = f"{SUPABASE_URL}/rest/v1/brand_pauses?select=brand,paused_until"
        req = urllib.request.Request(url, headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req, timeout=5) as r:
            rows = json.loads(r.read())
        paused = {}
        for row in rows:
            brand_name = row["brand"]
            until = row["paused_until"]
            if until is None:
                # Pause permanente
                paused[brand_name] = None
            else:
                # Pause temporaire — vérifier si encore active
                from datetime import datetime as _dt
                until_dt = _dt.fromisoformat(until.replace("Z", "+00:00"))
                until_paris = until_dt.astimezone(TZ_PARIS)
                if until_paris > datetime.now(TZ_PARIS):
                    paused[brand_name] = until_paris
                # Sinon la pause est expirée — on ignore
        return paused
    except Exception as e:
        log.warning(f"[Pause] Erreur lecture Supabase : {e}")
        return {}

def supabase_insert(incident):
    """Insère un incident dans Supabase pour historique long terme."""
    try:
        from datetime import datetime as dt
        # Parser le time depuis le format dd/mm/yyyy HH:MM:SS
        t_str = incident.get("time", "")
        try:
            t_parsed = dt.strptime(t_str, "%d/%m/%Y %H:%M:%S")
            t_iso = t_parsed.strftime("%Y-%m-%dT%H:%M:%S+02:00")
        except Exception:
            t_iso = dt.now(TZ_PARIS).isoformat()

        payload = {
            "brand": incident.get("brand"),
            "page": incident.get("page"),
            "type": incident.get("type"),
            "detail": incident.get("detail"),
            "diagnostics": incident.get("diagnostics"),
            "screenshot_url": incident.get("screenshot"),
            "time": t_iso,
        }
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/incidents",
            json=payload,
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            timeout=10,
            verify=False
        )
        if resp.status_code in (200, 201):
            log.info(f"[Supabase] Incident inséré : {incident.get('brand')} / {incident.get('page')} / {incident.get('type')}")
        else:
            log.error(f"[Supabase] Erreur insert : {resp.status_code} {resp.text}")
    except Exception as e:
        log.error(f"[Supabase] Exception : {e}")

def archive_incident(incident):
    """Archive un incident dans incidents/YYYY-MM-DD/Brand_Name.json sur GitHub."""
    if not gh_repo:
        return
    try:
        date = datetime.now(TZ_PARIS).strftime("%Y-%m-%d")
        brand_slug = incident["brand"].replace(" ", "_")
        path = f"incidents/{date}/{brand_slug}.json"
        inc_key = f"{incident.get('time')}|{incident.get('page')}|{incident.get('type')}"

        # Lire via raw URL (évite la limite 1MB et les erreurs encoding)
        raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{path}"
        req = urllib.request.Request(raw_url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                existing_data = json.loads(r.read())
            # Dédupliquer
            existing_keys = {f"{h.get('time')}|{h.get('page')}|{h.get('type')}" for h in existing_data}
            if inc_key in existing_keys:
                log.info(f"[Archive] Doublon ignoré : {inc_key}")
                return
            existing_data.append(incident)
            new_data = existing_data
            # Récupérer le SHA via API
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
            req2 = urllib.request.Request(api_url, headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            })
            with urllib.request.urlopen(req2, timeout=10) as r2:
                meta = json.loads(r2.read())
            sha = meta["sha"]
            # Mettre à jour
            import base64 as b64
            encoded = b64.b64encode(json.dumps(new_data, ensure_ascii=False, indent=2).encode()).decode()
            body = json.dumps({"message": f"incident {brand_slug} {date}", "content": encoded, "sha": sha}).encode()
            req3 = urllib.request.Request(api_url, data=body, headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json"
            }, method="PUT")
            with urllib.request.urlopen(req3, timeout=15) as r3:
                pass
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Fichier n'existe pas — créer
                gh_repo.create_file(path, f"incident {brand_slug} {date}",
                                    json.dumps([incident], ensure_ascii=False, indent=2))
            else:
                raise

        log.info(f"[Archive] {incident['brand']} / {incident['page']} / {incident['type']} archivé")
    except Exception as e:
        log.error(f"[Archive] Erreur : {e}")

def push_status(statuses, retry=3):
    if not gh_repo:
        log.error("[GitHub] gh_repo est None — token manquant ou init échouée")
        send_teams_alert_raw("🚨 ERREUR : gh_repo est None — token GitHub manquant ou révoqué. Le dashboard ne se met plus à jour.")
        return
    now = datetime.now(TZ_PARIS).strftime("%d/%m/%Y %H:%M:%S")
    payload = build_payload(statuses, now)

    # Si history vide en mémoire, charger depuis incidents/ comme source de vérité
    if not payload["history"]:
        folder_hist = load_history_from_incidents()
        if folder_hist:
            payload["history"] = sorted(folder_hist, key=lambda h: h.get("time",""))
            with history_lock:
                history.clear()
                history.extend(payload["history"][-MAX_HISTORY:])
            log.info(f"[push_status] History restaurée depuis incidents/ : {len(payload['history'])} entrées")

    content = json.dumps(payload, ensure_ascii=False, indent=2)
    for attempt in range(retry):
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
            return
        except Exception as e:
            log.error(f"[GitHub] Erreur push (tentative {attempt+1}/{retry}) : {e}")
            time.sleep(5)
    send_teams_alert_raw("🚨 ERREUR CRITIQUE : impossible de pusher status.json sur GitHub après 3 tentatives. Le dashboard ne reflète plus la réalité.")

# Points envoyés via SSE/Render : 2h de données (720 pts à 10s)
# Le reste est dans GitHub chart_data.json — chargé au démarrage du browser
SSE_CHART_POINTS = 720  # 2h

def build_payload(statuses, now):
    with history_lock:
        hist_snapshot = list(history[-MAX_HISTORY:])
    return {
        "updated_at": now,
        "statuses": statuses,
        "history": hist_snapshot,
        "chart_data": {k: v[-SSE_CHART_POINTS:] for k, v in chart_data.items()},
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
        now = datetime.now(TZ_PARIS).strftime("%d/%m/%Y %H:%M:%S")
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
        timestamp = datetime.now(TZ_PARIS).strftime("%Y%m%d_%H%M%S")
        safe = lambda s: s.replace(" ", "_").replace("/", "_")
        filename = f"screenshots/{safe(brand)}_{safe(page)}_{timestamp}.png"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote",
                "--single-process",
                "--disable-extensions",
                "--disable-images",
                "--memory-pressure-off",
                "--js-flags=--max-old-space-size=128",
            ])
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


# ── NORMALISATION DES LABELS D'INCIDENT ──
def get_incident_level(reason: str, error_type: str = None) -> str:
    """Retourne le niveau d'incident : KO, DÉGRADÉ, INACCESSIBLE."""
    r = (reason or "").lower()
    et = (error_type or "").lower()
    # Erreurs serveur = KO critique
    if any(x in r for x in ["500","502","503","504","erreur serveur","service indisponible"]):
        return "KO"
    if any(x in r for x in ["404","403","400","401"]):
        return "KO"
    # TIMEOUT = site répond mais trop lentement (Playwright arrive à charger) = DÉGRADÉ
    if "timeout" in r or "pas de réponse" in r or "very_slow" in et or "lente" in r or "slow" in et:
        return "DÉGRADÉ"
    # DNS/TCP = vraiment inaccessible
    if "dns" in r or "dns" in et or "tcp" in et:
        return "INACCESSIBLE"
    if "inaccessible" in r:
        return "INACCESSIBLE"
    return "KO"

def normalize_reason(reason: str, error_type: str = None) -> str:
    """Convertit les raisons techniques en labels lisibles."""
    if not reason:
        return "Erreur inconnue"
    r = reason.lower()
    if "timeout" in r or "pas de réponse" in r:
        return "Réponse trop lente — timeout après 8s"
    if "500" in r or "erreur serveur interne" in r:
        return "Erreur serveur interne (500)"
    if "502" in r: return "Passerelle incorrecte (502)"
    if "503" in r: return "Service indisponible (503)"
    if "504" in r: return "Délai passerelle dépassé (504)"
    if "403" in r or "waf" in r: return "Accès refusé (403)"
    if "404" in r: return "Page introuvable (404)"
    if "dns" in r: return "Erreur DNS"
    if "très lente" in r or "slow" in r: return "Site dégradé — réponse lente"
    if "immat" in r or "décodage" in r: return "Formulaire estimation inaccessible"
    if "retour en ligne" in r or "rétabli" in r: return "Rétabli"
    if "redirect" in r: return "Redirection incorrecte"
    return reason

def send_teams_alert(brand, page, url, reason, is_recovery=False, details=None, screenshot_url=None):
    now_str = datetime.now(TZ_PARIS).strftime("%d/%m/%Y %H:%M:%S")
    if is_recovery:
        emoji = "✅"
        level = "RÉTABLI"
        label = "Retour en ligne"
    else:
        level = get_incident_level(reason, details.get("error_type") if details else None)
        label = normalize_reason(reason, details.get("error_type") if details else None)
        emoji = "🚨" if level == "KO" else "🔴" if level == "INACCESSIBLE" else "⚠️"
    title = f"{emoji} {brand} — {page} · {level}"

    # Stats 24h pour enrichir la card
    now_paris = datetime.now(TZ_PARIS)
    cutoff_24h = now_paris.timestamp() - 86400
    inc_today = [h for h in history if h.get("brand") == brand and h.get("page") == page
                 and h.get("type") == "ko"]
    # Compter les incidents des dernières 24h
    inc_24h = 0
    for h in inc_today:
        try:
            t = datetime.strptime(h["time"], "%d/%m/%Y %H:%M:%S").replace(tzinfo=TZ_PARIS)
            if t.timestamp() >= cutoff_24h:
                inc_24h += 1
        except: pass
    # Uptime approximatif depuis chart_data
    key = f"{brand}:{page}"
    pts = chart_data.get(key, [])
    pts_24h = []
    for p in pts:
        try:
            t = datetime.strptime(p["time"], "%d/%m/%Y %H:%M:%S").replace(tzinfo=TZ_PARIS)
            if t.timestamp() >= cutoff_24h:
                pts_24h.append(p)
        except: pass
    uptime_str = "—"
    if pts_24h:
        ok_pts = len([p for p in pts_24h if p.get("elapsed", 0) < 8])
        uptime_str = f"{round(ok_pts/len(pts_24h)*100, 1)}%"

    lines = [
        f"🌐 **URL** : {url}",
        f"⚠️ **Statut** : {label}",
        f"🕐 **Heure** : {now_str}",
        f"📊 **Incidents 24h** : {inc_24h} · **Uptime** : {uptime_str}",
    ]

    if details and not is_recovery:
        elapsed_total = details.get("elapsed_total") or details.get("elapsed_http")
        lines.append("")
        lines.append("**── Diagnostic ──**")
        lines.append(f"🔴 **Type** : {details.get('error_type', '—')}")
        if elapsed_total:
            lines.append(f"⏱ **Temps de réponse** : {elapsed_total}s")
        lines.append(f"🔍 **IP** : {details.get('ip', '—')}")
        lines.append(f"⏱ **DNS** : {details.get('dns_elapsed', '—')}s")
        if details.get("elapsed_http") is not None:
            lines.append(f"⏱ **HTTP** : {details.get('elapsed_http')}s")
        if details.get("http_status"):
            lines.append(f"📡 **Status HTTP** : {details.get('http_status')}")
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
    """Vérifie une URL avec requests + headers Chrome (bypass WAF léger)."""
    import urllib3
    urllib3.disable_warnings()
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }
    t0 = time.time()
    details = {"brand": brand, "page": page}
    try:
        session = requests.Session()
        session.headers.update(headers)
        brand_timeout = BRAND_TIMEOUT.get(brand, DEFAULT_TIMEOUT)
        if brand in BRAND_TIMEOUT:
            log.info(f"[{brand}] Timeout personnalisé: {brand_timeout}s")
        r = session.get(url, timeout=brand_timeout, verify=False, allow_redirects=True)
        elapsed = round(time.time() - t0, 2)
        details["http_status"] = r.status_code
        details["elapsed_http"] = elapsed
        details["ip"] = resolve_dns(url.split("/")[2])

        body = r.text[:500].lower()
        ACCESS_DENIED = ["access denied", "403 forbidden", "cloudflare", "just a moment", "enable javascript"]
        if any(k in body for k in ACCESS_DENIED):
            details["error_type"] = "WAF_BLOCK"
            details["body_preview"] = r.text[:200]
            return False, f"Bloqué WAF ({r.status_code})", elapsed, details

        if r.status_code >= 400:
            details["error_type"] = f"HTTP_{r.status_code}"
            return False, f"HTTP {r.status_code}", elapsed, details

        very_slow_threshold = BRAND_TIMEOUT.get(brand, VERY_SLOW_THRESHOLD_SECONDS)
        if elapsed > very_slow_threshold:
            details["error_type"] = "VERY_SLOW"
            return False, f"Très lent ({elapsed}s)", elapsed, details

        return True, f"OK ({r.status_code}) en {elapsed}s", elapsed, details

    except requests.exceptions.ConnectTimeout:
        elapsed = round(time.time() - t0, 2)
        details["error_type"] = "TCP_TIMEOUT"
        return False, "Pas de réponse après 8s (TIMEOUT)", elapsed, details
    except requests.exceptions.ConnectionError as e:
        elapsed = round(time.time() - t0, 2)
        err = str(e)
        if "NameOrServiceNotKnown" in err or "nodename nor servname" in err or "Name or service" in err:
            details["error_type"] = "DNS_FAILURE"
            return False, f"Erreur DNS : {err[:80]}", elapsed, details
        details["error_type"] = "CONNECTION_ERROR"
        return False, f"Erreur connexion : {err[:80]}", elapsed, details
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        details["error_type"] = "UNKNOWN"
        return False, f"Erreur : {str(e)[:80]}", elapsed, details

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
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
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

FR_BRANDS = set()  # Check immat FR désactivé — cause blacklisting IP

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
            browser = p.chromium.launch(headless=True, args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote",
                "--single-process",
                "--disable-extensions",
                "--disable-images",
                "--memory-pressure-off",
                "--js-flags=--max-old-space-size=128",
            ])
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            pg = ctx.new_page()

            # 1. Charger la homepage
            pg.goto(homepage_url, timeout=15000, wait_until="domcontentloaded")
            pg.wait_for_timeout(2000)

            # 2. Fermer la CMP — plusieurs tentatives avec différents sélecteurs
            STLA_CMP_BRANDS = {"AlfaRomeo FR", "Fiat FR", "FiatPro FR", "Jeep FR", "Abarth FR", "Lancia FR"}
            try:
                if brand in STLA_CMP_BRANDS:
                    cmp = pg.locator("button#acceptAllBtn")
                else:
                    # PSA — essayer plusieurs sélecteurs
                    for selector in [
                        "a#_psaihm_continue_without_accepting",
                        "button#_psaihm_continue_without_accepting",
                        "#didomi-notice-disagree-button",
                        "button[id*='refuse']",
                        "button[id*='decline']",
                        "button[id*='reject']",
                        "#onetrust-reject-all-handler",
                    ]:
                        try:
                            cmp = pg.locator(selector)
                            cmp.wait_for(timeout=2000, state="visible")
                            cmp.click()
                            pg.wait_for_timeout(1500)
                            log.info(f"[{brand}][Immat] CMP fermée via {selector}")
                            break
                        except Exception:
                            continue
                    else:
                        raise Exception("Aucun sélecteur CMP trouvé")
                if brand in STLA_CMP_BRANDS:
                    cmp.wait_for(timeout=5000, state="visible")
                    cmp.click()
                    pg.wait_for_timeout(1500)
                    log.info(f"[{brand}][Immat] CMP fermée")
            except Exception:
                # Forcer la fermeture via JS si les sélecteurs échouent
                try:
                    pg.evaluate("document.querySelector('[id*=\"cookie\"], [id*=\"consent\"], [id*=\"banner\"], [class*=\"cookie\"]')?.remove()")
                    pg.evaluate("document.querySelector('#didomi-popup, #onetrust-banner-sdk, .cmp-root')?.remove()")
                    pg.wait_for_timeout(500)
                    log.info(f"[{brand}][Immat] CMP supprimée via JS")
                except Exception:
                    pass

            # 3. Saisir l'immat
            pg.wait_for_selector("#registration", timeout=10000)
            pg.fill("#registration", IMMAT_FR)
            pg.wait_for_timeout(500)

            # 4. Cliquer le bouton d'estimation — force=True pour bypasser les overlays
            try:
                pg.locator("#js-submit-plate").click(timeout=8000, force=True)
            except Exception:
                # Fallback via JavaScript
                pg.evaluate("document.querySelector('#js-submit-plate')?.click()")
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
    token = os.environ.get("GITHUB_TOKEN", "")
    log.info(f"GITHUB_TOKEN présent: {'OUI' if token else 'NON — PUSH DÉSACTIVÉ'}")
    init_github()
    log.info("═" * 60)
    log.info("  STLA Monitor V2 démarré")
    for brand, urls in BRANDS.items():
        log.info(f"  {brand} : {', '.join(urls.keys())}")
    log.info(f"  Intervalle : {CHECK_INTERVAL_SECONDS}s")
    log.info("═" * 60)

    while True:
        try:
            statuses = {}
            now = datetime.now(TZ_PARIS).strftime("%d/%m/%Y %H:%M:%S")
            now_short = datetime.now(TZ_PARIS).strftime("%H:%M:%S")
    
            # Construire la liste de toutes les tâches à exécuter
            # Charger les pauses depuis Supabase toutes les 5 cycles
            if not hasattr(get_paused_brands, '_cycle'):
                get_paused_brands._cycle = 0
            get_paused_brands._cycle += 1
            if get_paused_brands._cycle % 5 == 1:
                get_paused_brands._cache = get_paused_brands()
            _paused_brands = getattr(get_paused_brands, '_cache', {})

            # Ford FR PPR : plage horaire 08h-20h Paris
            _hour_paris = datetime.now(TZ_PARIS).hour
            _ppr_active = 8 <= _hour_paris < 20

            tasks = []
            for brand, urls in BRANDS.items():
                statuses[brand] = {}
                now_ts = datetime.now(TZ_PARIS).strftime("%d/%m/%Y %H:%M:%S")

                # Pause Supabase active ?
                if brand in _paused_brands:
                    until = _paused_brands[brand]
                    reason = "En pause" if until is None else f"En pause jusqu'à {until.strftime('%H:%M')}"
                    log.info(f"[Pause] {brand} — {reason}")
                    for page, url in urls.items():
                        statuses[brand][page] = {
                            "ok": True, "reason": reason, "elapsed": 0,
                            "checked_at": now_ts, "url": url, "details": {}
                        }
                    continue

                for page, url in urls.items():
                    # Ford FR PPR hors plage horaire
                    if brand == "Ford FR PPR" and not _ppr_active:
                        statuses[brand][page] = {
                            "ok": True, "reason": "Hors plage horaire (08h-20h)",
                            "elapsed": 0, "checked_at": now_ts, "url": url, "details": {}
                        }
                        continue
                    tasks.append((brand, page, url))
    
            def check_task(task):
                brand, page, url = task
                if brand in REFERENCE_BRANDS:
                    return brand, page, url, check_url_playwright(brand, page, url)
                else:
                    if brand in BRAND_TIMEOUT:
                        log.info(f"[{brand}] check_url avec timeout {BRAND_TIMEOUT[brand]}s")
                    return brand, page, url, check_url(brand, page, url)
    
            # Exécuter en parallèle — max 10 workers simultanés
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(check_task, t): t for t in tasks}
                for future in as_completed(futures, timeout=120):
                    try:
                        brand, page, url, (ok, reason, elapsed, details) = future.result(timeout=20)
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
                                inc = {"time": now, "brand": brand, "page": page,
                                    "type": "recovery", "detail": "Retour en ligne",
                                    "is_reference": brand in REFERENCE_BRANDS}
                                with history_lock: history.append(inc)
                                threading.Thread(target=archive_incident, args=(inc,), daemon=True).start()
                                threading.Thread(target=supabase_insert, args=(inc,), daemon=True).start()
                                if brand not in REFERENCE_BRANDS:
                                    send_teams_alert(brand, page, url, reason, is_recovery=True, details=details)
                        else:
                            if not incident_active.get(key):
                                incident_active[key] = True
                                screenshot_url = None
                                if brand not in REFERENCE_BRANDS:
                                    screenshot_url = take_screenshot(brand, page, url)
                                    send_teams_alert(brand, page, url, reason, details=details, screenshot_url=screenshot_url)
                                inc = {"time": now, "brand": brand, "page": page,
                                    "type": "ko", "detail": reason, "diagnostics": details,
                                    "screenshot": screenshot_url,
                                    "is_reference": brand in REFERENCE_BRANDS}
                                with history_lock: history.append(inc)
                                threading.Thread(target=archive_incident, args=(inc,), daemon=True).start()
                                threading.Thread(target=supabase_insert, args=(inc,), daemon=True).start()
                    except TimeoutError:
                        task = futures[future]
                        brand, page, url = task
                        log.error(f"[{brand}][{page}] TIMEOUT — check bloqué >20s, marqué KO")
                        key = f"{brand}:{page}"
                        now_t = datetime.now(TZ_PARIS).strftime("%d/%m/%Y %H:%M:%S")
                        chart_data[key].append({"time": now_t, "elapsed": 8.0})
                        if len(chart_data[key]) > MAX_CHART:
                            chart_data[key].pop(0)
                        if not incident_active.get(key):
                            incident_active[key] = True
                            inc = {"time": now_t, "brand": brand, "page": page,
                                   "type": "ko", "detail": "Timeout interne >20s"}
                            with history_lock: history.append(inc)
                            threading.Thread(target=archive_incident, args=(inc,), daemon=True).start()
                    except Exception as e:
                        log.error(f"Erreur task : {e}")
    
            push_status(statuses)
            threading.Thread(target=push_to_render, args=(statuses,), daemon=True).start()
            # Backup chart_data toutes les 20 cycles (~60min)
            _cycle_counter[0] = _cycle_counter[0] + 1
            if _cycle_counter[0] % 5 == 0:
                threading.Thread(target=push_chart_backup, daemon=True).start()
            time.sleep(CHECK_INTERVAL_SECONDS)
        except Exception as _cycle_err:
            log.error(f"[Cycle] Erreur non catchée — script continue : {_cycle_err}")

# ── WATCHDOG — Surveillance du Web Service Render ──
_watchdog_failures = [0]
_watchdog_down = [False]

def watchdog_loop():
    """Ping le Web Service toutes les 5 min — alerte Teams si KO."""
    RENDER_CHECK_URL = "https://stla-monitor.onrender.com/"
    CHECK_EVERY = 300   # 5 minutes
    MAX_FAIL    = 2     # alerter après 2 échecs consécutifs

    time.sleep(30)  # attendre que tout soit bien démarré
    log.info("[Watchdog] Démarré — surveillance du Web Service toutes les 5 min")

    while True:
        try:
            r = requests.head(RENDER_CHECK_URL, timeout=15, verify=False)
            ok = r.status_code in (200, 204, 301, 302)
        except Exception as e:
            ok = False

        if ok:
            if _watchdog_down[0]:
                _watchdog_down[0] = False
                _watchdog_failures[0] = 0
                send_teams_alert_raw(
                    "✅ UAS Monitoring — Web Service de nouveau en ligne\n"
                    f"Le serveur Render répond correctement.\n"
                    f"🕐 {datetime.now(TZ_PARIS).strftime('%d/%m/%Y %H:%M:%S')}"
                )
                log.info("[Watchdog] Recovery — service en ligne")
            else:
                _watchdog_failures[0] = 0
                log.info("[Watchdog] OK")
        else:
            _watchdog_failures[0] += 1
            log.warning(f"[Watchdog] Échec {_watchdog_failures[0]}/{MAX_FAIL}")
            if _watchdog_failures[0] >= MAX_FAIL and not _watchdog_down[0]:
                _watchdog_down[0] = True
                send_teams_alert_raw(
                    f"🚨 UAS Monitoring — Web Service KO\n"
                    f"Le serveur Render ne répond plus après {_watchdog_failures[0]} tentatives.\n"
                    f"URL : {RENDER_CHECK_URL}\n"
                    f"🕐 {datetime.now(TZ_PARIS).strftime('%d/%m/%Y %H:%M:%S')}\n"
                    f"Vérifiez les logs Render immédiatement."
                )

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    try:
        # Lancer le watchdog dans un thread séparé
        threading.Thread(target=watchdog_loop, daemon=True).start()
        run()
    except KeyboardInterrupt:
        log.info("Monitoring arrêté.")
