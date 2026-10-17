"""The Forkcast newsroom: seven agents that hypothesize, test and verify.

Spotter   flags candidate moments from the stream (cheap rules, no model).
Analyst   decides which experiment would show why a moment matters.
Simulator runs the experiment on the fork engine (exact solve + Monte Carlo forks).
Narrator  writes the line for each lens and language from the measured evidence.
Skeptic   blocks any line whose numbers, event ids or superlatives are not backed by evidence.
Director  applies broadcast grammar: priority, pacing and overlay type.
Localizer delivers every lens in five languages (templates, or a model when configured).

Every step is emitted as a trace message so the "Agent Newsroom" panel can show
the hand-offs, rejections and timings live.
"""
from __future__ import annotations

import re
import time
from statistics import median
from typing import Callable

from . import llm
from .analysis import MatchContext
from .engine import KICKOFF_ZONE
from .forecast import forecast_values, story
from .i18n import LANGS, club_prefix, render, render_story
from .interpret import Interpreter

MAIN_GAP_S = 75.0
TAG_GAP_S = 150.0
ALWAYS_AIR = {"goal", "red", "halftime", "fulltime"}
FORECAST_EVERY_S = 660.0
DISTANCE_MARKS = [(1, 1800.0), (2, 3600.0), (2, 5100.0)]
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
EID_RE = re.compile(r"\[(e\d{5})\]")
GUARDED = {
    "turning point": "turning_point",
    "fastest": "record",
    "hardest": "record",
    "record": "record",
    "best": "never",
    "worst": "never",
    "season": "never",
    "biggest": "biggest",
}


def pct(p: float) -> int:
    return int(round(100 * p))


def signed(d: float) -> str:
    return f"{100 * d:+.1f}"


