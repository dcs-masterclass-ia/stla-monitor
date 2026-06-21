"""
STLA Monitor — Serveur HTTP temps réel
"""

import os
import json
import base64
import logging
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = "dcs-masterclass-ia/stla-monitor"
GITHUB_RAW   = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/status.json"

latest_data = {}

def load_from_github():
    global latest_data
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        req = urllib.request.Request(GITHUB_RAW, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            latest_data = json.loads(r.read())
            latest_data["server_time"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        pts = sum(len(v) for v in latest_data.get("chart_data", {}).values())
        hist = len(latest_data.get("history", []))
        log.info(f"[Startup] GitHub chargé : {hist} incidents, {pts} points")
    except Exception as e:
        log.error(f"[Startup] Erreur : {e}")

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

@app.post("/update")
async def receive_update(request: Request):
    global latest_data
    try:
        latest_data = await request.json()
        latest_data["server_time"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/status")
async def get_status():
    return latest_data if latest_data else {"error": "Pas encore de données"}

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
    return {"service": "STLA Monitor", "status": "running"}

@app.head("/")
async def root_head():
    return Response(status_code=200)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
