"""FastAPI service over the engine/evaluator/classifier (brief §7).

Thin HTTP layer so the React UI (and any client) can list/fetch analyzed games,
analyze a new one on demand, and watch a fresh bot-vs-bot game. The heavy lifting
lives in the decoupled modules; this only marshals JSON.

Run:  uvicorn catan_review.api:app --reload
"""
from __future__ import annotations

import glob
import json
import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .engine import GameConfig, run_game
from .policy import REFERENCE
from .gamelog import GameLog
from .analyze import analyze_trajectory

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "games")

app = FastAPI(title="Catan Review", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    seed: int = 123
    players: int = 4
    n_before: int = 60
    n_alt: int = 45
    topk: int = 4
    max_decisions: Optional[int] = None


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/games")
def list_games():
    names = []
    for p in sorted(glob.glob(os.path.join(DATA_DIR, "*.review.json"))):
        names.append(os.path.basename(p)[: -len(".review.json")])
    return {"games": names}


@app.get("/api/games/{name}")
def get_game(name: str):
    path = os.path.join(DATA_DIR, f"{name}.review.json")
    if not os.path.exists(path):
        raise HTTPException(404, f"no analyzed game '{name}'")
    with open(path) as f:
        return json.load(f)


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    cfg = GameConfig(num_players=req.players, seed=req.seed)
    traj = run_game(cfg, REFERENCE)
    review = analyze_trajectory(
        traj, n_before=req.n_before, n_alt=req.n_alt, topk=req.topk,
        max_decisions=req.max_decisions,
    )
    return review


@app.post("/api/watch")
def watch(req: AnalyzeRequest):
    """Generate a bot-vs-bot game log (no analysis) for the watch mode."""
    cfg = GameConfig(num_players=req.players, seed=req.seed)
    traj = run_game(cfg, REFERENCE)
    return GameLog.from_trajectory(traj).to_json()


# Serve the built frontend if present (one-process production mode).
_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="web")