class Newsroom:
    def __init__(self, ctx: MatchContext, emit: Callable[[dict], None], use_llm: bool = True):
        self.ctx = ctx
        self.emit = emit
        self.events = ctx.events
        self.home = ctx.match.home
        self.away = ctx.match.away
        self.clubs = [self.home, self.away]
        self.interp = Interpreter(self.home.id, self.away.id)
        self.cues: list[dict] = []
        self.rejections = 0
        self.dropped = 0
        self.latencies: list[float] = []
        self.forks_run = 0
        self.fork_ms = 0.0
        self.last_main_t = -1e9
        self.last_tag_t = -1e9
        self.last_control_check = 0.0
        self.last_control_cue = {"take": -1e9, "chaos": -1e9}
        self.last_dominant = None
        self.use_llm = use_llm and llm.enabled()
        self.n_cue = 0
        self.max_swing = 0.0
        self.last_forecast_T = 0.0
        self.last_goal_T = -1e9
        self.last_T = 0.0
        self.dist_marks = list(DISTANCE_MARKS)
        self.tracking = ctx.tracking

    # ------------------------------------------------------------------ helpers
    def pname(self, pid: str | None) -> str:
        return self.ctx.players.get(pid, {}).get("name", "?") if pid else "?"

    def club(self, tid: str | None):
        return self.home if tid == self.home.id else self.away

    def trace(self, agent: str, ev: dict, msg: str, status: str = "ok", ms: float | None = None, cue: str | None = None):
        self.emit({"type": "trace", "agent": agent, "t": ev["t"], "T": ev["T"], "clock": ev["clock"], "msg": msg, "status": status,
                   "ms": round(ms, 1) if ms is not None else None, "cue_id": cue})

    # ------------------------------------------------------------------ stream entry point
    def process(self, i: int) -> None:
        ev = self.events[i]
        notes = self.interp.ingest(ev)
        for cand in self.spot(i, ev, notes):
            self.pipeline(i, ev, cand)
        if ev["t"] - self.last_control_check >= 120 and ev["type"] in ("pass", "carry"):
            self.last_control_check = ev["t"]
            self.check_control(i, ev)
        if ev["type"] == "shot" and ev["outcome"] == "goal":
            self.last_goal_T = ev["T"]
        if (ev["T"] - self.last_forecast_T >= FORECAST_EVERY_S and ev["t"] > 480 and ev["type"] in ("pass", "carry")
                and ev["T"] - self.last_main_t >= 120 and ev["T"] - self.last_goal_T >= 300):
            self.last_forecast_T = ev["T"]
            self.pipeline(i, ev, {"kind": "forecast", "priority": 25, "reason": f"{ev['clock']} outlook check"})
        self.last_T = ev["T"]

    def physical(self, T: float) -> dict:
        """Distance and top-speed leaders from the tracking layer."""
        ph = self.tracking.physical(T)
        rows = [{"player": pid, "name": self.pname(pid), "team": self.ctx.players.get(pid, {}).get("team"), **v}
                for pid, v in ph.items()]
        teams = {c.id: round(sum(r["km"] for r in rows if r["team"] == c.id), 1) for c in self.clubs}
        return {"distance": sorted(rows, key=lambda r: -r["km"])[:5], "speed": sorted(rows, key=lambda r: -r["top_kmh"])[:5],
                "team_km": teams}

    # ------------------------------------------------------------------ Spotter
    def spot(self, i: int, ev: dict, notes: dict) -> list[dict]:
        typ = ev["type"]
        out = []
        if typ == "shot":
            if ev["outcome"] == "goal":
                out.append({"kind": "goal", "priority": 100, "reason": "goal scored"})
            elif ev.get("xg", 0) >= 0.17:
                out.append({"kind": "chance", "priority": 60, "reason": f"xG {ev['xg']:.2f} chance {ev['outcome']}"})
        elif typ in ("interception", "tackle"):
            ap = ev["state"]["ap"]
            if ap >= 55:
                out.append({"kind": "turnover", "priority": 40, "reason": f"ball won {ap:.0f} m up the pitch"})
        elif typ == "card" and ev["outcome"] in ("red", "second_yellow"):
            out.append({"kind": "red", "priority": 90, "reason": "player sent off"})
        elif typ == "period_end" and ev["period"] == 1:
            out.append({"kind": "halftime", "priority": 95, "reason": "half time"})
        elif typ == "full_time":
            out.append({"kind": "fulltime", "priority": 99, "reason": "full time"})
        while self.dist_marks and (ev["period"], ev["t"]) >= self.dist_marks[0]:
            per, tm = self.dist_marks.pop(0)
            if ev["period"] == per:
                out.append({"kind": "record_distance", "priority": 20, "reason": f"distance check at {int(tm // 60)}'"})
        if ev["t"] > 600:
            recs = self.interp.records
            if "fastest_shot" in notes["records"] and (ev.get("speed_kmh") or 0) >= 95:
                out.append({"kind": "record_shot", "priority": 20, "reason": "new fastest shot", "record": recs["fastest_shot"]})
            for rT, _slot, pid, kmh in self.tracking.records:
                if self.last_T < rT <= ev["T"] and kmh >= 32.0:
                    out.append({"kind": "record_sprint", "priority": 20, "reason": f"tracking: new top speed {kmh} km/h",
                                "record": {"value": kmh, "player": pid, "T": rT}, "players": [pid]})
            if "hardest_pass" in notes["records"] and ev.get("pass_difficulty", 0) >= 55:
                out.append({"kind": "record_pass", "priority": 20, "reason": "hardest pass completed", "record": recs["hardest_pass"]})
        return out

    def check_control(self, i: int, ev: dict) -> None:
        ci = self.interp.control_index()
        t = ev["t"]
        dom = ci.get("dominant")
        if ci["index"] >= 66 and ci.get("dominant_share", 0) >= 0.6 and (
                t - self.last_control_cue["take"] >= 600 or dom != self.last_dominant):
            self.last_control_cue["take"] = t
            self.last_dominant = dom
            self.pipeline(i, ev, {"kind": "control_take", "priority": 30, "reason": f"control index {ci['index']}", "control": ci})
        elif ci["index"] <= 32 and t - self.last_control_cue["chaos"] >= 600:
            self.last_control_cue["chaos"] = t
            self.pipeline(i, ev, {"kind": "control_chaos", "priority": 30, "reason": f"control index {ci['index']}", "control": ci})

    # ------------------------------------------------------------------ pipeline
    def pipeline(self, i: int, ev: dict, cand: dict) -> None:
        t0 = time.perf_counter()
        kind = cand["kind"]
        self.n_cue += 1
        cue_id = f"c{self.n_cue:04d}"
        self.trace("Spotter", ev, f"Flagged {kind.replace('_', ' ')} [{ev['event_id']}]: {cand['reason']}.", cue=cue_id)
        plan = self.analyst(kind)
        self.trace("Analyst", ev, plan, cue=cue_id)
        ts = time.perf_counter()
        values, evidence = self.simulate(i, ev, cand)
        sim_ms = (time.perf_counter() - ts) * 1000
        if values is None:
            self.dropped += 1
            self.trace("Simulator", ev, evidence.get("why", "Not newsworthy."), status="drop", ms=sim_ms, cue=cue_id)
            return
        self.trace("Simulator", ev, evidence["summary"], ms=sim_ms, cue=cue_id)
        texts, draft_note = self.narrate(kind, ev, values, evidence)
        self.trace("Narrator", ev, f"Drafted: “{texts['en']['casual']}”{draft_note}", cue=cue_id)
        ok, reason = self.skeptic(texts["en"]["casual"], values, evidence)
        if not ok:
            self.rejections += 1
            self.trace("Skeptic", ev, f"Rejected: {reason}", status="reject", cue=cue_id)
            texts = self.narrate(kind, ev, values, evidence, plain=True)[0]
            ok2, reason2 = self.skeptic(texts["en"]["casual"], values, evidence)
            if not ok2:
                self.trace("Skeptic", ev, f"Rejected rewrite too ({reason2}); dropping.", status="reject", cue=cue_id)
                return
            self.trace("Narrator", ev, f"Rewrote: “{texts['en']['casual']}”", cue=cue_id)
        for lang in LANGS:
            for lens in ("casual", "analyst"):
                if lang == "en" and lens == "casual":
                    continue
                okl, rl = self.skeptic(texts[lang][lens], values, evidence, strict_words=(lang == "en"))
                if not okl:
                    self.trace("Skeptic", ev, f"Rejected {lang}/{lens}: {rl}", status="reject", cue=cue_id)
                    return
        self.trace("Skeptic", ev, "Verified every number and event id against the evidence.", cue=cue_id)
        lane = "tag" if kind.startswith("record") else "main"
        if not self.director(kind, ev, lane, cue_id, cand["priority"]):
            return
        latency = (time.perf_counter() - t0) * 1000
        self.latencies.append(latency)
        self.trace("Localizer", ev, f"Delivered {len(LANGS)} languages × casual, analyst, club and player lenses.",
                   ms=latency, cue=cue_id)
        cue = {
            "type": "cue", "cue_id": cue_id, "kind": kind, "lane": lane, "overlay": self.overlay(kind),
            "t": ev["t"], "T": ev["T"], "clock": ev["clock"], "period": ev["period"], "event_id": ev["event_id"],
            "team": ev.get("team"),
            "players": cand.get("players") or values.get("_players") or [p for p in (ev.get("player"), ev.get("receiver")) if p],
            "values": values, "evidence": evidence, "text": texts, "duration": self.duration(kind),
            "latency_ms": round(latency, 1),
        }
        self.cues.append(cue)
        if kind in ("goal", "turnover"):
            self.max_swing = max(self.max_swing, abs(evidence.get("delta", 0.0)))
        self.emit(cue)

    # ------------------------------------------------------------------ Analyst
    @staticmethod
    def analyst(kind: str) -> str:
        return {
            "goal": "Hypothesis: this goal swings the result. Experiment: exact outlook before vs after, cross-checked with 1,000 forks.",
            "chance": "Hypothesis: the miss cost real value. Experiment: re-run the state as if the shot had gone in.",
            "turnover": "Hypothesis: winning the ball this high changes the outlook. Experiment: outlook before vs after the turnover.",
            "red": "Hypothesis: a numbers change. Experiment: none needed; report the fact, no forecast claim.",
            "record_shot": "Check: is this the fastest shot in the evidence so far?",
            "record_sprint": "Check: is this the fastest sprint in the evidence so far?",
            "record_pass": "Check: rank this pass by completion probability.",
            "control_take": "Hypothesis: one side now controls the rhythm. Experiment: five-minute control window.",
            "control_chaos": "Hypothesis: the game has lost its shape. Experiment: five-minute turnover and pressure window.",
            "halftime": "Experiment: outlook for the second half from the current state.",
            "forecast": "Question: how does the rest of the match look from here? Experiment: exact joint-score solve.",
            "record_distance": "Check: who has covered the most ground, from the tracking feed?",
            "fulltime": "Experiment: rank the match's moments by measured swing.",
        }[kind]

    # ------------------------------------------------------------------ Simulator
    def simulate(self, i: int, ev: dict, cand: dict) -> tuple[dict | None, dict]:
        kind = cand["kind"]
        fe = self.ctx.fe
        tid = ev.get("team")
        team = self.ctx.team_index.get(tid, 0)
        club = self.club(tid) if tid else None
        base = {"player": self.pname(ev.get("player")), "team": club.name if club else "", "eid": ev["event_id"]}
        allow: set[str] = set()
        if kind == "goal":
            n = 1000
            im = self.ctx.impact(ev["event_id"], n_forks=n)
            self.forks_run += 2 * n
            wk = im["win_key"]
            before, after = im["before"][wk], im["after"][wk]
            fork = im["forks"]["after"][wk]
            if abs(im["delta_win"]) >= 0.15 and abs(im["delta_win"]) > self.max_swing:
                allow.add("turning_point")
            sc = ev["state"]["score"]
            _, fv = forecast_values(im["after"], sc, self.home, self.away)
            values = {**fv, **base, "score": f"{sc[0]}–{sc[1]}", "before": pct(before), "after": pct(after),
                      "delta_s": signed(im["delta_win"]), "xg": f"{ev['xg']:.2f}", "speed": f"{ev['speed_kmh']:.0f}",
                      "n": f"{n:,}", "fork": pct(fork)}
            ev_ = {"impact": im, "delta": im["delta_win"], "allow": sorted(allow), "max_prev": self.max_swing,
                   "summary": f"{base['team']} win prob {pct(before)}% → {pct(after)}% (exact). "
                              f"{n:,} forks after the goal: {fork * 100:.1f}% ±{im['forks']['after']['home_win_ci95'] * 100:.1f}."}
            return values, ev_
        if kind == "chance":
            sb, pb = self.ctx.state_before(i)
            before = fe.outlook_from_state(sb, pb)
            sc = list(sb["score"])
            sc[team] += 1
            ifgoal = fe.outlook(ev["t"], ev["period"], sc, 1 - team, KICKOFF_ZONE)
            wk = "home_win" if team == 0 else "away_win"
            swing = ifgoal[wk] - before[wk]
            values = {**base, "outcome_key": ev["outcome"], "xg": f"{ev['xg']:.2f}", "before": pct(before[wk]),
                      "ifgoal": pct(ifgoal[wk]), "swing": f"{100 * swing:.1f}", "xgp": pct(ev["xg"])}
            return values, {"delta": swing, "allow": [], "before": before, "if_goal": ifgoal,
                            "summary": f"Counterfactual goal: {base['team']} {pct(before[wk])}% → {pct(ifgoal[wk])}% (+{100 * swing:.1f} pts)."}
        if kind == "turnover":
            im = self.ctx.impact(ev["event_id"])
            wk = im["win_key"]
            threat = im["after"]["threat"]
            if abs(im["delta_win"]) < 0.025 and threat < 0.04:
                return None, {"why": f"Swing {signed(im['delta_win'])} pts and threat {threat * 100:.1f}% are below "
                                     f"the newsworthy bar (2.5 pts or 4%). Not airing."}
            if abs(im["delta_win"]) >= 0.15 and abs(im["delta_win"]) > self.max_swing:
                allow.add("turning_point")
            values = {**base, "before": pct(im["before"][wk]), "after": pct(im["after"][wk]),
                      "delta_s": signed(im["delta_win"]), "threat": f"{threat * 100:.1f}",
                      "mult": f"{threat / max(fe.avg_threat, 1e-6):.1f}"}
            return values, {"impact": im, "delta": im["delta_win"], "allow": sorted(allow), "max_prev": self.max_swing,
                            "summary": f"{base['team']} win prob {pct(im['before'][wk])}% → {pct(im['after'][wk])}% "
                                       f"({signed(im['delta_win'])} pts); chance this possession scores {threat * 100:.1f}%."}
        if kind == "red":
            return base, {"delta": 0.0, "allow": [], "summary": "Fact only: numbers change. No forecast claim made."}
        if kind == "record_distance":
            ph = self.physical(ev["T"])
            top = ph["distance"][0]
            values = {"player": top["name"], "km": f"{top['km']:.1f}", "top": f"{top['top_kmh']:.1f}",
                      "eid": ev["event_id"], "_players": [top["player"]]}
            return values, {"delta": 0.0, "allow": [], "physical": ph,
                            "summary": f"Tracking: {top['name']} leads with {top['km']:.1f} km "
                                       f"(next {ph['distance'][1]['km']:.1f} km)."}
        if kind == "forecast":
            st = ev["state"]
            o = fe.outlook_from_state(st, ev["period"])
            variant, fv = forecast_values(o, st["score"], self.home, self.away)
            return {**fv, "eid": ev["event_id"]}, {"delta": 0.0, "allow": [], "outlook": o,
                                                    "summary": f"Exact solve: {fv['hw']} / {fv['dw']} / {fv['aw']}; "
                                                               f"most likely {fv['sl']} ({fv['slp']}%); "
                                                               f"goal in next 10' {fv['p10']}%."}
        if kind == "record_sprint":
            rec = cand["record"]
            values = {"player": self.pname(rec["player"]), "speed": f"{rec['value']:.1f}", "eid": ev["event_id"]}
            return values, {"delta": 0.0, "allow": ["record"], "record": rec,
                            "summary": f"Tracking confirms {rec['value']} km/h, the top speed so far."}
        if kind.startswith("record"):
            rec = cand["record"]
            values = {**base}
            if kind == "record_pass":
                values.update({"succ": pct(ev.get("success_prob", 0)), "diff": int(ev.get("pass_difficulty", 0))})
            else:
                values["speed"] = f"{rec['value']:.1f}"
            return values, {"delta": 0.0, "allow": ["record"], "record": rec,
                            "summary": f"Confirmed: new match record ({rec['value']}) held by {base['player']}."}
        if kind in ("control_take", "control_chaos"):
            ci = cand["control"]
            dom = self.club(ci["dominant"]) if ci.get("dominant") else self.home
            rate = ci["turnover_rate"]
            values = {"team": dom.name, "share": pct(ci.get("dominant_share", 0.5)), "idx": ci["index"],
                      "chain": f"{ci['chain_len']:.1f}", "rate": pct(rate), "press": pct(ci["pressure_share"]),
                      "every": max(2, int(round(1 / max(rate, 0.01)))), "eid": ev["event_id"]}
            return values, {"delta": 0.0, "allow": [], "control": ci,
                            "summary": f"Control index {ci['index']}/100, turnover rate {pct(rate)}%, "
                                       f"chain length {ci['chain_len']}."}
        if kind == "halftime":
            st = ev["state"]
            o = fe.outlook(2700.0, 2, st["score"], 1, KICKOFF_ZONE)
            _, fv = forecast_values(o, st["score"], self.home, self.away)
            values = {**fv, "score": f"{self.home.name} {st['score'][0]}–{st['score'][1]} {self.away.name}",
                      "home": self.home.name, "away": self.away.name, "hw": pct(o["home_win"]),
                      "dw": pct(o["draw"]), "aw": pct(o["away_win"]), "eid": ev["event_id"]}
            return values, {"delta": 0.0, "allow": [], "outlook": o,
                            "summary": f"Second-half outlook: {pct(o['home_win'])} / {pct(o['draw'])} / {pct(o['away_win'])}."}
        if kind == "fulltime":
            st = ev["state"]
            snap = self.interp.snapshot()["teams"]
            # only moments that actually changed the outlook; a missed chance's value is hypothetical
            scored = [c for c in self.cues if c["kind"] in ("goal", "turnover")]
            big = max(scored, key=lambda c: abs(c["evidence"].get("delta", 0)), default=None)
            values = {"home": self.home.name, "away": self.away.name, "hs": st["score"][0], "as_": st["score"][1],
                      "hxg": f"{snap[self.home.id]['xg']:.2f}", "axg": f"{snap[self.away.id]['xg']:.2f}",
                      "bigplayer": big["values"].get("player", "?") if big else "?",
                      "bigclock": big["clock"] if big else "-",
                      "bigdelta": signed(big["evidence"]["delta"]) if big else "0.0", "eid": ev["event_id"]}
            return values, {"delta": 0.0, "allow": ["biggest"], "big_cue": big["cue_id"] if big else None,
                            "summary": f"Ranked {len(scored)} measured moments; biggest swing {values['bigdelta']} pts."}
        return None, {"why": "Unknown moment type."}

    # ------------------------------------------------------------------ Narrator + Localizer
    def narrate(self, kind: str, ev: dict, values: dict, evidence: dict, plain: bool = False) -> tuple[dict, str]:
        texts: dict[str, dict[str, str]] = {}
        variant = values.get("variant")
        delta = abs(evidence.get("delta", 0.0))
        # the Narrator reaches for drama; the Skeptic decides whether the evidence allows it
        flourish = (not plain and kind in ("goal", "turnover") and delta >= 0.08 and int(ev["event_id"][1:]) % 2 == 0)
        note = " (with flourish)" if flourish else ""
        for lang in LANGS:
            texts[lang] = {}
            for lens in ("casual", "analyst"):
                if kind == "forecast":
                    texts[lang][lens] = render_story(f"forecast_{variant}", lang, lens, values)
                    continue
                line = render(kind, lang, lens, values)
                if flourish and lang == "en" and lens == "casual":
                    line += " That could be the turning point of the match."
                more = ""
                if kind in ("goal", "halftime") and variant:
                    more = render_story(f"after_{variant}", lang, lens, values)
                elif kind == "chance":
                    more = render("chance_more", lang, lens, values)
                elif kind == "turnover":
                    more = render("turnover_more", lang, lens, values)
                texts[lang][lens] = f"{line} {more}" if more else line
                if more:
                    texts[lang][f"{lens}_more"] = more  # the "what it means" sentence, shown as its own line
        if not plain and self.use_llm and kind in ("goal", "chance", "turnover"):
            rewritten = llm.rewrite(texts["en"]["casual"])
            if rewritten:
                texts["en"]["casual"] = rewritten
                note += " (model rewrite)"
        # club lens: same fact, framed for each club's fans
        tid = ev.get("team")
        for lang in LANGS:
            for c in self.clubs:
                if kind in ("goal", "turnover", "record_shot", "record_pass", "chance"):
                    good = (tid == c.id) if kind != "chance" else (tid != c.id)
                    sentiment = "good" if good else "bad"
                elif kind == "red":
                    sentiment = "bad" if tid == c.id else "good"
                else:
                    sentiment = "neutral"
                texts[lang][f"club:{c.id}"] = club_prefix(sentiment, lang, c.name) + texts[lang]["casual"]
        return texts, note

    # ------------------------------------------------------------------ Skeptic
    def skeptic(self, text: str, values: dict, evidence: dict, strict_words: bool = True) -> tuple[bool, str]:
        for eid in EID_RE.findall(text):
            if eid not in self.ctx.by_id:
                return False, f"cites unknown event {eid}"
        body = EID_RE.sub("", text)
        allowed = set()
        for v in values.values():
            allowed.update(NUM_RE.findall(str(v)))
        allowed.update({"1", "000", "100", "10"})  # "1,000" separators, "/100" scales, "next 10 minutes"
        for num in NUM_RE.findall(body):
            if num not in allowed and num.replace(",", ".") not in allowed:
                return False, f"number {num} is not in the evidence"
        if strict_words:
            low = text.lower()
            permits = set(evidence.get("allow", []))
            for phrase, need in GUARDED.items():
                if phrase in low and need not in permits:
                    if need == "turning_point":
                        d = abs(evidence.get("delta", 0)) * 100
                        prev = evidence.get("max_prev", 0) * 100
                        if d < 15:
                            return False, f"“turning point” needs a swing of at least 15 pts; measured {d:.1f}."
                        return False, (f"“turning point” must be the biggest swing so far; "
                                       f"{d:.1f} pts is below the {prev:.1f} pts measured earlier.")
                    return False, f"“{phrase}” is not supported by the evidence"
        return True, ""

    # ------------------------------------------------------------------ Director
    def director(self, kind: str, ev: dict, lane: str, cue_id: str, priority: int) -> bool:
        t = ev["T"]
        if kind in ALWAYS_AIR:
            self.last_main_t = t
            self.trace("Director", ev, f"Airing now ({self.overlay(kind)} overlay, priority {priority}).", cue=cue_id)
            return True
        if lane == "tag":
            if t - self.last_tag_t < TAG_GAP_S:
                self.dropped += 1
                self.trace("Director", ev, f"Held: a stat tag aired {t - self.last_tag_t:.0f} s ago.", status="drop", cue=cue_id)
                return False
            self.last_tag_t = t
            self.trace("Director", ev, "Airing as a player tag.", cue=cue_id)
            return True
        if t - self.last_main_t < MAIN_GAP_S:
            self.dropped += 1
            self.trace("Director", ev, f"Held: screen busy (last card {t - self.last_main_t:.0f} s ago).", status="drop", cue=cue_id)
            return False
        self.last_main_t = t
        self.trace("Director", ev, f"Airing ({self.overlay(kind)} overlay, priority {priority}).", cue=cue_id)
        return True

    @staticmethod
    def overlay(kind: str) -> str:
        return {"goal": "impact", "chance": "impact", "turnover": "impact", "red": "banner", "halftime": "banner",
                "fulltime": "banner", "control_take": "meter", "control_chaos": "meter",
                "forecast": "forecast"}.get(kind, "tag")

    @staticmethod
    def duration(kind: str) -> float:
        return {"goal": 11.0, "halftime": 10.0, "fulltime": 12.0, "red": 7.0, "forecast": 11.0,
                "chance": 9.0, "turnover": 9.0}.get(kind, 6.0 if kind.startswith("record") else 7.0)

    # ------------------------------------------------------------------ reporting
    def ops(self) -> dict:
        lat = sorted(self.latencies)
        p99 = lat[min(len(lat) - 1, int(0.99 * len(lat)))] if lat else 0.0
        return {"type": "ops", "cues_aired": len(self.cues), "rejected": self.rejections, "held": self.dropped,
                "latency_p50_ms": round(median(lat), 1) if lat else 0.0, "latency_p99_ms": round(p99, 1),
                "forks_run": self.forks_run, "model": "foundry" if self.use_llm else "templates"}

    def recap(self, lang: str = "en") -> dict:
        ft = next((c for c in self.cues if c["kind"] == "fulltime"), None)
        moments = sorted([c for c in self.cues if c["kind"] in ("goal", "turnover")],
                         key=lambda c: abs(c["evidence"].get("delta", 0)), reverse=True)[:5]
        moments = sorted(moments, key=lambda c: (c["period"], c["t"]))
        chances = sorted([c for c in self.cues if c["kind"] == "chance"],
                         key=lambda c: c["evidence"].get("delta", 0), reverse=True)[:3]
        snap = self.interp.snapshot()
        return {
            "lang": lang,
            "headline": ft["text"][lang]["casual"] if ft else "",
            "analyst": ft["text"][lang]["analyst"] if ft else "",
            "moments": [{"clock": c["clock"], "event_id": c["event_id"], "kind": c["kind"],
                         "delta": c["evidence"].get("delta", 0), "line": c["text"][lang]["casual"]} for c in moments],
            "stats": snap["teams"],
            "missed_chances": [{"clock": c["clock"], "event_id": c["event_id"], "goal_value": c["evidence"].get("delta", 0),
                                "line": c["text"][lang]["casual"]} for c in chances],
            "highlights": [{"event_id": c["event_id"], "t": c["t"], "period": c["period"], "clock": c["clock"],
                            "kind": c["kind"]} for c in sorted(moments + chances, key=lambda c: (c["period"], c["t"]))],
        }


