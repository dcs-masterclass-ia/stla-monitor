"""
STLA Monitor — Serveur HTTP temps réel
- Reçoit les données du script Python toutes les 10s
- Sert les données au dashboard sans cache
- Le ping régulier du script empêche la mise en veille Render
"""

import os
import json
import logging
from datetime import datetime
from fastapi import FastAPI, Request
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

# État en mémoire
latest_data = {}

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

@app.get("/")
async def root():
    return {"service": "STLA Monitor", "status": "running"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
