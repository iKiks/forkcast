# Forkcast event schema (v0.1)

Every event emitted by the synthetic engine and streamed over `/api/live` (message `type: "event"`, original type in `type_`).

| Field | Type | Notes |
| --- | --- | --- |
| `event_id` | string | `e00001`… unique per match, cited by every on-screen claim |
| `match_id` | string | `{home}-{away}-{seed}`; deterministic |
| `seq` | int | 1-based order |
| `t` | float | match clock in seconds; second half starts at 2700 |
| `clock` | string | broadcast clock, e.g. `45+2` |
| `period` | int | 1 or 2 |
| `team` | string or null | club id of the acting team |
| `player` | string or null | player id, e.g. `kes-9` |
| `receiver` | string | passes and crosses that were completed |
| `type` | string | `kickoff, pass, carry, cross, shot, interception, tackle, clearance, recovery, foul, card, free_kick, corner, throw_in, goal_kick, goalkeeper, substitution, period_start, period_end, full_time` |
| `x`, `y` | float | metres; pitch 105 × 68, home attacks towards x = 105 |
| `end_x`, `end_y` | float | where the ball went |
| `outcome` | string | e.g. `complete, intercepted, out, goal, saved, blocked, off_target, yellow, red` |
| `pressure` | bool | an opponent was pressing the action |
| `body_part` | string | shots: `foot` or `head` |
| `speed_kmh` | float | ball speed (pass, shot) or player speed (carry) |
| `xg` | float | shots; calibrated so goals ≈ sum of xG |
| `pass_length` | float | metres |
| `pass_difficulty` | int | 0–100, = (1 − completion probability) × 100 |
| `success_prob` | float | modelled completion probability of the pass |
| `chain_id` | int | possession chain; changes on every turnover |
| `tags` | string[] | `sprint, rocket, big_chance, long_ball, final_third_entry, high_turnover, corner, red_card`… |
| `state` | object | state *after* the event: `score`, `poss` (0 home / 1 away), `ap` (metres of progress for the team in possession), `y`, `zone` (0–17), `t`, `red` |

Zones: 6 progress bands (edges at 20%, 35%, 50%, 65%, 80% of the pitch length in the attacking direction) × 3 lateral channels.

Determinism: `(home, away, seed)` always reproduces the same match, byte for byte.
