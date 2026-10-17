"""Seeded synthetic match engine.

Generates football-realistic event streams for two fictional clubs. The same
probability functions are reused by the fork engine and the counterfactual
tools, so the data, the forecasts and the explanations share one world model.

Coordinates: absolute pitch metres, x in [0, 105], y in [0, 68]. The home club
attacks towards x = 105. Inside the simulation we work in the *attacking frame*
of the team in possession: ``ap`` is metres of progress towards the opponent goal.
"""
from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass, field

from .world import CLUBS, Club, Player, PITCH_LENGTH as L, PITCH_WIDTH as W

# Zones used by the fork engine: 6 progress bands x 3 lateral channels = 18 zones.
PROGRESS_EDGES = [0.20, 0.35, 0.50, 0.65, 0.80]
N_PROGRESS = 6
N_LATERAL = 3
N_ZONES = N_PROGRESS * N_LATERAL
KICKOFF_ZONE = 3 * N_LATERAL + 1  # progress 0.5, central channel

ON_BALL = {"pass", "carry", "cross", "shot"}


def zone_of(ap: float, y: float) -> int:
    pb = bisect.bisect_right(PROGRESS_EDGES, max(0.0, min(0.999, ap / L)))
    lb = min(N_LATERAL - 1, max(0, int(y / (W / N_LATERAL))))
    return pb * N_LATERAL + lb


def zone_center(z: int) -> tuple[float, float]:
    pb, lb = divmod(z, N_LATERAL)
    edges = [0.0] + PROGRESS_EDGES + [1.0]
    return (edges[pb] + edges[pb + 1]) / 2 * L, (lb + 0.5) * W / N_LATERAL


def sigmoid(v: float) -> float:
    return 1.0 / (1.0 + math.exp(-v))


def pass_success_prob(q_diff: float, length: float, pressure: bool, p_start: float, p_end: float) -> float:
    """Probability a pass is completed. Shared with the counterfactual engine."""
    logit = (
        3.05
        + 2.0 * q_diff
        - 0.047 * length
        - 0.75 * (1.0 if pressure else 0.0)
        - 2.4 * max(0.0, p_end - 0.72)
        + 0.5 * max(0.0, 0.5 - p_start)
    )
    return sigmoid(logit)


def shot_xg(ap: float, y: float, header: bool = False, pressure: bool = False) -> float:
    """Expected goals from distance and goal-mouth angle (attacking frame)."""
    dx = L - ap
    dy = y - W / 2
    d = math.hypot(dx, dy)
    a1 = math.atan2(W / 2 + 3.66 - y, max(dx, 0.1))
    a2 = math.atan2(W / 2 - 3.66 - y, max(dx, 0.1))
    angle = abs(a1 - a2)
    xg = 0.58 * sigmoid(-1.25 + 1.7 * angle - 0.085 * d)
    if header:
        xg *= 0.6
    if pressure:
        xg *= 0.78
    return max(0.01, min(0.85, xg))


def pressure_prob(p: float, opp_press: float) -> float:
    return 0.18 + 0.38 * opp_press * (1.0 - p) + 0.22 * p


@dataclass
class Match:
    match_id: str
    seed: int
    home: Club
    away: Club
    events: list[dict] = field(default_factory=list)
    score: list[int] = field(default_factory=lambda: [0, 0])

    def meta(self) -> dict:
        return {
            "match_id": self.match_id,
            "seed": self.seed,
            "home": self.home.to_dict(),
            "away": self.away.to_dict(),
            "pitch": {"length": L, "width": W},
            "final_score": self.score,
            "n_events": len(self.events),
        }


