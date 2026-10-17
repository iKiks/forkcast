"""Forkcast API and live stream.

Run:  uvicorn forkcast.server:app --reload    then open http://127.0.0.1:8000
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, llm
from .agents import Newsroom, pundit_duel
from .analysis import MatchContext
from .bus import BUS
from .forecast import story
from .tracking import HALFTIME_GAP
from .engine import KICKOFF_ZONE, N_LATERAL, PROGRESS_EDGES
from .i18n import LANGS
from .world import CLUBS, FORMATION_433, LEAGUE_NAME

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

app = FastAPI(title="Forkcast", version=__version__,
              description="Explainable match intelligence, proven by re-simulation. Synthetic data only.")
app.mount("/static", StaticFiles(directory=WEB), name="static")

_matches: "OrderedDict[str, MatchContext]" = OrderedDict()
_sessions: dict[str, dict] = {}
_recaps: dict[str, Newsroom] = {}


def get_ctx(home: str, away: str, seed: int) -> MatchContext:
    if home not in CLUBS or away not in CLUBS or home == away:
        raise HTTPException(400, "Pick two different clubs.")
    key = f"{home}-{away}-{seed}"
    if key in _matches:
        _matches.move_to_end(key)
        return _matches[key]
    ctx = MatchContext(home, away, seed)
    _matches[key] = ctx
    while len(_matches) > 12:
        _matches.popitem(last=False)
    return ctx


def offline_newsroom(ctx: MatchContext) -> Newsroom:
    if ctx.match_id not in _recaps:
        nr = Newsroom(ctx, lambda m: None, use_llm=False)
        for i in range(len(ctx.events)):
            nr.process(i)
        _recaps[ctx.match_id] = nr
    return _recaps[ctx.match_id]


def meta_payload(ctx: MatchContext) -> dict:
    m = ctx.match
    pre = ctx.fe.outlook(0.0, 1, [0, 0], 0, KICKOFF_ZONE)
    return {
        "type": "meta", "version": __version__, "league": LEAGUE_NAME, "match_id": m.match_id, "seed": m.seed,
        "home": m.home.to_dict(), "away": m.away.to_dict(), "pitch": {"length": 105, "width": 68},
        "formation": FORMATION_433, "zones": {"progress_edges": PROGRESS_EDGES, "lateral": N_LATERAL},
        "langs": LANGS, "prematch": pre, "model": "foundry" if llm.enabled() else "templates", "bus": BUS.kind,
        "chain": {"dt": ctx.fe.m.dt, "fitted_on_matches": ctx.fe.m.n_matches, "steps": ctx.fe.S},
        "timeline": {"p1_end": ctx.tracking.p2_start - HALFTIME_GAP, "p2_start": ctx.tracking.p2_start,
                     "end": ctx.events[-1]["T"]},
        "slots": ctx.tracking.initial_slots,
        "prematch_story": story(pre, [0, 0], m.home, m.away)[0],
    }


def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, separators=(',', ':'))}\n\n"


# ---------------------------------------------------------------------- pages
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "version": __version__, "model": "foundry" if llm.enabled() else "templates", "bus": BUS.kind}


@app.get("/api/clubs")
def clubs():
    return {"league": LEAGUE_NAME, "clubs": [c.to_dict() for c in CLUBS.values()]}


@app.get("/api/validation")
def validation():
    f = ROOT / "docs" / "validation.json"
    if not f.exists():
        raise HTTPException(404, "Run python -m scripts.validate first.")
    return JSONResponse(json.loads(f.read_text()))


# ---------------------------------------------------------------------- live stream
@app.get("/api/live")
async def live(home: str = "kes", away: str = "amb", seed: int = 42, speed: float = Query(15.0, ge=1, le=400),
               skip: float = Query(0.0, ge=0, le=95)):
    """Server-sent events: the live pipeline (ingest -> interpret -> agents -> cues)."""
    ctx = await asyncio.to_thread(get_ctx, home, away, seed)
    sid = secrets.token_hex(6)
    _sessions[sid] = {"paused": False, "speed": speed}

    async def gen():
        out: list[dict] = []
        nr = Newsroom(ctx, out.append)
        tr = ctx.tracking
        events = ctx.events
        n = len(events)
        meta = meta_payload(ctx)
        meta["session"] = sid
        yield sse(meta)
        skip_T = skip * 60 if skip <= 45 else tr.p2_start + (skip * 60 - 2700)
        T, end_T = 0.0, events[-1]["T"] + 1.0
        ei, done = 0, -1
        last_minute, last_score, last_stats = -1, [0, 0], -1e9
        try:
            while T < end_T:
                sess = _sessions.get(sid)
                if sess is None:
                    break
                while sess["paused"]:
                    await asyncio.sleep(0.1)
                tick = max(1.0, sess["speed"] / 30.0)  # at most ~30 messages a second, whatever the speed
                fast = T + tick <= skip_T
                if not fast:
                    await asyncio.sleep(tick / sess["speed"])
                T1 = min(end_T, T + tick)
                batch = []
                while ei < n and events[ei]["T"] <= T1:
                    ev = events[ei]
                    batch.append(ev)
                    yield sse({**ev, "type": "event", "type_": ev["type"]})
                    if ei - 1 > done:
                        await asyncio.to_thread(nr.process, ei - 1)
                        done = ei - 1
                    if ev["type"] == "shot" and ev["outcome"] == "goal":
                        await asyncio.to_thread(nr.process, ei)  # goals need no lookahead: air them instantly
                        done = ei
                    for msg in out:
                        if fast:
                            msg["catchup"] = True  # skipped minutes: log it, don't flash it on screen
                        yield sse(msg)
                    out.clear()
                    st = ev["state"]
                    minute = int(ev["T"] // 60)
                    if minute != last_minute or st["score"] != last_score:
                        last_minute, last_score = minute, list(st["score"])
                        o = ctx.fe.outlook_from_state(st, ev["period"])
                        texts, fv = story(o, st["score"], ctx.match.home, ctx.match.away)
                        yield sse({"type": "outlook", "t": ev["t"], "T": ev["T"], "period": ev["period"],
                                   "clock": ev["clock"], "event_id": ev["event_id"], "score": st["score"], **o,
                                   "story": texts, "variant": fv["variant"]})
                    ei += 1
                if batch:
                    await asyncio.to_thread(BUS.publish, batch)
                if not fast:
                    ch = tr.chunk(T, T1)
                    if ch:
                        yield sse({"type": "track", **ch})
                if T1 - last_stats >= 15:
                    last_stats = T1
                    yield sse({"type": "stats", "T": T1, **nr.interp.snapshot(), "ops": nr.ops(),
                               "physical": nr.physical(T1)})
                T = T1
            if done < n - 1:
                await asyncio.to_thread(nr.process, n - 1)
            for msg in out:
                yield sse(msg)
            out.clear()
            _recaps[ctx.match_id] = nr
            yield sse({"type": "stats", "T": end_T, **nr.interp.snapshot(), "ops": nr.ops(),
                       "physical": nr.physical(end_T)})
            yield sse({"type": "recap", "T": end_T, **nr.recap("en")})
            yield sse({"type": "end", "T": end_T})
        finally:
            _sessions.pop(sid, None)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class Control(BaseModel):
    session: str
    paused: bool | None = None
    speed: float | None = None


@app.post("/api/control")
def control(c: Control):
    s = _sessions.get(c.session)
    if not s:
        raise HTTPException(404, "Session ended.")
    if c.paused is not None:
        s["paused"] = c.paused
    if c.speed is not None:
        s["speed"] = max(1.0, min(400.0, c.speed))
    return s


# ---------------------------------------------------------------------- moment tools
@app.get("/api/impact")
async def impact(home: str, away: str, seed: int, event_id: str, n: int = Query(1000, ge=0, le=5000)):
    ctx = await asyncio.to_thread(get_ctx, home, away, seed)
    if event_id not in ctx.by_id:
        raise HTTPException(404, "Unknown event.")
    t0 = time.perf_counter()
    res = await asyncio.to_thread(ctx.impact, event_id, n)
    res["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return res


class Play(BaseModel):
    home: str
    away: str
    seed: int
    event_id: str
    x: float | None = None
    y: float | None = None


@app.post("/api/play")
async def play(p: Play):
    """Play the Moment: the viewer's own pass, replayed through 2,000 futures."""
    ctx = await asyncio.to_thread(get_ctx, p.home, p.away, p.seed)
    if p.event_id not in ctx.by_id:
        raise HTTPException(404, "Unknown event.")
    t0 = time.perf_counter()
    try:
        res = await asyncio.to_thread(ctx.counterfactual, p.event_id, p.x, p.y)
    except ValueError as e:
        raise HTTPException(400, str(e))
    res["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return res


@app.get("/api/duel")
async def duel(home: str, away: str, seed: int, event_id: str):
    ctx = await asyncio.to_thread(get_ctx, home, away, seed)
    if event_id not in ctx.by_id:
        raise HTTPException(404, "Unknown event.")
    try:
        return await asyncio.to_thread(pundit_duel, ctx, event_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/recap")
async def recap(home: str, away: str, seed: int, lang: str = "en"):
    if lang not in LANGS:
        raise HTTPException(400, f"lang must be one of {list(LANGS)}")
    ctx = await asyncio.to_thread(get_ctx, home, away, seed)
    nr = await asyncio.to_thread(offline_newsroom, ctx)
    return nr.recap(lang)


@app.get("/api/match")
async def match(home: str, away: str, seed: int, events: bool = False):
    ctx = await asyncio.to_thread(get_ctx, home, away, seed)
    out = meta_payload(ctx)
    if events:
        out["events"] = ctx.events
    return out
