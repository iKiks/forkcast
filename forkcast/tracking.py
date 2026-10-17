"""Physical layer: 5 Hz tracking for 22 players and the ball, synthesized from the event stream.

The event engine decides *what* happens; this layer decides *how it looks*:

* the ball travels between events at its recorded speed, with an arc for long balls,
  crosses and clearances, and is placed for restarts;
* the player who acts next runs onto the ball so he arrives as it does;
* the player on the ball dribbles with it;
* the nearest defenders press, the rest hold a team shape that slides with the ball,
  squeezes when defending and stays in their own half for kickoffs;
* every player is moved by a speed- and acceleration-limited model, so the speeds and
  distances it reports are physically plausible.

Output arrays are indexed by frame; frames are 0.2 s of match time on a monotonic
timeline ``T`` (second half starts a few seconds after the first half ends).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .world import FORMATION_433, PITCH_LENGTH as L, PITCH_WIDTH as W

DT = 0.2
HALFTIME_GAP = 12.0
POSSESSION_TYPES = {"pass", "carry", "cross", "shot", "kickoff", "throw_in", "free_kick", "corner", "goal_kick",
                    "goalkeeper", "interception", "tackle", "recovery", "clearance"}
NO_BALL = {"substitution", "period_start", "period_end", "full_time"}
MODE_CRUISE, MODE_RUNNER, MODE_FOLLOW, MODE_PRESS, MODE_OFF = 0, 1, 2, 3, 4


def assign_T(events: list[dict]) -> float:
    """Add a monotonic timeline ``T`` (seconds) to every event; return the T where the second half starts."""
    p1_end = max(e["t"] for e in events if e["period"] == 1)
    p2_start = p1_end + HALFTIME_GAP
    for e in events:
        e["T"] = round(e["t"] if e["period"] == 1 else p2_start + (e["t"] - 2700.0), 2)
    return p2_start


@dataclass
class Tracking:
    T: np.ndarray  # (F,)
    ball: np.ndarray  # (F, 3) x, y, z (height, metres)
    pos: np.ndarray  # (F, 22, 2)
    speed: np.ndarray  # (F, 22) km/h
    dist: np.ndarray  # (F, 22) cumulative metres
    active: np.ndarray  # (F, 22) bool, on the pitch
    slot_changes: list  # [(T, slot, player_id)]
    initial_slots: list  # 22 player ids
    records: list  # [(T, slot, player_id, km/h)] new top-speed records
    p2_start: float

    def frame_at(self, T: float) -> int:
        return int(min(len(self.T) - 1, max(0, np.searchsorted(self.T, T))))

    def slots_at(self, T: float) -> list[str]:
        slots = list(self.initial_slots)
        for tc, s, pid in self.slot_changes:
            if tc <= T:
                slots[s] = pid
        return slots

    def chunk(self, T0: float, T1: float) -> dict:
        """Frames with T0 < T <= T1, compact enough to stream."""
        a = int(np.searchsorted(self.T, T0, side="right"))
        b = int(np.searchsorted(self.T, T1, side="right"))
        if b <= a:
            return {}
        return {
            "T": [round(float(t), 2) for t in self.T[a:b]],
            "ball": np.round(self.ball[a:b], 2).tolist(),
            "pos": np.round(self.pos[a:b], 2).reshape(b - a, -1).tolist(),
            "on": self.active[b - 1].astype(int).tolist(),
            "slots": self.slots_at(float(self.T[b - 1])),
        }

    def physical(self, T: float) -> dict:
        """Distance and top speed per player id up to time T."""
        f = self.frame_at(T)
        top = self.speed[: f + 1].max(axis=0)
        out: dict[str, dict] = {}
        slots = list(self.initial_slots)
        changes = sorted(self.slot_changes)
        # attribute distance before a substitution to the player who left
        seg_start = {s: 0 for s in range(22)}
        for tc, s, pid in changes:
            if tc > T:
                break
            fc = self.frame_at(tc)
            old = slots[s]
            out[old] = {"km": round(float(self.dist[fc, s] - self.dist[seg_start[s], s]) / 1000, 2),
                        "top_kmh": round(float(self.speed[seg_start[s]: fc + 1, s].max()), 1)}
            slots[s] = pid
            seg_start[s] = fc
        for s in range(22):
            pid = slots[s]
            out[pid] = {"km": round(float(self.dist[f, s] - self.dist[seg_start[s], s]) / 1000, 2),
                        "top_kmh": round(float(self.speed[seg_start[s]: f + 1, s].max()), 1)}
        del top
        return out


def _ball_moves(bev: list[dict]) -> list[tuple]:
    """Ball moves (T0, T1, x0, y0, x1, y1, peak) between consecutive ball-located events."""
    moves = []
    for i, e in enumerate(bev):
        T0 = e["T"]
        Tn = bev[i + 1]["T"] if i + 1 < len(bev) else T0 + 2
        gap = max(0.05, Tn - T0)
        x0, y0 = e["x"], e["y"]
        ex, ey = (e["end_x"], e["end_y"]) if e.get("end_x") is not None else (x0, y0)
        length = math.hypot(ex - x0, ey - y0)
        if length > 0.3:
            typ = e["type"]
            if typ == "carry":
                v = max(3.0, (e.get("speed_kmh") or 20) / 3.6)
            elif typ == "clearance":
                v = 22.0
            else:
                v = max(9.0, (e.get("speed_kmh") or 45) / 3.6)
            dur = min(length / v, 0.92 * gap)
            if typ == "cross":
                peak = 2.2 + length * 0.05
            elif typ == "clearance":
                peak = min(14.0, 4 + length * 0.18)
            elif typ == "pass" and (length > 26 or "long_ball" in e.get("tags", [])):
                peak = min(10.0, length * 0.16)
            elif typ == "shot":
                peak = 0.0 if e.get("body_part") == "head" else 0.6
            else:
                peak = 0.0
            moves.append((T0, T0 + dur, x0, y0, ex, ey, peak))
            T_arr = T0 + dur
        else:
            T_arr = T0
        if i + 1 < len(bev):
            nx, ny = bev[i + 1]["x"], bev[i + 1]["y"]
            if math.hypot(nx - ex, ny - ey) > 1.0:
                # restart or dribble to the next action: placed (dead ball) or rolled (live)
                span = min(1.4, max(0.1, Tn - T_arr))
                moves.append((Tn - span, Tn, ex, ey, nx, ny, 0.0))
    moves.sort(key=lambda m: m[0])
    return moves


def build(events: list[dict], home, away, seed: int) -> Tracking:
    p2_start = assign_T(events)
    T_end = events[-1]["T"] + 2.0
    Tg = np.round(np.arange(0.0, T_end, DT), 2)
    F = len(Tg)
    rng = np.random.default_rng(seed + 991)

    # ------------------------------------------------------------ slots and lineups
    clubs = (home, away)
    initial = [p.id for p in home.players] + [p.id for p in away.players]
    roles = [r for r, _, _ in FORMATION_433] * 2
    base = np.array([[bx, by] for _, bx, by in FORMATION_433] * 2)
    team = np.array([0] * 11 + [1] * 11)
    vmax = np.array([p.top_speed for p in home.players] + [p.top_speed for p in away.players]) / 3.6
    is_gk = np.array([r == "GK" for r in roles])
    is_cb = np.array([r == "CB" for r in roles])
    slot_of = {pid: i for i, pid in enumerate(initial)}
    slot_changes = []
    off_from = np.full(22, np.inf)
    ev_slot = []
    for e in events:
        if e["type"] == "substitution":
            s = slot_of.get(e["player_off"])
            if s is not None:
                slot_of[e["player"]] = s
                slot_changes.append((e["T"], s, e["player"]))
        if e["type"] == "card" and e.get("outcome") in ("red", "second_yellow"):
            s = slot_of.get(e["player"])
            if s is not None:
                off_from[s] = min(off_from[s], e["T"])
        ev_slot.append(slot_of.get(e.get("player"), -1) if e.get("player") else -1)

    # ------------------------------------------------------------ ball
    bidx = [i for i, e in enumerate(events) if e["type"] not in NO_BALL and e.get("x") is not None]
    bev = [events[i] for i in bidx]
    moves = _ball_moves(bev)
    ball = np.zeros((F, 3))
    ball[:, 0], ball[:, 1] = L / 2, W / 2
    mi = 0
    cur = (L / 2, W / 2)
    m0 = np.array([m[0] for m in moves])
    for f in range(F):
        t = Tg[f]
        while mi + 1 < len(moves) and m0[mi + 1] <= t:
            cur = (moves[mi][4], moves[mi][5])
            mi += 1
        if not moves or t < moves[mi][0]:
            ball[f, 0], ball[f, 1] = cur
            continue
        T0, T1, x0, y0, x1, y1, peak = moves[mi]
        if t >= T1:
            ball[f] = (x1, y1, 0.0)
        else:
            u = (t - T0) / max(1e-6, T1 - T0)
            ball[f] = (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u, peak * 4 * u * (1 - u))

    # ------------------------------------------------------------ per-frame context
    bT = np.array([e["T"] for e in bev])
    le = np.clip(np.searchsorted(bT, Tg, side="right") - 1, 0, len(bev) - 1)
    ne = np.clip(le + 1, 0, len(bev) - 1)
    poss = np.array([e["state"]["poss"] for e in bev])[le]
    le_type = np.array([e["type"] for e in bev])[le]
    ne_type = np.array([e["type"] for e in bev])[ne]
    bslot = np.array([ev_slot[i] for i in bidx])
    le_slot, ne_slot = bslot[le], bslot[ne]
    tleft = np.maximum(0.25, bT[ne] - Tg)
    ne_xy = np.array([[e["x"], e["y"]] for e in bev])[ne]
    poss_type_ne = np.isin(ne_type, list(POSSESSION_TYPES))

    # ------------------------------------------------------------ team shape targets (vectorised)
    bx, by = ball[:, 0], ball[:, 1]
    tgt = np.zeros((F, 22, 2))
    for s in range(22):
        tm = team[s]
        ap = bx if tm == 0 else L - bx
        att = poss == tm
        shift = (ap / L - np.where(att, 0.45, 0.56)) * 36.0
        if is_gk[s]:
            xf = base[s, 0] * L + np.maximum(0.0, shift * 0.15)
            yf = W / 2 + (by - W / 2) * 0.22
        else:
            push = np.where(att & np.isin(roles[s], ["RB", "LB"]), 6.0, 0.0)
            xf = base[s, 0] * L + shift + push
            wide = np.where(att, 0.80, 0.60)
            yf = W / 2 + (base[s, 1] * W - W / 2) * wide + (by - W / 2) * np.where(att, 0.22, 0.38)
        # restarts: each side in its own half until the kickoff is taken
        kick = (ne_type == "kickoff") & (le_type != "kickoff")
        kick |= (le_type == "kickoff") & (Tg - bT[le] < 1.5)
        xf = np.where(kick, np.minimum(xf, L / 2 - 1.5 - (0 if att.any() else 0)), xf)
        xf = np.clip(xf, 1.5, L - 1.5)
        yf = np.clip(yf, 1.5, W - 1.5)
        # gentle, deterministic wandering so nobody moves in lockstep
        ph, w1, w2 = rng.uniform(0, 6.3), rng.uniform(0.09, 0.17), rng.uniform(0.07, 0.14)
        amp = 0.6 if is_gk[s] else 4.2
        xf = xf + amp * np.sin(Tg * w1 + ph)
        yf = yf + amp * 0.8 * np.sin(Tg * w2 + ph * 1.7)
        tgt[:, s, 0] = xf if tm == 0 else L - xf
        tgt[:, s, 1] = yf

    # corners: both teams crowd the box
    corner = le_type == "corner"
    if corner.any():
        box = rng.uniform(0, 1, (22, 2))
        for s in range(22):
            if is_gk[s]:
                continue
            att_team = poss
            gx_att = np.where(att_team == 0, L - 5 - box[s, 0] * 11, 5 + box[s, 0] * 11)
            y_box = W / 2 + (box[s, 1] - 0.5) * 30
            sel = corner & ((team[s] == att_team) & ~is_cb[s] | (team[s] != att_team))
            tgt[sel, s, 0] = gx_att[sel]
            tgt[sel, s, 1] = y_box

    mode = np.zeros((F, 22), dtype=np.int8)
    f_idx = np.arange(F)
    # the player who acts next runs to where he will play the ball
    run = (ne_slot >= 0) & (ne_slot != le_slot) & poss_type_ne & (bT[ne] > Tg)
    tgt[f_idx[run], ne_slot[run]] = ne_xy[run]
    mode[f_idx[run], ne_slot[run]] = MODE_RUNNER
    # the player on the ball keeps it
    keepb = (le_slot >= 0) & (le_slot == ne_slot) & np.isin(le_type, list(POSSESSION_TYPES))
    tgt[f_idx[keepb], le_slot[keepb], 0] = bx[keepb]
    tgt[f_idx[keepb], le_slot[keepb], 1] = by[keepb]
    mode[f_idx[keepb], le_slot[keepb]] = MODE_FOLLOW
    # pressing: the two nearest outfield defenders close the ball down
    for tm in (0, 1):
        defending = (poss != tm) & ~corner
        cols = np.array([s for s in range(22) if team[s] == tm and not is_gk[s]])
        d = np.hypot(tgt[:, cols, 0] - bx[:, None], tgt[:, cols, 1] - by[:, None])
        order = np.argsort(d, axis=1)
        intensity = clubs[tm].style.press
        own_goal_x = 0.0 if tm == 0 else L
        for rank, gap in ((0, 1.6), (1, 6.0 - 3.0 * intensity)):
            s_sel = cols[order[:, rank]]
            ok = defending & (mode[f_idx, s_sel] == MODE_CRUISE) & (np.hypot(bx - own_goal_x, by - W / 2) < 95)
            if rank == 1:
                ok &= rng.random(F) < 0.15 + 0.85 * intensity  # pressing sides send a second man
            dirx = np.sign(own_goal_x - bx)
            tgt[f_idx[ok], s_sel[ok], 0] = bx[ok] + dirx[ok] * gap
            tgt[f_idx[ok], s_sel[ok], 1] = by[ok]
            mode[f_idx[ok], s_sel[ok]] = MODE_PRESS
    # sent off: walk to the touchline and leave
    for s in range(22):
        if np.isfinite(off_from[s]):
            sel = Tg >= off_from[s]
            tgt[sel, s] = (L / 2, -4.0)
            mode[sel, s] = MODE_OFF

    # ------------------------------------------------------------ motion integration
    pos = np.zeros((F, 22, 2))
    spd = np.zeros((F, 22))
    dist = np.zeros((F, 22))
    p = tgt[0].copy()
    v = np.zeros((22, 2))
    acc_base = np.where(is_gk, 3.0, 4.2)
    cruise = vmax * 0.58
    total = np.zeros(22)
    for f in range(F):
        to = tgt[f] - p
        d = np.hypot(to[:, 0], to[:, 1]) + 1e-9
        m = mode[f]
        sp = np.minimum(cruise, d * 0.9)
        r = m == MODE_RUNNER
        sp[r] = np.minimum(vmax[r] * 1.03, np.maximum(d[r] / tleft[f] * 1.3, np.minimum(d[r] * 0.8, 3.0)))
        fo = m == MODE_FOLLOW
        sp[fo] = np.minimum(vmax[fo], d[fo] / DT * 0.75)
        pr = m == MODE_PRESS
        sp[pr] = np.minimum(vmax[pr] * 0.92, d[pr] * 1.1)
        of = m == MODE_OFF
        sp[of] = np.minimum(1.6, d[of])
        vdes = to / d[:, None] * sp[:, None]
        dv = vdes - v
        amax = np.where(r | pr | fo, 6.0, acc_base) * DT
        n = np.hypot(dv[:, 0], dv[:, 1]) + 1e-9
        dv *= np.minimum(1.0, amax / n)[:, None]
        v += dv
        vs = np.hypot(v[:, 0], v[:, 1])
        over = vs > vmax * 1.03
        if over.any():
            v[over] *= (vmax[over] * 1.03 / vs[over])[:, None]
            vs = np.hypot(v[:, 0], v[:, 1])
        p = p + v * DT
        total += vs * DT
        pos[f], spd[f], dist[f] = p, vs * 3.6, total
    active = ~(((Tg[:, None] >= off_from[None, :] + 25.0)))

    # ------------------------------------------------------------ top-speed records (for tags)
    records = []
    best = 0.0
    fmax = spd.max(axis=1)
    smax = spd.argmax(axis=1)
    for f in range(F):
        if Tg[f] > 600 and fmax[f] > best + 0.25:
            best = float(fmax[f])
            s = int(smax[f])
            pid = initial[s]
            for tc, ss, ppid in slot_changes:
                if ss == s and tc <= Tg[f]:
                    pid = ppid
            records.append((float(Tg[f]), s, pid, round(best, 1)))
        elif Tg[f] <= 600:
            best = max(best, float(fmax[f]))

    return Tracking(Tg, ball, pos.astype(np.float32), spd.astype(np.float32), dist.astype(np.float32),
                    active, slot_changes, initial, records, p2_start)
