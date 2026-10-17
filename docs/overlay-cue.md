# Overlay cue contract (`overlay.cue` v0.1)

Cues are timed, machine-readable instructions a graphics renderer can draw over a live feed. They arrive on `/api/live` as `type: "cue"` and can be downloaded after a match from the app ("Download overlay cues").

```json
{
  "type": "cue",
  "cue_id": "c0012",
  "kind": "goal",
  "lane": "main",
  "overlay": "impact",
  "t": 1189.4,
  "clock": "19:49",
  "period": 1,
  "event_id": "e00412",
  "team": "amb",
  "players": ["amb-9", "amb-10"],
  "duration": 9.0,
  "latency_ms": 312.5,
  "values": { "player": "Nico Moreau", "before": 33, "after": 60, "delta_s": "+27.1", "n": "1,000", "fork": 60, "xg": "0.31", "speed": "98" },
  "evidence": { "delta": 0.271, "impact": { "before": { "home_win": 0.38 }, "after": { "home_win": 0.17 } } },
  "text": {
    "en": { "casual": "GOAL! …", "analyst": "Goal: … [e00412] …", "club:kes": "Worrying for Kestrel Vale fans: …", "club:amb": "Good news for Port Amberly fans: …" },
    "fr": { … }, "es": { … }, "pt": { … }, "pcm": { … }
  }
}
```

| Field | Meaning |
| --- | --- |
| `kind` | `goal, chance, turnover, red, record_shot, record_sprint, record_pass, control_take, control_chaos, halftime, fulltime` |
| `lane` | `main` (one card at a time) or `tag` (small player tag) |
| `overlay` | suggested template: `impact` (lower third with before/after bar), `banner`, `meter`, `tag` |
| `t`, `period`, `clock` | when to show it, in match time |
| `duration` | seconds on screen at normal playback |
| `values` | every number shown on screen; the Skeptic verified each one |
| `evidence` | the measurement behind the cue (exact outlook, forks, counterfactual) |
| `text[lang][lens]` | lenses: `casual`, `analyst`, `club:<id>`; player-focus clients filter by `players` |

Rules the Director enforces: goals, red cards, half time and full time always air; other `main` cues need 75 match seconds of clear screen; `tag` cues need 150 seconds between them.
