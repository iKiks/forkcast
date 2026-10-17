"""Streaming interpreter: turns raw events into football statistics and patterns.

It is incremental: ``ingest(event)`` is called once per event as it arrives, so it
works identically for live streams and replays.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque

TURNOVERS = {"interception", "tackle"}
ON_BALL = {"pass", "carry", "cross", "shot"}


def _blank_team() -> dict:
    return {"passes": 0, "passes_complete": 0, "shots": 0, "on_target": 0, "goals": 0, "xg": 0.0,
            "fouls": 0, "yellow": 0, "red": 0, "corners": 0, "turnovers_won": 0, "possession_s": 0.0,
            "final_third_entries": 0}


def _blank_player() -> dict:
    return {"touches": 0, "passes": 0, "passes_complete": 0, "shots": 0, "goals": 0, "xg": 0.0,
            "turnovers_won": 0, "top_speed_kmh": 0.0, "hardest_pass_completed": 0, "carries": 0}


class Interpreter:
    def __init__(self, home_id: str, away_id: str):
        self.ids = [home_id, away_id]
        self.team = {home_id: _blank_team(), away_id: _blank_team()}
        self.players: dict[str, dict] = defaultdict(_blank_player)
        self.window: deque = deque()  # recent on-ball/turnover events for rhythm metrics
        self.last_t = 0.0
        self.last_poss: str | None = None
        self.chain_len: dict[int, int] = defaultdict(int)
        self.records = {"fastest_shot": None, "fastest_sprint": None, "hardest_pass": None}
        self.control_history: list[dict] = []
        self.score = [0, 0]

    def ingest(self, ev: dict) -> dict:
        """Update statistics; return derived annotations for this event (tags, records)."""
        notes: dict = {"records": []}
        t = ev["t"]
        poss_team = self.ids[ev["state"]["poss"]]
        if self.last_poss is not None and t > self.last_t and ev["type"] not in ("period_start",):
            self.team[self.last_poss]["possession_s"] += min(30.0, t - self.last_t)
        self.last_t, self.last_poss = t, poss_team
        self.score = list(ev["state"]["score"])
        typ = ev["type"]
        tid = ev.get("team")
        pid = ev.get("player")
        if tid not in self.team:
            return notes
        ts = self.team[tid]
        ps = self.players[pid] if pid else None
        if ps is not None and typ in ON_BALL:
            ps["touches"] += 1
        if typ in ON_BALL or typ in TURNOVERS:
            self.window.append(ev)
            self.chain_len[ev["chain_id"]] += 1
        while self.window and self.window[0]["t"] < t - 300:
            self.window.popleft()
        if typ == "pass":
            ts["passes"] += 1
            ps["passes"] += 1
            if "final_third_entry" in ev.get("tags", []) and ev["outcome"] == "complete":
                ts["final_third_entries"] += 1
            if ev["outcome"] == "complete":
                ts["passes_complete"] += 1
                ps["passes_complete"] += 1
                diff = ev.get("pass_difficulty", 0)
                ps["hardest_pass_completed"] = max(ps["hardest_pass_completed"], diff)
                rec = self.records["hardest_pass"]
                if diff >= 45 and (rec is None or diff > rec["value"]):
                    self.records["hardest_pass"] = {"value": diff, "event_id": ev["event_id"], "player": pid}
                    notes["records"].append("hardest_pass")
        elif typ == "carry":
            ps["carries"] += 1
            sp = ev.get("speed_kmh") or 0
            ps["top_speed_kmh"] = max(ps["top_speed_kmh"], sp)
            rec = self.records["fastest_sprint"]
            if sp >= 31 and (rec is None or sp > rec["value"]):
                self.records["fastest_sprint"] = {"value": sp, "event_id": ev["event_id"], "player": pid}
                notes["records"].append("fastest_sprint")
        elif typ == "shot":
            ts["shots"] += 1
            ts["xg"] += ev.get("xg", 0)
            ps["shots"] += 1
            ps["xg"] += ev.get("xg", 0)
            if ev["outcome"] in ("goal", "saved"):
                ts["on_target"] += 1
            if ev["outcome"] == "goal":
                ts["goals"] += 1
                ps["goals"] += 1
            sp = ev.get("speed_kmh") or 0
            rec = self.records["fastest_shot"]
            if rec is None or sp > rec["value"]:
                self.records["fastest_shot"] = {"value": sp, "event_id": ev["event_id"], "player": pid}
                notes["records"].append("fastest_shot")
        elif typ in TURNOVERS:
            ts["turnovers_won"] += 1
            ps["turnovers_won"] += 1
        elif typ == "foul":
            ts["fouls"] += 1
        elif typ == "card":
            if ev["outcome"] == "yellow":
                ts["yellow"] += 1
            else:
                ts["red"] += 1
        elif typ == "corner":
            ts["corners"] += 1
        return notes

    # ------------------------------------------------------------------ rhythm
    def control_index(self) -> dict:
        """0 = chaos, 100 = control, over the last five match minutes."""
        evs = list(self.window)
        if len(evs) < 8:
            return {"index": 50, "dominant": None, "turnover_rate": 0.0, "pressure_share": 0.0, "chain_len": 0.0}
        on_ball = [e for e in evs if e["type"] in ON_BALL]
        turn = sum(1 for e in evs if e["type"] in TURNOVERS)
        rate = turn / max(1, len(on_ball))
        pressure = sum(1 for e in on_ball if e.get("pressure")) / max(1, len(on_ball))
        chains = {e["chain_id"] for e in evs}
        avg_chain = len(on_ball) / max(1, len(chains))
        raw = (avg_chain - 5.5) / 2.5 - (rate - 0.12) * 12 - (pressure - 0.35) * 3
        idx = int(round(100 / (1 + math.exp(-raw))))
        counts = {tid: sum(1 for e in on_ball if e["team"] == tid) for tid in self.ids}
        dom = max(counts, key=counts.get) if on_ball else None
        share = counts[dom] / max(1, len(on_ball)) if dom else 0.5
        return {"index": idx, "dominant": dom, "dominant_share": round(share, 2), "turnover_rate": round(rate, 3),
                "pressure_share": round(pressure, 2), "chain_len": round(avg_chain, 1)}

    def snapshot(self) -> dict:
        total = sum(self.team[t]["possession_s"] for t in self.ids) or 1
        teams = {}
        for tid in self.ids:
            s = dict(self.team[tid])
            s["possession"] = round(s["possession_s"] / total, 3)
            s["pass_completion"] = round(s["passes_complete"] / max(1, s["passes"]), 3)
            s["xg"] = round(s["xg"], 2)
            teams[tid] = s
        return {"teams": teams, "control": self.control_index(), "records": self.records}

    def player_stats(self, pid: str) -> dict:
        p = dict(self.players.get(pid, _blank_player()))
        p["xg"] = round(p["xg"], 2)
        p["top_speed_kmh"] = round(p["top_speed_kmh"], 1)
        return p
