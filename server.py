"""
STLA Monitor — Serveur HTTP temps réel avec Server-Sent Events
"""

import os
import json
import base64
import asyncio
import logging
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = "dcs-masterclass-ia/stla-monitor"
GITHUB_RAW   = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/status.json"

latest_data = {}

# SSE — liste des queues clients connectés
sse_clients: list[asyncio.Queue] = []

def notify_clients():
    """Notifie tous les clients SSE connectés qu'il y a une nouvelle update."""
    dead = []
    for q in sse_clients:
        try:
            q.put_nowait("update")
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        sse_clients.remove(q)

def merge_chart_data(old_cd: dict, new_cd: dict, max_pts: int = 10080) -> dict:
    """Merge deux chart_data en dédupliquant par time."""
    merged = {}
    for key in set(list(old_cd.keys()) + list(new_cd.keys())):
        seen = set()
        all_pts = []
        for p in (old_cd.get(key, []) + new_cd.get(key, [])):
            if p["time"] not in seen:
                seen.add(p["time"])
                all_pts.append(p)
        all_pts.sort(key=lambda p: p["time"])
        merged[key] = all_pts[-max_pts:]
    return merged

def load_from_github():
    global latest_data
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

        # Charger status.json
        req = urllib.request.Request(GITHUB_RAW, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            latest_data = json.loads(r.read())
            latest_data["server_time"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        # Si history vide, charger depuis incidents/
        if not latest_data.get("history"):
            latest_data["history"] = load_incidents_from_folder()

        # Charger chart_data.json (backup complet) et merger
        try:
            cd_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/chart_data.json"
            req2 = urllib.request.Request(cd_url, headers=headers)
            with urllib.request.urlopen(req2, timeout=15) as r2:
                backup = json.loads(r2.read())
            merged = merge_chart_data(
                backup.get("chart_data", {}),
                latest_data.get("chart_data", {})
            )
            latest_data["chart_data"] = merged
            total = sum(len(v) for v in merged.values())
            log.info(f"[Startup] chart_data fusionné : {total} points")
        except Exception as e:
            log.error(f"[Startup] Erreur chart_data.json : {e}")

        pts = sum(len(v) for v in latest_data.get("chart_data", {}).values())
        hist = len(latest_data.get("history", []))
        log.info(f"[Startup] Prêt : {hist} incidents, {pts} points chart")
    except Exception as e:
        log.error(f"[Startup] Erreur : {e}")

def load_incidents_from_folder():
    all_incidents = []
    try:
        from datetime import timedelta
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        today = datetime.now()
        for i in range(7):
            date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            try:
                api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/incidents/{date}"
                req = urllib.request.Request(api_url, headers={**headers, "Accept": "application/vnd.github.v3+json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    files = json.loads(r.read())
                for f in files:
                    raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/incidents/{date}/{f['name']}"
                    req2 = urllib.request.Request(raw_url, headers=headers)
                    with urllib.request.urlopen(req2, timeout=10) as r2:
                        all_incidents.extend(json.loads(r2.read()))
            except Exception:
                pass
        all_incidents.sort(key=lambda h: h.get("time", ""))
        log.info(f"[Startup] incidents/ : {len(all_incidents)} incidents")
    except Exception as e:
        log.error(f"[Startup] Erreur incidents/ : {e}")
    return all_incidents

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_from_github()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── SSE STREAM ──
@app.get("/stream")
async def stream(request: Request):
    """Server-Sent Events — pousse les updates en temps réel aux clients."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    sse_clients.append(queue)
    log.info(f"[SSE] Client connecté ({len(sse_clients)} total)")

    async def event_generator():
        try:
            # Envoyer immédiatement les données actuelles
            data_str = json.dumps(latest_data, ensure_ascii=False)
            yield f"data: {data_str}\n\n"

            while True:
                # Attendre une notification ou envoyer un heartbeat toutes les 30s
                try:
                    await asyncio.wait_for(queue.get(), timeout=30)
                    if await request.is_disconnected():
                        break
                    data_str = json.dumps(latest_data, ensure_ascii=False)
                    yield f"data: {data_str}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat pour garder la connexion ouverte
                    yield ": heartbeat\n\n"
        except Exception:
            pass
        finally:
            if queue in sse_clients:
                sse_clients.remove(queue)
            log.info(f"[SSE] Client déconnecté ({len(sse_clients)} restants)")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

# ── UPDATE ──
@app.post("/update")
async def receive_update(request: Request):
    global latest_data
    try:
        new_data = await request.json()
        new_data["server_time"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        # Merger chart_data en mémoire
        if latest_data and latest_data.get("chart_data") and new_data.get("chart_data"):
            new_data["chart_data"] = merge_chart_data(
                latest_data["chart_data"],
                new_data["chart_data"]
            )

        # Merger history — garder tout, dédupliquer
        if latest_data and latest_data.get("history") and new_data.get("history"):
            seen = set()
            merged_hist = []
            for h in (latest_data["history"] + new_data["history"]):
                key = f"{h.get('time')}|{h.get('brand')}|{h.get('page')}|{h.get('type')}"
                if key not in seen:
                    seen.add(key)
                    merged_hist.append(h)
            merged_hist.sort(key=lambda h: h.get("time", ""))
            new_data["history"] = merged_hist

        latest_data = new_data

        # Notifier tous les clients SSE
        notify_clients()

        pts = sum(len(v) for v in latest_data.get("chart_data", {}).values())
        log.info(f"[Update] Reçu — {pts} pts chart, {len(latest_data.get('history',[]))} incidents, {len(sse_clients)} clients notifiés")
        return {"ok": True, "clients": len(sse_clients)}
    except Exception as e:
        log.error(f"[Update] Erreur : {e}")
        return {"ok": False, "error": str(e)}

# ── STATUS (fallback HTTP) ──
@app.get("/status")
async def get_status():
    return latest_data if latest_data else {"error": "Pas encore de données"}

# ── PUSH BRAND ──
@app.post("/push-brand")
async def push_brand(request: Request):
    if not GITHUB_TOKEN:
        return {"ok": False, "error": "GITHUB_TOKEN manquant"}
    try:
        body = await request.json()
        brand_name = body.get("brand")
        pages = body.get("pages", {})
        if not brand_name or not pages:
            return {"ok": False, "error": "brand et pages requis"}

        api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/stla_monitor.py"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        }
        req = urllib.request.Request(api, headers=headers)
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        sha = data["sha"]
        content = base64.b64decode(data["content"].replace("\n", "")).decode("utf-8")

        import re
        pages_str = json.dumps(pages, ensure_ascii=False)
        pattern = rf'("{re.escape(brand_name)}")\s*:\s*\{{[^}}]+\}}'
        replacement = f'"{brand_name}": {pages_str}'
        new_content, count = re.subn(pattern, replacement, content)

        if count == 0:
            return {"ok": False, "error": f"Brand '{brand_name}' non trouvée"}

        new_b64 = base64.b64encode(new_content.encode("utf-8")).decode()
        push_body = json.dumps({
            "message": f"update: URLs {brand_name} via admin",
            "content": new_b64, "sha": sha
        }).encode()
        req2 = urllib.request.Request(api, data=push_body, headers=headers, method="PUT")
        with urllib.request.urlopen(req2) as r2:
            resp = json.loads(r2.read())
            return {"ok": True, "commit": resp["commit"]["sha"][:8]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/")
async def root():
    return {"service": "STLA Monitor", "status": "running", "sse_clients": len(sse_clients)}

@app.head("/")
async def root_head():
    return Response(status_code=200)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
