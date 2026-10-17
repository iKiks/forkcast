"""The fictional football world: clubs, styles and squads.

All clubs, players and the league are invented. No real names, marks or likenesses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import random

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
LEAGUE_NAME = "Meridian Premier Division"

# 4-3-3 base shape in the attacking frame: x in [0,1] own goal -> opponent goal, y in [0,1].
FORMATION_433 = [
    ("GK", 0.05, 0.50),
    ("RB", 0.24, 0.12),
    ("CB", 0.18, 0.37),
    ("CB", 0.18, 0.63),
    ("LB", 0.24, 0.88),
    ("DM", 0.36, 0.50),
    ("CM", 0.48, 0.30),
    ("CM", 0.48, 0.70),
    ("RW", 0.70, 0.14),
    ("ST", 0.76, 0.50),
    ("LW", 0.70, 0.86),
]


@dataclass(frozen=True)
class Style:
    """Team style vector. All values in [0, 1]."""

    quality: float  # overall technical level
    press: float  # how hard they press without the ball
    directness: float  # preference for long, forward passes
    width: float  # how much they use the flanks
    tempo: float  # speed of ball circulation
    finishing: float  # shot conversion skill


@dataclass
class Player:
    id: str
    name: str
    short: str
    number: int
    role: str
    base_x: float
    base_y: float
    top_speed: float  # km/h


@dataclass
class Club:
    id: str
    name: str
    short: str
    color: str
    alt_color: str
    style: Style
    players: list[Player] = field(default_factory=list)
    bench: list[Player] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "short": self.short,
            "color": self.color,
            "alt_color": self.alt_color,
            "style": self.style.__dict__,
            "players": [p.__dict__ for p in self.players],
            "bench": [p.__dict__ for p in self.bench],
        }


FIRST = [
    "Tobi", "Kemi", "Ade", "Chidi", "Femi", "Ifeanyi", "Seun", "Bayo", "Emeka", "Dayo",
    "Luca", "Mateo", "Jonas", "Elias", "Rafael", "Theo", "Milan", "Arno", "Nico", "Sami",
    "Kofi", "Yaw", "Kwame", "Idris", "Omar", "Hamza", "Ravi", "Arjun", "Kenji", "Haruto",
    "Diego", "Tomas", "Bruno", "Iker", "Leif", "Sven", "Pavel", "Dario", "Ilan", "Remy",
]
LAST = [
    "Adeyemi", "Okafor", "Balogun", "Eze", "Afolabi", "Nwosu", "Ogunleye", "Bankole",
    "Varga", "Lindqvist", "Moreau", "Castell", "Brandt", "Okoro", "Mensah", "Asante",
    "Haddad", "Farouk", "Iyer", "Tanaka", "Sato", "Quintero", "Ferraz", "Duarte",
    "Halvorsen", "Novak", "Rossetti", "Marchand", "Kovac", "Delacroix", "Ferreira",
    "Achterberg", "Valdivia", "Oyelaran", "Abiodun", "Kaminski", "Strand", "Bellami",
]

CLUB_DEFS = [
    # id, name, short, colour, alt, style
    ("kes", "Kestrel Vale", "KES", "#21C7B8", "#0B3D3A",
     Style(quality=0.72, press=0.45, directness=0.25, width=0.55, tempo=0.65, finishing=0.62)),
    ("amb", "Port Amberly", "AMB", "#FF7A3D", "#3A1606",
     Style(quality=0.66, press=0.80, directness=0.70, width=0.45, tempo=0.80, finishing=0.58)),
    ("irn", "Ironmere United", "IRN", "#C9D1D9", "#22272E",
     Style(quality=0.62, press=0.55, directness=0.55, width=0.70, tempo=0.55, finishing=0.55)),
    ("cal", "Calder Bay", "CAL", "#7C8CFF", "#151A4A",
     Style(quality=0.70, press=0.62, directness=0.40, width=0.50, tempo=0.70, finishing=0.66)),
    ("wht", "Whitford Town", "WHT", "#F2C14E", "#3D2E05",
     Style(quality=0.58, press=0.35, directness=0.60, width=0.40, tempo=0.45, finishing=0.52)),
    ("ash", "Ashbourne Forge", "ASH", "#E5484D", "#3B0A0C",
     Style(quality=0.65, press=0.70, directness=0.50, width=0.60, tempo=0.75, finishing=0.60)),
]


def _make_players(club_id: str, seed: int) -> tuple[list[Player], list[Player]]:
    rng = random.Random(f"{club_id}-{seed}")
    used: set[str] = set()
    numbers = [1, 2, 4, 5, 3, 6, 8, 10, 7, 9, 11]
    xi: list[Player] = []

    def name() -> str:
        while True:
            n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if n not in used:
                used.add(n)
                return n

    for i, (role, bx, by) in enumerate(FORMATION_433):
        n = name()
        speed = rng.uniform(29.0, 35.5) if role in ("RW", "LW", "ST", "RB", "LB") else rng.uniform(26.0, 32.0)
        if role == "GK":
            speed = rng.uniform(22.0, 26.0)
        xi.append(Player(f"{club_id}-{numbers[i]}", n, n.split()[-1], numbers[i], role, bx, by, round(speed, 1)))
    bench = []
    for j, role in enumerate(["CM", "RW", "ST", "CB", "LW"]):
        n = name()
        num = 14 + j * 3
        bx, by = next((x, y) for r, x, y in FORMATION_433 if r == role)
        bench.append(Player(f"{club_id}-{num}", n, n.split()[-1], num, role, bx, by, round(rng.uniform(28.0, 34.0), 1)))
    return xi, bench


def build_clubs(seed: int = 7) -> dict[str, Club]:
    clubs: dict[str, Club] = {}
    for cid, name, short, color, alt, style in CLUB_DEFS:
        xi, bench = _make_players(cid, seed)
        clubs[cid] = Club(cid, name, short, color, alt, style, xi, bench)
    return clubs


CLUBS = build_clubs()
