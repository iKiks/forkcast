"""Calibrate the synthetic engine against public football norms.

Runs N seeded matches across every fixture and prints pass/fail per metric.
Usage: python -m scripts.validate [n_matches]
"""
from __future__ import annotations

import itertools
import json
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forkcast.engine import simulate  # noqa: E402
from forkcast.tracking import build as build_tracking  # noqa: E402
from forkcast.world import CLUBS  # noqa: E402

# Target bands are calibration targets typical of top-flight football.
BANDS = {
    "goals_per_match": (2.4, 3.1),
    "shots_per_team": (10.0, 16.0),
    "on_target_share": (0.30, 0.40),
    "pass_completion": (0.76, 0.88),
    "passes_per_team": (300, 520),
    "fouls_per_match": (18.0, 27.0),
    "yellow_per_match": (2.5, 5.0),
    "home_win_share": (0.36, 0.52),
    "draw_share": (0.18, 0.32),
    "km_per_outfield_player": (9.0, 12.0),
    "top_speed_kmh": (30.0, 37.0),
}


def run(n: int = 500) -> dict:
    fixtures = list(itertools.permutations(CLUBS.keys(), 2))
    goals, shots, on_t, passes, comp, fouls, yellows = [], [], [], [], [], [], []
    hw = dr = 0
    t0 = time.perf_counter()
    for i in range(n):
        h, a = fixtures[i % len(fixtures)]
        m = simulate(h, a, seed=10_000 + i)
        ev = m.events
        goals.append(sum(m.score))
        sh = [e for e in ev if e["type"] == "shot"]
        shots.extend([sum(1 for e in sh if e["team"] == h), sum(1 for e in sh if e["team"] == a)])
        on_t.append(sum(1 for e in sh if e["outcome"] in ("goal", "saved")) / max(1, len(sh)))
        ps = [e for e in ev if e["type"] == "pass"]
        passes.extend([sum(1 for e in ps if e["team"] == h), sum(1 for e in ps if e["team"] == a)])
        comp.append(sum(1 for e in ps if e["outcome"] == "complete") / max(1, len(ps)))
        fouls.append(sum(1 for e in ev if e["type"] == "foul"))
        yellows.append(sum(1 for e in ev if e["type"] == "card" and e["outcome"] in ("yellow", "second_yellow")))
        if m.score[0] > m.score[1]:
            hw += 1
        elif m.score[0] == m.score[1]:
            dr += 1
    dur = time.perf_counter() - t0
    # physical layer: a smaller sample, since tracking is 5 Hz for every player
    kms, tops = [], []
    for i in range(min(12, n)):
        h, a = fixtures[i % len(fixtures)]
        m = simulate(h, a, seed=20_000 + i)
        tr = build_tracking(m.events, m.home, m.away, 20_000 + i)
        km = tr.dist[-1] / 1000
        kms.append(st.median([float(km[s]) for s in range(22) if s % 11 != 0]))
        tops.append(float(tr.speed.max()))
    vals = {
        "goals_per_match": st.mean(goals),
        "shots_per_team": st.mean(shots),
        "on_target_share": st.mean(on_t),
        "pass_completion": st.mean(comp),
        "passes_per_team": st.mean(passes),
        "fouls_per_match": st.mean(fouls),
        "yellow_per_match": st.mean(yellows),
        "home_win_share": hw / n,
        "draw_share": dr / n,
        "km_per_outfield_player": st.mean(kms),
        "top_speed_kmh": st.mean(tops),
    }
    rows = []
    ok_all = True
    for k, v in vals.items():
        lo, hi = BANDS[k]
        ok = lo <= v <= hi
        ok_all &= ok
        rows.append({"metric": k, "value": round(v, 3), "band": [lo, hi], "pass": ok})
    return {"n_matches": n, "seconds": round(dur, 2), "ms_per_match": round(dur / n * 1000, 1),
            "all_pass": ok_all, "metrics": rows}


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    res = run(n)
    for r in res["metrics"]:
        print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['metric']:<18} {r['value']:>8}   band {r['band']}")
    print(f"\n{res['n_matches']} matches in {res['seconds']}s ({res['ms_per_match']} ms/match). "
          f"{'ALL PASS' if res['all_pass'] else 'SOME FAIL'}")
    out = ROOT / "docs" / "validation.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, indent=2))
