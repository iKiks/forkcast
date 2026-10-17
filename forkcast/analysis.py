"""Match context: moment impact, counterfactuals and the Futures River for one match."""
from __future__ import annotations

from functools import lru_cache

from .engine import KICKOFF_ZONE, Match, MatchSim, zone_of
from .forks import ForkEngine, load_or_fit
from .tracking import build as build_tracking
from .world import CLUBS, PITCH_LENGTH as L

SKIP = {"period_start", "period_end", "full_time", "substitution", "card"}
RESOLUTION = {"interception", "tackle", "throw_in", "goalkeeper", "goal_kick", "recovery", "clearance"}
ON_BALL = {"pass", "carry", "cross", "shot"}


@lru_cache(maxsize=16)
def fork_engine_for(home: str, away: str) -> ForkEngine:
    return ForkEngine(load_or_fit(home, away))


class MatchContext:
    def __init__(self, home: str, away: str, seed: int):
        self.match: Match = MatchSim(CLUBS[home], CLUBS[away], seed).run()
        self.fe = fork_engine_for(home, away)
        self.events = self.match.events
        self.tracking = build_tracking(self.events, self.match.home, self.match.away, seed)
        self.by_id = {e["event_id"]: i for i, e in enumerate(self.events)}
        self.team_index = {home: 0, away: 1}
        self.players = {}
        for ti, club in enumerate((self.match.home, self.match.away)):
            for p in club.players + club.bench:
                self.players[p.id] = {**p.__dict__, "team": club.id, "team_index": ti}
        self.q = [self.match.home.style.quality, self.match.away.style.quality]

    @property
    def match_id(self) -> str:
        return self.match.match_id

    # ---------------------------------------------------------------- states
    def state_before(self, i: int) -> tuple[dict, int]:
        j = i - 1
        while j >= 0 and self.events[j]["type"] in SKIP:
            j -= 1
        if j < 0:
            j = 0
        return self.events[j]["state"], self.events[j]["period"]

    def state_after(self, i: int) -> tuple[dict, int]:
        ev = self.events[i]
        if ev["type"] == "shot" and ev["outcome"] == "goal":
            # a goal is resolved the moment it happens: the other side kicks off from the centre
            team = self.team_index[ev["team"]]
            return {**ev["state"], "poss": 1 - team, "zone": KICKOFF_ZONE, "ap": 52.5, "y": 34.0}, ev["period"]
        if i + 1 < len(self.events):
            nxt = self.events[i + 1]
            if nxt["type"] in RESOLUTION:
                return nxt["state"], nxt["period"]
        return ev["state"], ev["period"]

    def outlook_at(self, i: int, after: bool = True) -> dict:
        st, per = self.state_after(i) if after else self.state_before(i)
        return self.fe.outlook_from_state(st, per)

    # ---------------------------------------------------------------- impact
    def impact(self, event_id: str, n_forks: int = 0) -> dict:
        i = self.by_id[event_id]
        ev = self.events[i]
        sb, pb = self.state_before(i)
        sa, pa = self.state_after(i)
        before = self.fe.outlook_from_state(sb, pb)
        after = self.fe.outlook_from_state(sa, pa)
        team = self.team_index.get(ev["team"], 0) if ev["team"] else 0
        wk = "home_win" if team == 0 else "away_win"
        out = {
            "event_id": event_id,
            "team": ev["team"],
            "team_index": team,
            "before": before,
            "after": after,
            "delta_win": round(after[wk] - before[wk], 4),
            "delta_home_win": round(after["home_win"] - before["home_win"], 4),
            "delta_exp_points": round(after["exp_points"][team] - before["exp_points"][team], 4),
            "win_key": wk,
        }
        if n_forks:
            seed = int(event_id[1:])
            fb = self.fe.sample(sb["t"], pb, sb["score"], sb["poss"], sb["zone"], n_forks, seed)
            fa = self.fe.sample(sa["t"], pa, sa["score"], sa["poss"], sa["zone"], n_forks, seed + 1)
            out["forks"] = {"before": fb, "after": fa}
        return out

    # ---------------------------------------------------------------- counterfactual
    def frame(self, team: int, x: float) -> float:
        return x if team == 0 else L - x

    def unframe(self, team: int, ap: float) -> float:
        return ap if team == 0 else L - ap

    def counterfactual(self, event_id: str, target_x: float | None = None, target_y: float | None = None) -> dict:
        """Play the Moment: what if the player had passed to (target_x, target_y)?"""
        i = self.by_id[event_id]
        ev = self.events[i]
        if ev["type"] not in ON_BALL or ev["team"] is None:
            raise ValueError("Pick an on-ball moment (pass, carry, cross or shot).")
        team = self.team_index[ev["team"]]
        sb, pb = self.state_before(i)
        ap0 = self.frame(team, ev["x"])
        y0 = ev["y"]
        qd = self.q[team] - self.q[1 - team]
        args = (team, qd, ap0, y0)
        ctx = (sb["t"], pb, sb["score"])
        actual = self.fe.outlook_from_state(*self.state_after(i))
        actual_ep = actual["exp_points"][team]
        wk = "home_win" if team == 0 else "away_win"
        res = {
            "event_id": event_id, "team": ev["team"], "team_index": team, "player": ev["player"],
            "from": {"x": ev["x"], "y": y0},
            "actual": {"type": ev["type"], "outcome": ev["outcome"],
                       "to": {"x": ev.get("end_x"), "y": ev.get("end_y")},
                       "exp_points": actual_ep, "win_prob": actual[wk]},
            "before": self.fe.outlook_from_state(sb, pb),
        }
        best_t, best = self.fe.best_pass(*args, ev["pressure"], *ctx)
        res["best"] = {**best, "to": {"x": round(self.unframe(team, best_t[0]), 1), "y": best_t[1]}}
        safe_t, safe = self.fe.best_pass(*args, ev["pressure"], *ctx, max_len=18.0, min_success=0.88)
        if not safe_t:
            safe_t, safe = self.fe.best_pass(*args, ev["pressure"], *ctx, max_len=18.0, min_success=0.6)
        if safe_t:
            res["safe"] = {**safe, "to": {"x": round(self.unframe(team, safe_t[0]), 1), "y": safe_t[1]}}
        direct_t, direct = self.fe.best_pass(*args, ev["pressure"], *ctx, forward_only=True)
        if not direct_t:
            direct_t, direct = best_t, best
        if direct_t:
            res["direct"] = {**direct, "to": {"x": round(self.unframe(team, direct_t[0]), 1), "y": direct_t[1]}}
        if target_x is not None and target_y is not None:
            tap = self.frame(team, float(target_x))
            yours = self.fe.pass_option(team, qd, ap0, y0, tap, float(target_y), ev["pressure"], *ctx)
            # sample both branches with real forks so the viewer sees futures, not just a number
            t1 = sb["t"] + 1.0 + yours["length"] / 15
            ok = self.fe.sample(t1, pb, sb["score"], team, zone_of(tap, float(target_y)), 1000, i)
            ix = ap0 + (tap - ap0) * 0.75
            iy = y0 + (float(target_y) - y0) * 0.75
            bad = self.fe.sample(t1, pb, sb["score"], 1 - team, zone_of(L - ix, iy), 1000, i + 7)
            p = yours["success_prob"]
            mixed = {k: round(p * ok[k] + (1 - p) * bad[k], 4) for k in ("home_win", "draw", "away_win")}
            res["yours"] = {**yours, "to": {"x": round(float(target_x), 1), "y": round(float(target_y), 1)},
                            "forks": {"n": 2000, "if_completed": ok, "if_lost": bad, "mixed": mixed}}
            res["verdict_delta_ep"] = round(yours["exp_points"] - actual_ep, 4)
        res["best_delta_ep"] = round(best["exp_points"] - actual_ep, 4)
        return res

    # ---------------------------------------------------------------- river
    def river(self, step_seconds: int = 60) -> list[dict]:
        pts = []
        j = 0
        n = len(self.events)
        end_t = self.events[-1]["t"]
        for period, (t0, t1) in ((1, (0, None)), (2, (2700, None))):
            pe = [e for e in self.events if e["period"] == period]
            last = pe[-1]["t"]
            t = t0
            while t <= last + 1:
                while j + 1 < n and self.events[j + 1]["t"] <= t and self.events[j + 1]["period"] <= period:
                    j += 1
                k = j
                while k > 0 and self.events[k]["type"] in SKIP:
                    k -= 1
                st = self.events[k]["state"]
                o = self.fe.outlook(t, period, st["score"], st["poss"], st["zone"])
                pts.append({"t": t, "period": period, "score": st["score"], **o})
                t += step_seconds
        del end_t
        return pts
