"""Turn an exact outlook into descriptive, fully-evidenced forecast language."""
from __future__ import annotations

from .i18n import LANGS, render_story


def pct(p: float) -> int:
    return int(round(100 * p))


def forecast_values(o: dict, score: list[int], home, away) -> tuple[str, dict]:
    """Return (variant, values): variant is 'lead' or 'level'; every number on screen comes from values."""
    sls = o["scorelines"]
    v = {
        "home": home.name, "away": away.name, "score": f"{score[0]}–{score[1]}",
        "hw": pct(o["home_win"]), "dw": pct(o["draw"]), "aw": pct(o["away_win"]),
        "mins": o["mins_left"],
        "sl": f"{sls[0]['score'][0]}–{sls[0]['score'][1]}", "slp": pct(sls[0]["p"]),
        "sl2": f"{sls[1]['score'][0]}–{sls[1]['score'][1]}", "slp2": pct(sls[1]["p"]),
        "ngh": pct(o["next_goal"]["home"]), "nga": pct(o["next_goal"]["away"]), "ngn": pct(o["next_goal"]["none"]),
        "p10": pct(1 - o["next_goal_10"]["none"]),
        "egh": f"{o['exp_goals_left'][0]:.1f}", "ega": f"{o['exp_goals_left'][1]:.1f}",
    }
    if score[0] == score[1]:
        fav, fw = (home, o["home_win"]) if o["home_win"] >= o["away_win"] else (away, o["away_win"])
        variant = "draw" if o["draw"] >= max(o["home_win"], o["away_win"]) else "level"
        v.update({"fav": fav.name, "fw": pct(fw), "variant": variant})
        return variant, v
    lead_home = score[0] > score[1]
    lead, trail = (home, away) if lead_home else (away, home)
    lw, tw = (o["home_win"], o["away_win"]) if lead_home else (o["away_win"], o["home_win"])
    egl, egt = (o["exp_goals_left"][0], o["exp_goals_left"][1]) if lead_home else (o["exp_goals_left"][1], o["exp_goals_left"][0])
    v.update({"lead": lead.name, "trail": trail.name, "lw": pct(lw), "tw": pct(tw),
              "p_back": pct(o["draw"] + tw), "need": abs(score[0] - score[1]),
              "egl": f"{egl:.1f}", "egt": f"{egt:.1f}", "variant": "lead"})
    return "lead", v


def story(o: dict, score: list[int], home, away, kind: str = "forecast") -> tuple[dict, dict]:
    """Texts for every language and lens. kind: 'forecast' (full) or 'after' (suffix after a moment)."""
    variant, v = forecast_values(o, score, home, away)
    tpl = f"{kind}_{variant}"
    texts = {lang: {lens: render_story(tpl, lang, lens, v) for lens in ("casual", "analyst")} for lang in LANGS}
    return texts, {**v, "variant": variant}
