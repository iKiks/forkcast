"""Forkcast MCP server: the fork engine as tools for any MCP client.

Use it from GitHub Copilot agent mode in VS Code (see .vscode/mcp.json), from
Microsoft Foundry agents, or from any MCP-compatible client:

    python -m forkcast.mcp_server            # stdio transport

Matches are deterministic, so (home, away, seed) always identifies the same match.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .agents import Newsroom, pundit_duel
from .analysis import MatchContext
from .forecast import story
from .world import CLUBS, LEAGUE_NAME

mcp = FastMCP("forkcast")
_ctx: dict[str, MatchContext] = {}


def _get(home: str, away: str, seed: int) -> MatchContext:
    if home not in CLUBS or away not in CLUBS or home == away:
        raise ValueError(f"Clubs must be two different ids from {sorted(CLUBS)}")
    key = f"{home}-{away}-{seed}"
    if key not in _ctx:
        _ctx[key] = MatchContext(home, away, seed)
    return _ctx[key]


def _brief(ev: dict) -> dict:
    keep = ("event_id", "clock", "period", "team", "player", "type", "outcome", "x", "y", "end_x", "end_y", "xg",
            "speed_kmh", "pass_difficulty", "tags")
    return {k: ev.get(k) for k in keep if ev.get(k) not in (None, [], "")}


@mcp.tool()
def list_clubs() -> dict:
    """List the fictional clubs of the league with their style vectors."""
    return {"league": LEAGUE_NAME, "clubs": [{"id": c.id, "name": c.name, "style": c.style.__dict__} for c in CLUBS.values()]}


@mcp.tool()
def match_summary(home: str = "kes", away: str = "amb", seed: int = 42) -> dict:
    """Final score, goals and the pre-match outlook for a synthetic match."""
    c = _get(home, away, seed)
    goals = [_brief(e) for e in c.events if e["type"] == "shot" and e["outcome"] == "goal"]
    pre = c.fe.outlook(0.0, 1, [0, 0], 0, 10)
    return {"match_id": c.match_id, "final_score": c.match.score, "goals": goals, "prematch_outlook": pre,
            "n_events": len(c.events)}


@mcp.tool()
def get_events(home: str = "kes", away: str = "amb", seed: int = 42, from_minute: float = 0, to_minute: float = 95,
               types: list[str] | None = None, limit: int = 50) -> list[dict]:
    """Events between two match minutes, optionally filtered by type (pass, shot, interception, tackle, card...)."""
    c = _get(home, away, seed)
    out = []
    for e in c.events:
        m = e["t"] / 60
        if from_minute <= m <= to_minute and (not types or e["type"] in types):
            out.append(_brief(e))
            if len(out) >= limit:
                break
    return out


@mcp.tool()
def get_state(home: str = "kes", away: str = "amb", seed: int = 42, event_id: str = "e00001") -> dict:
    """Match state right after an event, with the exact win/draw/loss outlook from the fork engine."""
    c = _get(home, away, seed)
    i = c.by_id[event_id]
    st, per = c.state_after(i)
    return {"event": _brief(c.events[i]), "state": st, "outlook": c.fe.outlook_from_state(st, per)}


@mcp.tool()
def forecast(home: str = "kes", away: str = "amb", seed: int = 42, minute: float = 60, lang: str = "en") -> dict:
    """Descriptive forecast at a match minute: win/draw/loss, likely scorelines, who scores next, what the trailing side needs."""
    c = _get(home, away, seed)
    t = minute * 60
    period = 1 if minute <= 45 else 2
    cand = [e for e in c.events if e["period"] == period and e["t"] <= t and e["type"] not in ("substitution", "card")]
    ev = cand[-1] if cand else c.events[0]
    o = c.fe.outlook_from_state(ev["state"], ev["period"])
    texts, values = story(o, ev["state"]["score"], c.match.home, c.match.away)
    return {"clock": ev["clock"], "score": ev["state"]["score"], "outlook": o, "story": texts.get(lang, texts["en"])}


@mcp.tool()
def physical(home: str = "kes", away: str = "amb", seed: int = 42, minute: float = 95) -> dict:
    """Distance covered and top speed per player from the 5 Hz tracking feed, up to a match minute."""
    c = _get(home, away, seed)
    tr = c.tracking
    T = minute * 60 if minute <= 45 else tr.p2_start + (minute - 45) * 60
    rows = [{"player": pid, "name": c.players.get(pid, {}).get("name"), **v} for pid, v in tr.physical(T).items()]
    return {"distance": sorted(rows, key=lambda r: -r["km"]), "fastest": sorted(rows, key=lambda r: -r["top_kmh"])[:5]}


@mcp.tool()
def fork_match(home: str = "kes", away: str = "amb", seed: int = 42, event_id: str = "e00001", n: int = 1000) -> dict:
    """Measure what one moment changed: exact outlook before vs after, plus n Monte Carlo forks of each."""
    c = _get(home, away, seed)
    return c.impact(event_id, n_forks=max(0, min(5000, n)))


@mcp.tool()
def counterfactual_pass(home: str = "kes", away: str = "amb", seed: int = 42, event_id: str = "e00001",
                        x: float | None = None, y: float | None = None) -> dict:
    """What if the player had passed to (x, y) instead? Also returns the best, safest and most direct options."""
    c = _get(home, away, seed)
    return c.counterfactual(event_id, x, y)


@mcp.tool()
def pundit_debate(home: str = "kes", away: str = "amb", seed: int = 42, event_id: str = "e00001") -> dict:
    """Two pundit agents argue safe vs direct; the simulator rules with measured evidence."""
    c = _get(home, away, seed)
    d = pundit_duel(c, event_id)
    d.pop("counterfactual", None)
    return d


@mcp.tool()
def verify_claim(home: str = "kes", away: str = "amb", seed: int = 42, text: str = "", event_id: str = "e00001") -> dict:
    """Run the Skeptic on a sentence about an event: every number and event id must be backed by evidence."""
    c = _get(home, away, seed)
    nr = Newsroom(c, lambda m: None, use_llm=False)
    im = c.impact(event_id)
    wk = im["win_key"]
    values = {"before": round(im["before"][wk] * 100), "after": round(im["after"][wk] * 100),
              "delta": f"{im['delta_win'] * 100:+.1f}", "threat": f"{im['after']['threat'] * 100:.1f}"}
    ok, reason = nr.skeptic(text, values, {"delta": im["delta_win"], "allow": [], "max_prev": 1.0})
    return {"verified": ok, "reason": reason or "All numbers and ids match the evidence.", "evidence": values}


@mcp.tool()
def recap(home: str = "kes", away: str = "amb", seed: int = 42, lang: str = "en") -> dict:
    """Full-time recap in en, fr, es, pt or pcm (Nigerian Pidgin), with the moments ranked by measured swing."""
    c = _get(home, away, seed)
    nr = Newsroom(c, lambda m: None, use_llm=False)
    for i in range(len(c.events)):
        nr.process(i)
    return nr.recap(lang)


if __name__ == "__main__":
    mcp.run()