def pundit_duel(ctx: MatchContext, event_id: str) -> dict:
    """Two pundits argue; the simulator referees with measured evidence."""
    cf = ctx.counterfactual(event_id)
    ev = ctx.events[ctx.by_id[event_id]]
    team = cf["team_index"]
    club = ctx.match.home if team == 0 else ctx.match.away
    name = ctx.players.get(ev["player"], {}).get("name", "?")
    safe, direct = cf.get("safe"), cf.get("direct")
    if not safe or not direct:
        raise ValueError("No clear safe/direct alternatives from this position.")
    purist = (f"Keep it. The {safe['length']:.0f} m pass lands {pct(safe['success_prob'])}% of the time and keeps "
              f"{club.name} on {safe['win_prob'] * 100:.1f}% to win.")
    direct_line = (f"Go for it. The {direct['length']:.0f} m ball forward lands {pct(direct['success_prob'])}% of the time, "
                   f"and if it does this attack scores {direct['threat'] / max(direct['success_prob'], 1e-6) * 100:.1f}% of the time.")
    diff = direct["exp_points"] - safe["exp_points"]
    winner = "The Direct One" if diff > 0 else "The Purist"
    verdict = (f"Simulator: {winner} wins. Over 100 moments like this, going direct is worth "
               f"{diff * 100:+.1f} points versus keeping it (exact solve over the remaining match).")
    actual_ep = cf["actual"]["exp_points"]
    did = "kept it" if ev["type"] == "pass" and (ev.get("pass_length") or 0) <= 18 else "went another way"
    return {
        "event_id": event_id, "player": name, "team": club.name, "clock": ev["clock"],
        "pundits": [
            {"name": "The Purist", "style": "possession", "line": purist, "option": safe},
            {"name": "The Direct One", "style": "direct", "line": direct_line, "option": direct},
        ],
        "verdict": verdict, "winner": winner, "delta_points_per_100": round(diff * 100, 2),
        "actual": {"note": f"{name} {did}.", "exp_points": actual_ep},
        "counterfactual": cf,
    }
