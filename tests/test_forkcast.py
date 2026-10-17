import json
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from forkcast.agents import Newsroom, pundit_duel
from forkcast.analysis import MatchContext
from forkcast.engine import KICKOFF_ZONE, simulate
from forkcast.i18n import LANGS
from forkcast.server import app
from scripts.validate import run as validate_run


@pytest.fixture(scope="module")
def ctx():
    return MatchContext("kes", "amb", 42)


@pytest.fixture(scope="module")
def newsroom(ctx):
    msgs = []
    nr = Newsroom(ctx, msgs.append, use_llm=False)
    for i in range(len(ctx.events)):
        nr.process(i)
    nr.msgs = msgs
    return nr


# ---------------------------------------------------------------- engine
def test_engine_is_deterministic():
    a, b = simulate("kes", "amb", 7), simulate("kes", "amb", 7)
    assert a.events == b.events and a.score == b.score
    assert simulate("kes", "amb", 8).events != a.events


def test_event_schema():
    m = simulate("cal", "irn", 3)
    required = {"event_id", "match_id", "seq", "t", "clock", "period", "team", "type", "chain_id", "state"}
    for e in m.events:
        assert required <= e.keys()
        if e["x"] is not None:
            assert 0 <= e["x"] <= 105 and 0 <= e["y"] <= 68
    assert m.events[-1]["type"] == "full_time"
    assert [e["seq"] for e in m.events] == list(range(1, len(m.events) + 1))


def test_calibration_bands():
    res = validate_run(120)
    failing = [r for r in res["metrics"] if not r["pass"]]
    # small samples are noisy: allow at most one borderline metric
    assert len(failing) <= 1, failing


# ---------------------------------------------------------------- forks
def test_exact_distribution_is_normalised(ctx):
    fe = ctx.fe
    for s in (0, 10, 500, fe.S):
        assert np.allclose(fe.J[s].sum(axis=(-1, -2)), 1.0, atol=1e-3)
        assert np.all(fe.N[s].sum(-1) <= 1.0 + 1e-4)


def test_descriptive_forecast_is_consistent(ctx):
    o = ctx.fe.outlook(3000.0, 2, [2, 1], 1, KICKOFF_ZONE)
    assert abs(o["home_win"] + o["draw"] + o["away_win"] - 1) < 1e-3
    assert o["scorelines"][0]["p"] >= o["scorelines"][1]["p"]
    assert o["scorelines"][0]["score"][0] >= 2 and o["scorelines"][0]["score"][1] >= 1
    ng = o["next_goal"]
    assert abs(ng["home"] + ng["away"] + ng["none"] - 1) < 1e-3
    assert o["next_goal_10"]["none"] >= ng["none"]  # a goal within 10 minutes is no likelier than one at all


def test_tracking_is_physical(ctx):
    tr = ctx.tracking
    assert np.all(np.diff(tr.T) > 0)
    assert tr.speed.max() < 37.5  # km/h: no superhuman sprints
    km = tr.dist[-1] / 1000
    outfield = [s for s in range(22) if s % 11 != 0]
    assert 8.0 < float(np.median(km[outfield])) < 12.5
    slot = {pid: i for i, pid in enumerate(tr.initial_slots)}
    gaps = []
    for e in ctx.events:
        if e["type"] in ("pass", "carry", "cross", "shot") and e["player"] in slot and e["period"] == 1:
            f = tr.frame_at(e["T"])
            gaps.append(np.hypot(*(tr.pos[f, slot[e["player"]]] - np.array([e["x"], e["y"]]))))
    assert np.median(gaps) < 1.5  # the player on the ball is at the ball when he plays it
    ch = tr.chunk(100.0, 102.0)
    assert len(ch["T"]) == 10 and len(ch["pos"][0]) == 44


def test_monte_carlo_agrees_with_exact_solver(ctx):
    fe = ctx.fe
    exact = fe.outlook(0.0, 1, [0, 0], 0, KICKOFF_ZONE)
    mc = fe.sample(0.0, 1, [0, 0], 0, KICKOFF_ZONE, n=4000, seed=3)
    for k in ("home_win", "draw", "away_win"):
        assert abs(exact[k] - mc[k]) < 0.04


def test_goals_raise_the_scorers_outlook(ctx):
    for e in ctx.events:
        if e["type"] == "shot" and e["outcome"] == "goal":
            assert ctx.impact(e["event_id"])["delta_win"] > 0