def clock_label(t: float, period: int) -> str:
    base = 0 if period == 1 else 2700
    regular_end = 2700 if period == 1 else 5400
    if t <= regular_end:
        m = int(t // 60)
        s = int(t % 60)
        return f"{m:02d}:{s:02d}"
    extra = t - regular_end
    return f"{regular_end // 60}+{int(extra // 60) + 1}"


class MatchSim:
    def __init__(self, home: Club, away: Club, seed: int):
        self.home = home
        self.away = away
        self.clubs = [home, away]
        self.seed = seed
        self.rng = random.Random(seed)
        self.match_id = f"{home.id}-{away.id}-{seed}"
        self.xi = [list(home.players), list(away.players)]
        self.bench = [list(home.bench), list(away.bench)]
        self.cards: dict[str, int] = {}
        self.sent_off: set[str] = set()
        self.events: list[dict] = []
        self.score = [0, 0]
        self.t = 0.0
        self.period = 1
        self.poss = 0
        self.ap = L / 2
        self.y = W / 2
        self.chain = 1
        self.carrier: Player | None = None
        self.subs_done = [0, 0]
        self.sub_times = [
            sorted(self.rng.uniform(56, 82) * 60 for _ in range(3)),
            sorted(self.rng.uniform(56, 82) * 60 for _ in range(3)),
        ]

    # ------------------------------------------------------------------ helpers
    def to_abs(self, team: int, ap: float) -> float:
        return ap if team == 0 else L - ap

    def active(self, team: int) -> list[Player]:
        return [p for p in self.xi[team] if p.id not in self.sent_off]

    def block_positions(self, team: int, ball_ap: float, ball_y: float, attacking: bool):
        """Approximate player positions in the team's own attacking frame."""
        shift = (ball_ap / L - (0.45 if attacking else 0.55)) * 36.0
        out = []
        for pl in self.active(team):
            if pl.role == "GK":
                px = pl.base_x * L + max(0.0, shift * 0.15)
            else:
                px = pl.base_x * L + shift
            py = pl.base_y * W * 0.75 + ball_y * 0.25
            out.append((pl, max(1.0, min(L - 1, px)), max(1.0, min(W - 1, py))))
        return out

    def nearest(self, team: int, ap: float, y: float, attacking: bool, exclude: Player | None = None,
                allow_gk: bool = False, ref_ball=None) -> Player:
        bap, by = ref_ball if ref_ball else (ap, y)
        best, bd = None, 1e9
        for pl, px, py in self.block_positions(team, bap, by, attacking):
            if pl is exclude or (pl.role == "GK" and not allow_gk):
                continue
            d = (px - ap) ** 2 + (py - y) ** 2
            if d < bd:
                best, bd = pl, d
        return best or self.active(team)[0]

    def emit(self, **kw) -> dict:
        team = kw.get("team")
        ev = {
            "event_id": f"e{len(self.events) + 1:05d}",
            "match_id": self.match_id,
            "seq": len(self.events) + 1,
            "t": round(self.t, 2),
            "clock": clock_label(self.t, self.period),
            "period": self.period,
            "team": self.clubs[team].id if team is not None else None,
            "player": None,
            "type": kw.pop("type"),
            "x": None,
            "y": None,
            "end_x": None,
            "end_y": None,
            "outcome": None,
            "pressure": False,
            "body_part": None,
            "speed_kmh": None,
            "chain_id": self.chain,
            "tags": [],
        }
        kw.pop("team", None)
        ev.update(kw)
        for k in ("x", "y", "end_x", "end_y", "speed_kmh", "xg", "pass_length"):
            if ev.get(k) is not None:
                ev[k] = round(float(ev[k]), 3 if k == "xg" else 1)
        ev["state"] = {
            "score": list(self.score),
            "poss": self.poss,
            "ap": round(self.ap, 1),
            "y": round(self.y, 1),
            "zone": zone_of(self.ap, self.y),
            "t": round(self.t, 2),
            "red": [sum(1 for p in self.xi[i] if p.id in self.sent_off) for i in (0, 1)],
        }
        self.events.append(ev)
        return ev

    def change_poss(self, new_ap: float, new_y: float, new_carrier: Player | None):
        self.poss = 1 - self.poss
        self.ap = max(1.0, min(L - 1.0, new_ap))
        self.y = max(1.0, min(W - 1.0, new_y))
        self.carrier = new_carrier
        self.chain += 1

    # ------------------------------------------------------------------ actions
    def kickoff(self, team: int):
        self.poss = team
        self.ap, self.y = L / 2, W / 2
        self.chain += 1
        st = next(p for p in self.active(team) if p.role in ("ST", "CM", "DM"))
        self.carrier = st
        self.emit(type="kickoff", team=team, player=st.id, x=L / 2, y=W / 2)

    def do_pass(self, team: int, carrier: Player, pressure: bool, long_ball: bool, through_box: bool = False):
        s = self.clubs[team].style
        o = self.clubs[1 - team].style
        rng = self.rng
        p = self.ap / L
        if long_ball:
            length = rng.uniform(24, 48)
            theta = rng.gauss(0.0, 0.45)
        else:
            length = rng.uniform(6, 21) if p < 0.75 else rng.uniform(5, 15)
            theta = rng.gauss(0.15 * (s.directness - 0.5), 1.25 - 0.45 * s.directness)
        # width preference pulls passes towards the flanks
        tx = self.ap + length * math.cos(theta)
        ty = self.y + length * math.sin(theta)
        if rng.random() < s.width * 0.35:
            ty += (rng.choice([-1, 1])) * rng.uniform(4, 12)
        tx = max(2.0, min(L - 7.0, tx))
        ty = max(2.0, min(W - 2.0, ty))
        length = math.hypot(tx - self.ap, ty - self.y)
        prob = pass_success_prob(s.quality - o.quality, length, pressure, p, tx / L)
        speed = 22 + length * 1.25 + rng.uniform(-4, 6)
        dt = 1.0 + length / 15 + (1 - s.tempo) * 2.2 + rng.uniform(0, 1.4)
        x0, y0 = self.to_abs(team, self.ap), self.y
        x1 = self.to_abs(team, tx)
        tags = ["long_ball"] if long_ball else []
        if tx / L > 0.8 and self.ap / L <= 0.8:
            tags.append("final_third_entry")
        if rng.random() < prob:
            recv = self.nearest(team, tx, ty, True, exclude=carrier, allow_gk=tx < 12, ref_ball=(tx, ty))
            self.t += dt
            self.ap, self.y, self.carrier = tx, ty, recv
            self.emit(type="pass", team=team, player=carrier.id, receiver=recv.id, x=x0, y=y0, end_x=x1, end_y=ty,
                      outcome="complete", pressure=pressure, speed_kmh=speed, pass_length=length,
                      pass_difficulty=round((1 - prob) * 100), success_prob=round(prob, 3), tags=tags)
            return
        self.t += dt
        if rng.random() < 0.17:
            # out of play: throw-in or goal kick to the opponent
            out_y = 0.5 if ty < W / 2 else W - 0.5
            self.emit(type="pass", team=team, player=carrier.id, x=x0, y=y0, end_x=x1, end_y=out_y,
                      outcome="out", pressure=pressure, speed_kmh=speed, pass_length=length,
                      pass_difficulty=round((1 - prob) * 100), success_prob=round(prob, 3), tags=tags)
            opp = 1 - team
            nap = L - tx
            taker = self.nearest(opp, nap, out_y, True, ref_ball=(nap, out_y))
            self.t += rng.uniform(10, 18)
            self.change_poss(nap, out_y, taker)
            self.emit(type="throw_in", team=opp, player=taker.id, x=self.to_abs(opp, nap), y=out_y)
            return
        f = rng.uniform(0.5, 1.0)
        ix = self.ap + (tx - self.ap) * f
        iy = self.y + (ty - self.y) * f
        self.emit(type="pass", team=team, player=carrier.id, x=x0, y=y0, end_x=self.to_abs(team, ix), end_y=iy,
                  outcome="intercepted", pressure=pressure, speed_kmh=speed, pass_length=length,
                  pass_difficulty=round((1 - prob) * 100), success_prob=round(prob, 3), tags=tags)
        opp = 1 - team
        dfd = self.nearest(opp, L - ix, iy, False, ref_ball=(L - ix, iy))
        self.change_poss(L - ix, iy, dfd)
        self.t += rng.uniform(0.3, 1.0)
        self.emit(type="interception", team=opp, player=dfd.id, x=self.to_abs(opp, self.ap), y=self.y,
                  outcome="won", tags=["high_turnover"] if self.ap / L > 0.6 else [])

    def do_carry(self, team: int, carrier: Player, pressure: bool):
        s = self.clubs[team].style
        o = self.clubs[1 - team].style
        rng = self.rng
        p = self.ap / L
        length = rng.uniform(4, 15)
        theta = rng.gauss(0, 0.55)
        tx = max(2.0, min(L - 8.0, self.ap + length * math.cos(theta)))
        ty = max(2.0, min(W - 2.0, self.y + length * math.sin(theta)))
        prob = sigmoid(2.1 + 1.6 * (s.quality - o.quality) - 1.0 * pressure - 1.3 * max(0.0, p - 0.65))
        speed = rng.uniform(0.62, 1.0) * carrier.top_speed
        dt = max(1.5, length / (speed / 3.6)) + rng.uniform(0.2, 1.2)
        x0, y0 = self.to_abs(team, self.ap), self.y
        tags = []
        if speed >= 31.0:
            tags.append("sprint")
        self.t += dt
        if rng.random() < prob:
            self.ap, self.y = tx, ty
            self.emit(type="carry", team=team, player=carrier.id, x=x0, y=y0, end_x=self.to_abs(team, tx), end_y=ty,
                      outcome="complete", pressure=pressure, speed_kmh=speed, tags=tags)
            return
        opp = 1 - team
        dfd = self.nearest(opp, L - self.ap, self.y, False)
        foul_p = 0.17 + 0.25 * self.clubs[opp].style.press
        if rng.random() < foul_p:
            self.emit(type="carry", team=team, player=carrier.id, x=x0, y=y0, end_x=x0, end_y=y0,
                      outcome="fouled", pressure=True, speed_kmh=speed, tags=tags)
            self.foul(opp, dfd, team, carrier)
            return
        self.emit(type="carry", team=team, player=carrier.id, x=x0, y=y0, end_x=x0, end_y=y0,
                  outcome="dispossessed", pressure=True, speed_kmh=speed, tags=tags)
        self.change_poss(L - self.ap, self.y, dfd)
        self.t += rng.uniform(0.3, 1.0)
        self.emit(type="tackle", team=opp, player=dfd.id, x=self.to_abs(opp, self.ap), y=self.y, outcome="won",
                  tags=["high_turnover"] if self.ap / L > 0.6 else [])

    def foul(self, fouling_team: int, fouler: Player, fouled_team: int, victim: Player):
        rng = self.rng
        self.t += rng.uniform(1, 2)
        ev = self.emit(type="foul", team=fouling_team, player=fouler.id, victim=victim.id,
                       x=self.to_abs(fouled_team, self.ap), y=self.y)
        card = None
        r = rng.random()
        if r < 0.004:
            card = "red"
        elif r < 0.17:
            card = "yellow"
            self.cards[fouler.id] = self.cards.get(fouler.id, 0) + 1
            if self.cards[fouler.id] >= 2:
                card = "second_yellow"
        if card:
            self.t += rng.uniform(15, 35)
            tags = ["red_card"] if card in ("red", "second_yellow") else []
            self.emit(type="card", team=fouling_team, player=fouler.id, outcome=card, tags=tags,
                      x=ev["x"], y=ev["y"])
            if card in ("red", "second_yellow"):
                self.sent_off.add(fouler.id)
        self.t += rng.uniform(8, 20)
        # free kick to the fouled team
        self.emit(type="free_kick", team=fouled_team, player=victim.id, x=self.to_abs(fouled_team, self.ap), y=self.y)
        self.carrier = victim
        if self.ap / L > 0.74 and abs(self.y - W / 2) < 18 and rng.random() < 0.45:
            self.do_shot(fouled_team, victim, False, set_piece="free_kick")

    def do_cross(self, team: int, carrier: Player, pressure: bool, from_corner: bool = False):
        s = self.clubs[team].style
        o = self.clubs[1 - team].style
        rng = self.rng
        x0, y0 = self.to_abs(team, self.ap), self.y
        tx, ty = rng.uniform(93, 101), rng.uniform(27, 41)
        prob = 0.17 + 0.4 * (s.quality - o.quality) - (0.05 if pressure else 0.0) + (0.04 if from_corner else 0)
        self.t += rng.uniform(1.5, 3.0)
        if rng.random() < prob:
            recv = self.nearest(team, tx, ty, True, exclude=carrier, ref_ball=(tx, ty))
            self.ap, self.y, self.carrier = tx, ty, recv
            self.emit(type="cross", team=team, player=carrier.id, receiver=recv.id, x=x0, y=y0,
                      end_x=self.to_abs(team, tx), end_y=ty, outcome="complete", pressure=pressure,
                      speed_kmh=rng.uniform(55, 80), tags=["corner"] if from_corner else [])
            self.do_shot(team, recv, rng.random() < 0.5, header_possible=True)
            return
        self.emit(type="cross", team=team, player=carrier.id, x=x0, y=y0, end_x=self.to_abs(team, tx), end_y=ty,
                  outcome="cleared", pressure=pressure, speed_kmh=rng.uniform(55, 80),
                  tags=["corner"] if from_corner else [])
        opp = 1 - team
        dfd = self.nearest(opp, L - tx, ty, False, ref_ball=(L - tx, ty))
        if rng.random() < 0.28:
            self.corner(team)
            return
        clear_to = (L - tx) + rng.uniform(15, 40)
        self.change_poss(clear_to, rng.uniform(10, W - 10), None)
        self.t += rng.uniform(1.5, 3)
        self.emit(type="clearance", team=opp, player=dfd.id, x=self.to_abs(opp, L - tx), y=ty,
                  end_x=self.to_abs(opp, self.ap), end_y=self.y)
        # loose clearance: 45% recovered by the attackers
        if rng.random() < 0.45:
            rec = self.nearest(team, L - self.ap, self.y, True, ref_ball=(L - self.ap, self.y))
            self.change_poss(L - self.ap, self.y, rec)
            self.emit(type="recovery", team=team, player=rec.id, x=self.to_abs(team, self.ap), y=self.y)
        else:
            self.carrier = self.nearest(opp, self.ap, self.y, True, ref_ball=(self.ap, self.y))

    def corner(self, team: int):
        rng = self.rng
        side = rng.choice([0.5, W - 0.5])
        self.ap, self.y = L - 0.5, side
        self.t += rng.uniform(18, 30)
        taker = next((p for p in self.active(team) if p.role in ("RW", "LW", "CM")), self.active(team)[1])
        self.carrier = taker
        self.emit(type="corner", team=team, player=taker.id, x=self.to_abs(team, self.ap), y=side)
        self.do_cross(team, taker, False, from_corner=True)

    def do_shot(self, team: int, shooter: Player, pressure: bool, header_possible: bool = False,
                set_piece: str | None = None):
        s = self.clubs[team].style
        rng = self.rng
        header = header_possible and rng.random() < 0.55
        xg = shot_xg(self.ap, self.y, header, pressure)
        if set_piece == "free_kick":
            xg = min(xg, 0.07)
        goal_p = xg * (0.7 + 0.5 * s.finishing)  # xG is calibrated: finishing 0.6 -> 1.0x
        speed = rng.uniform(42, 72) if header else rng.uniform(64, 121)
        x0, y0 = self.to_abs(team, self.ap), self.y
        gx = self.to_abs(team, L)
        self.t += rng.uniform(0.5, 1.5)
        tags = []
        if xg >= 0.3:
            tags.append("big_chance")
        if speed >= 105:
            tags.append("rocket")
        if set_piece:
            tags.append(set_piece)
        r = rng.random()
        common = dict(type="shot", team=team, player=shooter.id, x=x0, y=y0, end_x=gx,
                      pressure=pressure, body_part="head" if header else "foot", speed_kmh=speed, xg=xg)
        if r < goal_p:
            self.score[team] += 1
            self.emit(**common, end_y=W / 2 + rng.uniform(-3, 3), outcome="goal", tags=tags + ["goal"])
            self.t += rng.uniform(45, 70)
            self.kickoff(1 - team)
            return
        on_target_p = min(0.95, max(0.0, (0.34 - goal_p) / max(0.05, 1 - goal_p)))
        r2 = rng.random()
        opp = 1 - team
        if r2 < on_target_p:
            gk = next(p for p in self.active(opp) if p.role == "GK") if any(
                p.role == "GK" for p in self.active(opp)) else self.active(opp)[0]
            self.emit(**common, end_y=W / 2 + rng.uniform(-3, 3), outcome="saved", tags=tags, goalkeeper=gk.id)
            if rng.random() < 0.33:
                self.corner(team)
            else:
                self.t += rng.uniform(4, 10)
                self.change_poss(6.0, W / 2, gk)
                self.emit(type="goalkeeper", team=opp, player=gk.id, x=self.to_abs(opp, 6.0), y=W / 2, outcome="claim")
        elif r2 < on_target_p + 0.27:
            self.emit(**common, end_y=y0, outcome="blocked", tags=tags)
            if rng.random() < 0.5:
                self.ap = max(60.0, self.ap - rng.uniform(5, 15))
                self.carrier = self.nearest(team, self.ap, self.y, True)
                self.t += rng.uniform(1, 2)
                self.emit(type="recovery", team=team, player=self.carrier.id, x=self.to_abs(team, self.ap), y=self.y)
            else:
                dfd = self.nearest(opp, L - self.ap, self.y, False)
                self.change_poss(L - self.ap + 3, self.y, dfd)
                self.t += rng.uniform(1, 2)
                self.emit(type="recovery", team=opp, player=dfd.id, x=self.to_abs(opp, self.ap), y=self.y)
        else:
            miss_y = W / 2 + rng.choice([-1, 1]) * rng.uniform(4.0, 9.0)
            self.emit(**common, end_y=miss_y, outcome="off_target", tags=tags)
            self.t += rng.uniform(18, 30)
            gk = next((p for p in self.active(opp) if p.role == "GK"), self.active(opp)[0])
            self.change_poss(6.0, W / 2, gk)
            self.emit(type="goal_kick", team=opp, player=gk.id, x=self.to_abs(opp, 6.0), y=W / 2)

    def maybe_sub(self):
        for team in (0, 1):
            while self.subs_done[team] < 3 and self.t >= self.sub_times[team][self.subs_done[team]] and self.period == 2:
                idx = self.subs_done[team]
                on = self.bench[team][idx]
                candidates = [p for p in self.active(team) if p.role == on.role] or [
                    p for p in self.active(team) if p.role != "GK"]
                off = self.rng.choice(candidates)
                i = self.xi[team].index(off)
                new = Player(on.id, on.name, on.short, on.number, off.role, off.base_x, off.base_y, on.top_speed)
                self.xi[team][i] = new
                if self.carrier is off:
                    self.carrier = new
                self.subs_done[team] += 1
                self.emit(type="substitution", team=team, player=new.id, player_off=off.id)

    # ------------------------------------------------------------------ main loop
    def run(self) -> Match:
        rng = self.rng
        end1 = 2700 + rng.uniform(60, 240)
        end2 = 5400 + rng.uniform(120, 330)
        self.emit(type="period_start", team=None)
        self.kickoff(0)
        while True:
            end = end1 if self.period == 1 else end2
            if self.t >= end:
                self.emit(type="period_end", team=None)
                if self.period == 1:
                    self.period = 2
                    self.t = 2700.0
                    self.emit(type="period_start", team=None)
                    self.kickoff(1)
                    continue
                self.emit(type="full_time", team=None, outcome=f"{self.score[0]}-{self.score[1]}")
                break
            self.maybe_sub()
            team = self.poss
            s = self.clubs[team].style
            o = self.clubs[1 - team].style
            carrier = self.carrier if self.carrier and self.carrier.id not in self.sent_off else None
            if carrier is None or carrier not in self.active(team):
                carrier = self.nearest(team, self.ap, self.y, True, allow_gk=self.ap < 10)
                self.carrier = carrier
            p = self.ap / L
            c = 1.0 - abs(self.y - W / 2) / (W / 2)
            # a red card weakens a side: fewer players, more pressure
            red_pen = 0.06 * (len(self.xi[team]) - len(self.active(team)))
            pressure = rng.random() < pressure_prob(p, o.press) + red_pen
            shoot_p = 0.0 if p < 0.72 else (0.018 + 0.054 * (p - 0.72) / 0.28) * (0.2 + 0.8 * c)
            cross_p = 0.24 * (0.5 + s.width) if (p > 0.74 and c < 0.45) else 0.0
            carry_p = 0.16 + 0.1 * (1 - s.directness)
            if pressure and rng.random() < 0.013:
                opp = 1 - team
                self.foul(opp, self.nearest(opp, L - self.ap, self.y, False), team, carrier)
                continue
            r = rng.random()
            if r < shoot_p:
                self.do_shot(team, carrier, pressure)
            elif r < shoot_p + cross_p:
                self.do_cross(team, carrier, pressure)
            elif r < shoot_p + cross_p + carry_p:
                self.do_carry(team, carrier, pressure)
            else:
                long_ball = p < 0.62 and rng.random() < s.directness * 0.32
                self.do_pass(team, carrier, pressure, long_ball)
        return Match(self.match_id, self.seed, self.home, self.away, self.events, list(self.score))


def simulate(home_id: str = "kes", away_id: str = "amb", seed: int = 1) -> Match:
    return MatchSim(CLUBS[home_id], CLUBS[away_id], seed).run()
