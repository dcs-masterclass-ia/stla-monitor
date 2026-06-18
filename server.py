"""
STLA Monitor — Serveur WebSocket temps réel
- Reçoit les données du script Python
- Broadcast instantané vers tous les dashboards connectés
- Hébergé sur Render.com
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# ÉTAT GLOBAL
# ─────────────────────────────────────────────

latest_status = {}
connected_dashboards = set()

# ─────────────────────────────────────────────
# WEBSOCKET — Dashboard clients
# ─────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_dashboards.add(websocket)
    log.info(f"[WS] Dashboard connecté — {len(connected_dashboards)} client(s)")

    try:
        # Envoyer l'état actuel immédiatement à la connexion
        if latest_status:
            await websocket.send_json(latest_status)

        # Garder la connexion ouverte
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        connected_dashboards.discard(websocket)
        log.info(f"[WS] Dashboard déconnecté — {len(connected_dashboards)} client(s)")
    except Exception as e:
        connected_dashboards.discard(websocket)
        log.error(f"[WS] Erreur : {e}")

# ─────────────────────────────────────────────
# HTTP POST — Script Python envoie les données
# ─────────────────────────────────────────────

@app.post("/update")
async def receive_update(request: Request):
    global latest_status
    try:
        data = await request.json()
        latest_status = data
        latest_status["server_time"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        # Broadcast à tous les dashboards connectés
        dead = set()
        for ws in connected_dashboards:
            try:
                await ws.send_json(latest_status)
            except Exception:
                dead.add(ws)
        connected_dashboards.difference_update(dead)

        log.info(f"[Update] Données reçues et broadcastées à {len(connected_dashboards)} client(s)")
        return {"ok": True, "clients": len(connected_dashboards)}

    except Exception as e:
        log.error(f"[Update] Erreur : {e}")
        return {"ok": False, "error": str(e)}

@app.get("/status")
async def get_status():
    return {
        "ok": True,
        "clients": len(connected_dashboards),
        "last_update": latest_status.get("server_time", "—"),
        "brands": list(latest_status.get("statuses", {}).keys())
    }

@app.get("/")
async def root():
    return {"service": "STLA Monitor WebSocket Server", "status": "running"}

# ─────────────────────────────────────────────
# LANCEMENT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