def test_counterfactual_and_duel(ctx):
    ev = next(e for e in ctx.events if e["type"] == "pass" and e["period"] == 2)
    cf = ctx.counterfactual(ev["event_id"], 70.0, 30.0)
    assert 0 < cf["yours"]["success_prob"] < 1
    assert cf["yours"]["forks"]["n"] == 2000
    d = pundit_duel(ctx, ev["event_id"])
    assert d["winner"] in ("The Purist", "The Direct One")


# ---------------------------------------------------------------- agents
def test_newsroom_airs_goals_in_every_language(ctx, newsroom):
    goals = [e for e in ctx.events if e["type"] == "shot" and e["outcome"] == "goal"]
    aired = [c for c in newsroom.cues if c["kind"] == "goal"]
    assert len(aired) == len(goals)
    for c in newsroom.cues:
        assert set(c["text"]) == set(LANGS)
        for lang in LANGS:
            assert {"casual", "analyst"} <= c["text"][lang].keys()


def test_every_number_on_screen_is_evidence(newsroom):
    num = re.compile(r"\d+(?:[.,]\d+)?")
    for c in newsroom.cues:
        allowed = set()
        for v in c["values"].values():
            allowed.update(num.findall(str(v)))
        allowed |= {"1", "000", "100", "10"}
        for lang in LANGS:
            for text in c["text"][lang].values():
                body = re.sub(r"\[e\d{5}\]", "", text)
                assert set(num.findall(body)) <= allowed, (lang, text)


def test_skeptic_rejects_unsupported_claims(ctx, newsroom):
    ok, _ = newsroom.skeptic("Win chance 12% to 99%.", {"a": 12}, {"allow": []})
    assert not ok
    ok, _ = newsroom.skeptic("See [e99999].", {}, {"allow": []})
    assert not ok
    ok, why = newsroom.skeptic("That is the turning point.", {}, {"allow": [], "delta": 0.05})
    assert not ok and "15" in why
    ok, _ = newsroom.skeptic("Score 2 to 1.", {"s": "2–1"}, {"allow": []})
    assert ok


def test_forecast_cues_are_descriptive(newsroom):
    fc = [c for c in newsroom.cues if c["kind"] == "forecast"]
    assert fc, "expected periodic forecast cues"
    for c in fc:
        assert "Most likely finish" in c["text"]["en"]["casual"] or "likeliest result" in c["text"]["en"]["casual"]
    goals = [c for c in newsroom.cues if c["kind"] == "goal"]
    assert all(c["text"]["en"].get("casual_more") for c in goals)


def test_recap(newsroom):
    r = newsroom.recap("pcm")
    assert r["headline"].startswith("Full time")
    assert r["moments"]


# ---------------------------------------------------------------- API
def test_api_end_to_end():
    c = TestClient(app)
    assert c.get("/health").json()["ok"]
    assert len(c.get("/api/clubs").json()["clubs"]) == 6
    m = c.get("/api/match", params={"home": "kes", "away": "amb", "seed": 42}).json()
    assert m["home"]["id"] == "kes"
    ev = c.get("/api/match", params={"home": "kes", "away": "amb", "seed": 42, "events": True}).json()["events"]
    pas = next(e for e in ev if e["type"] == "pass")
    r = c.post("/api/play", json={"home": "kes", "away": "amb", "seed": 42, "event_id": pas["event_id"], "x": 60, "y": 30})
    assert r.status_code == 200 and "yours" in r.json()
    assert c.get("/api/duel", params={"home": "kes", "away": "amb", "seed": 42, "event_id": pas["event_id"]}).status_code == 200
    assert c.get("/api/recap", params={"home": "kes", "away": "amb", "seed": 42, "lang": "fr"}).json()["lang"] == "fr"
    assert c.get("/api/recap", params={"home": "kes", "away": "amb", "seed": 42, "lang": "xx"}).status_code == 400


def test_live_stream_runs_to_full_time():
    c = TestClient(app)
    kinds = {}
    with c.stream("GET", "/api/live", params={"home": "cal", "away": "wht", "seed": 5, "skip": 95, "speed": 400}) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                msg = json.loads(line[6:])
                kinds[msg["type"]] = kinds.get(msg["type"], 0) + 1
    for k in ("meta", "event", "trace", "cue", "outlook", "stats", "recap", "end"):
        assert kinds.get(k), k
