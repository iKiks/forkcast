"""The fork engine: measure what a moment changed by replaying the future.

The engine's own output is used to fit a Markov model of the match
(team in possession x pitch zone -> next state). Two solvers run on that model:

* an exact backward dynamic program giving the full distribution of the final
  goal difference from any state (used for the live outlook and Futures River), and
* a vectorised Monte Carlo sampler that plays N futures (used as the visible
  "1,000 forks" and as an independent cross-check of the exact solver).

Because the model is fitted to the same engine that generates the match, the
forecasts and the data come from one world.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .engine import (KICKOFF_ZONE, N_ZONES, MatchSim, pass_success_prob, zone_center, zone_of)
from .world import CLUBS, PITCH_LENGTH as L, PITCH_WIDTH as W

Z = N_ZONES
N_OUT = 2 * Z + 1  # keep (Z) + turnover (Z) + goal (1)
K = 10  # final goal difference support: -K..K
D = 2 * K + 1
G = 8  # extra goals tracked per side in the joint solver (0..7)
SKIP_TYPES = {"period_start", "period_end", "full_time", "substitution", "card"}
EXPECTED_STOPPAGE = (150.0, 225.0)
CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache"


@dataclass
class ChainModel:
    home: str
    away: str
    P: np.ndarray  # (2, Z, N_OUT)
    dt: float  # seconds per step
    goal_steps: int  # extra steps consumed by a goal restart
    n_matches: int

    def to_json(self) -> dict:
        return {"home": self.home, "away": self.away, "P": self.P.tolist(), "dt": self.dt,
                "goal_steps": self.goal_steps, "n_matches": self.n_matches}

    @classmethod
    def from_json(cls, d: dict) -> "ChainModel":
        return cls(d["home"], d["away"], np.array(d["P"]), d["dt"], d["goal_steps"], d["n_matches"])


def fit_chain(home: str, away: str, n_matches: int = 60, base_seed: int = 900_000) -> ChainModel:
    """Fit the transition model to simulated matches between these two clubs."""
    counts = np.zeros((2, Z, N_OUT))
    dts: list[float] = []
    restart: list[float] = []
    for i in range(n_matches):
        m = MatchSim(CLUBS[home], CLUBS[away], base_seed + i).run()
        prev = None
        skip_next = False
        for ev in m.events:
            if ev["type"] in SKIP_TYPES:
                continue
            st = ev["state"]
            if prev is None or ev["period"] != prev["period"]:
                prev = {**st, "period": ev["period"]}
                continue
            if skip_next:
                restart.append(st["t"] - prev["t"])
                skip_next = False
                prev = {**st, "period": ev["period"]}
                continue
            T = prev["poss"]
            if st["score"][T] > prev["score"][T]:
                o = 2 * Z
                skip_next = True
            elif st["poss"] == T:
                o = st["zone"]
            else:
                o = Z + st["zone"]
            counts[T, prev["zone"], o] += 1
            dts.append(max(0.1, st["t"] - prev["t"]))
            prev = {**st, "period": ev["period"]}
    # smoothing towards the pooled distribution of the zone
    pooled = counts.sum(0, keepdims=True)
    pooled = pooled / np.maximum(pooled.sum(-1, keepdims=True), 1)
    alpha = 3.0
    P = counts + alpha * pooled
    P = P / P.sum(-1, keepdims=True)
    dt = float(np.mean(dts))
    goal_steps = int(round(np.mean(restart) / dt)) if restart else 10
    return ChainModel(home, away, P, dt, goal_steps, n_matches)


def load_or_fit(home: str, away: str, n_matches: int = 60) -> ChainModel:
    CACHE_DIR.mkdir(exist_ok=True)
    f = CACHE_DIR / f"chain-{home}-{away}-{n_matches}.json"
    if f.exists():
        return ChainModel.from_json(json.loads(f.read_text()))
    model = fit_chain(home, away, n_matches)
    f.write_text(json.dumps(model.to_json()))
    return model


class ForkEngine:
    """Exact outlook + Monte Carlo forks for one fixture."""

    def __init__(self, model: ChainModel):
        self.m = model
        self.P = model.P
        self.keep = model.P[:, :, :Z]
        self.turn = model.P[:, :, Z:2 * Z]
        self.goal = model.P[:, :, 2 * Z]
        self.cum = np.cumsum(model.P, axis=-1)
        self.cum[..., -1] = 1.0
        total = 5400 + sum(EXPECTED_STOPPAGE) + 120
        self.S = int(math.ceil(total / model.dt)) + model.goal_steps + 2
        self.J = self._solve_joint()
        self.N = self._solve_next_goal()
        self.threat = self._threat()
        self.avg_threat = float(self.threat.mean())
        g = np.arange(G)
        self._a = g[:, None] * np.ones((1, G), dtype=int)
        self._b = g[None, :] * np.ones((G, 1), dtype=int)
        self._ab = self._a - self._b

    # ------------------------------------------------------------ exact solvers
    def _solve_joint(self) -> np.ndarray:
        """J[s, p, z, a, b]: probability the home side adds a goals and the away side b goals in s steps."""
        S, gs = self.S, self.m.goal_steps
        J = np.zeros((S + 1, 2, Z, G, G), dtype=np.float32)
        J[0, :, :, 0, 0] = 1.0
        keep = self.keep.astype(np.float32)
        turn = self.turn.astype(np.float32)
        goal = self.goal.astype(np.float32)
        for s in range(1, S + 1):
            nxt = J[s - 1].reshape(2, Z, G * G)
            k = np.einsum("pzy,pyd->pzd", keep, nxt)
            t = np.einsum("pzy,pyd->pzd", turn, nxt[::-1])
            ag = J[max(0, s - 1 - gs)]
            gh = np.zeros((G, G), dtype=np.float32)  # home scores, away kicks off
            gh[1:] = ag[1, KICKOFF_ZONE][:-1]
            gh[-1] += ag[1, KICKOFF_ZONE][-1]
            ga = np.zeros((G, G), dtype=np.float32)  # away scores, home kicks off
            ga[:, 1:] = ag[0, KICKOFF_ZONE][:, :-1]
            ga[:, -1] += ag[0, KICKOFF_ZONE][:, -1]
            g = np.stack([gh, ga]).reshape(2, 1, G * G)
            J[s] = (k + t + goal[:, :, None] * g).reshape(2, Z, G, G)
        return J

    def _solve_next_goal(self) -> np.ndarray:
        """N[s, p, z, k]: probability the next goal comes within s steps and is scored by side k."""
        S = self.S
        N = np.zeros((S + 1, 2, Z, 2), dtype=np.float32)
        e = np.zeros((2, Z, 2), dtype=np.float32)
        e[0, :, 0] = self.goal[0]
        e[1, :, 1] = self.goal[1]
        for s in range(1, S + 1):
            nxt = N[s - 1]
            N[s] = np.einsum("pzy,pyk->pzk", self.keep, nxt) + np.einsum("pzy,pyk->pzk", self.turn, nxt[::-1]) + e
        return N

    def _threat(self) -> np.ndarray:
        """Probability the current possession ends in a goal, per team and zone (an xT-style value)."""
        out = np.zeros((2, Z))
        for p in (0, 1):
            A = np.eye(Z) - self.keep[p]
            out[p] = np.linalg.solve(A, self.goal[p])
        return out

    # ------------------------------------------------------------ time helpers
    @staticmethod
    def remaining_seconds(t: float, period: int) -> float:
        e1, e2 = EXPECTED_STOPPAGE
        if period == 1:
            return max(30.0, 2700 + e1 - t) + 2700 + e2
        return max(30.0, 5400 + e2 - t)

    def steps(self, t: float, period: int) -> int:
        return int(min(self.S, round(self.remaining_seconds(t, period) / self.m.dt)))

    # ------------------------------------------------------------ outlook
    def joint(self, t: float, period: int, poss: int, zone: int) -> np.ndarray:
        return self.J[self.steps(t, period), poss, zone]

    def distribution(self, t: float, period: int, poss: int, zone: int) -> np.ndarray:
        """Distribution of the change in goal difference (home minus away), support -K..K."""
        j = self.joint(t, period, poss, zone)
        out = np.zeros(D)
        np.add.at(out, self._ab.ravel() + K, j.ravel())
        return out

    def outlook(self, t: float, period: int, score: list[int], poss: int, zone: int) -> dict:
        j = self.joint(t, period, poss, zone).astype(np.float64)
        j = j / j.sum()
        diff0 = score[0] - score[1]
        fd = self._ab + diff0
        home = float(j[fd > 0].sum())
        draw = float(j[fd == 0].sum())
        away = float(j[fd < 0].sum())
        dist = np.zeros(D)
        np.add.at(dist, self._ab.ravel() + K, j.ravel())
        f = np.arange(-K, K + 1) + diff0
        cdf = np.cumsum(dist)
        q = {k: int(f[min(len(f) - 1, np.searchsorted(cdf, v))]) for k, v in
             (("p10", 0.10), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90))}
        flat = np.argsort(j.ravel())[::-1][:4]
        scorelines = [{"score": [int(score[0] + i // G), int(score[1] + i % G)], "p": round(float(j.ravel()[i]), 4)}
                      for i in flat]
        steps = self.steps(t, period)
        ng = self.N[steps, poss, zone].astype(np.float64)
        s10 = min(steps, int(round(600 / self.m.dt)))
        ng10 = self.N[s10, poss, zone].astype(np.float64)
        rem = self.remaining_seconds(t, period)
        return {
            "home_win": round(home, 4), "draw": round(draw, 4), "away_win": round(away, 4),
            "exp_points": [round(3 * home + draw, 3), round(3 * away + draw, 3)],
            "final_diff": {**q, "mean": round(float((dist * f).sum()), 3)},
            "threat": round(float(self.threat[poss, zone]), 4),
            "scorelines": scorelines,
            "exp_goals_left": [round(float((j * self._a).sum()), 3), round(float((j * self._b).sum()), 3)],
            "next_goal": {"home": round(float(ng[0]), 4), "away": round(float(ng[1]), 4),
                          "none": round(float(max(0.0, 1 - ng.sum())), 4)},
            "next_goal_10": {"home": round(float(ng10[0]), 4), "away": round(float(ng10[1]), 4),
                             "none": round(float(max(0.0, 1 - ng10.sum())), 4)},
            "mins_left": int(round(rem / 60)),
        }

    def outlook_from_state(self, state: dict, period: int) -> dict:
        return self.outlook(state["t"], period, state["score"], state["poss"], state["zone"])

    # ------------------------------------------------------------ Monte Carlo
    def sample(self, t: float, period: int, score: list[int], poss: int, zone: int, n: int = 1000,
               seed: int = 0) -> dict:
        rng = np.random.default_rng(seed)
        steps = self.steps(t, period)
        p = np.full(n, poss, dtype=np.int64)
        z = np.full(n, zone, dtype=np.int64)
        diff = np.full(n, score[0] - score[1], dtype=np.int64)
        left = np.full(n, steps, dtype=np.int64)
        goals_h = np.zeros(n, dtype=np.int64)
        goals_a = np.zeros(n, dtype=np.int64)
        active = left > 0
        it = 0
        while active.any() and it < 4 * self.S:
            it += 1
            idx = np.nonzero(active)[0]
            u = rng.random(idx.size)
            c = self.cum[p[idx], z[idx]]
            o = (u[:, None] > c).sum(1)
            o = np.minimum(o, N_OUT - 1)
            keep = o < Z
            turn = (o >= Z) & (o < 2 * Z)
            goal = o == 2 * Z
            ik, it_, ig = idx[keep], idx[turn], idx[goal]
            z[ik] = o[keep]
            z[it_] = o[turn] - Z
            p[it_] = 1 - p[it_]
            scorer = p[ig]
            diff[ig] += np.where(scorer == 0, 1, -1)
            goals_h[ig] += scorer == 0
            goals_a[ig] += scorer == 1
            p[ig] = 1 - scorer
            z[ig] = KICKOFF_ZONE
            left[idx] -= 1
            left[ig] -= self.m.goal_steps
            active = left > 0
        home = float((diff > 0).mean())
        draw = float((diff == 0).mean())
        away = float((diff < 0).mean())
        se = math.sqrt(max(home * (1 - home), 1e-9) / n)
        return {
            "n": n, "home_win": round(home, 4), "draw": round(draw, 4), "away_win": round(away, 4),
            "home_win_ci95": round(1.96 * se, 4),
            "final_diff_hist": {int(k): int(v) for k, v in zip(*np.unique(diff, return_counts=True))},
            "extra_goals_mean": [round(float(goals_h.mean()), 3), round(float(goals_a.mean()), 3)],
        }

    # ------------------------------------------------------------ counterfactuals
    def pass_option(self, team: int, q_diff: float, ap0: float, y0: float, tap: float, ty: float,
                    pressure: bool, t: float, period: int, score: list[int]) -> dict:
        """Value of passing from (ap0, y0) to (tap, ty) in team's attacking frame."""
        length = math.hypot(tap - ap0, ty - y0)
        prob = pass_success_prob(q_diff, length, pressure, ap0 / L, tap / L)
        t1 = t + 1.0 + length / 15
        ok = self.outlook(t1, period, score, team, zone_of(tap, ty))
        ix = ap0 + (tap - ap0) * 0.75
        iy = y0 + (ty - y0) * 0.75
        bad = self.outlook(t1, period, score, 1 - team, zone_of(L - ix, iy))
        ep = prob * ok["exp_points"][team] + (1 - prob) * bad["exp_points"][team]
        win = prob * (ok["home_win"] if team == 0 else ok["away_win"]) + (1 - prob) * (
            bad["home_win"] if team == 0 else bad["away_win"])
        threat = prob * float(self.threat[team, zone_of(tap, ty)])
        return {"success_prob": round(prob, 3), "length": round(length, 1), "exp_points": round(ep, 4),
                "win_prob": round(win, 4), "threat": round(threat, 4),
                "difficulty": round((1 - prob) * 100)}

    def best_pass(self, team: int, q_diff: float, ap0: float, y0: float, pressure: bool, t: float,
                  period: int, score: list[int], max_len: float = 48.0, min_success: float = 0.0,
                  forward_only: bool = False) -> tuple[tuple[float, float], dict]:
        best, best_opt = None, None
        for tap in np.arange(max(2.0, ap0 - 25), min(L - 7, ap0 + max_len) + 0.1, 3.0):
            for ty in np.arange(3.0, W - 2.9, 4.0):
                d = math.hypot(tap - ap0, ty - y0)
                if d < 6 or d > max_len or (forward_only and tap < ap0 + 8):
                    continue
                opt = self.pass_option(team, q_diff, ap0, y0, float(tap), float(ty), pressure, t, period, score)
                if opt["success_prob"] < min_success:
                    continue
                if best_opt is None or opt["exp_points"] > best_opt["exp_points"] + 1e-9:
                    best, best_opt = (float(tap), float(ty)), opt
        return best, best_opt


def zone_label(z: int) -> str:
    pb, lb = divmod(z, 3)
    third = ["deep in own half", "own half", "midfield", "opposition half", "final third", "the box area"][pb]
    lane = ["right channel", "centre", "left channel"][lb]
    return f"{third}, {lane}"


__all__ = ["ChainModel", "ForkEngine", "fit_chain", "load_or_fit", "zone_label", "zone_center"]
