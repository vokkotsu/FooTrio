import json
import os
import random
from functools import lru_cache

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "game_data.json")


@lru_cache(maxsize=1)
def load_game_data():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_players():
    return load_game_data()["players"]


def get_options():
    return load_game_data()["options"]


def sample_options(attribute, k=5):
    options = get_options()
    pool = options.get(attribute, [])
    if len(pool) <= k:
        return list(pool)
    return random.sample(pool, k)


def normalize_name(name: str) -> str:
    return " ".join((name or "").lower().split())


def find_player_matches(guess: str):
    data = load_game_data()
    norm = normalize_name(guess)
    if not norm:
        return []
    ids = data.get("name_index", {}).get(norm, [])
    players = {p["player_id"]: p for p in data["players"]}
    return [players[i] for i in ids if i in players]


def best_guess_for_constraints(constraints: dict, rng: random.Random | None = None) -> str:
    """Return a plausible player name guess for the given constraints (for bots)."""
    rng = rng or random
    players = get_players()
    country = constraints.get("country")
    position = constraints.get("position")
    club = constraints.get("club")

    best_name = None
    best_score = -1
    # sample to keep it cheap; fall back to full scan if needed
    sample = players if len(players) <= 5000 else rng.sample(players, 5000)
    for p in sample:
        score = 0
        if country and p.get("country") == country:
            score += 1
        if position and p.get("position") == position:
            score += 1
        if club and club in (p.get("clubs") or []):
            score += 1
        if score > best_score:
            best_score = score
            best_name = p.get("name")
            if best_score == 3:
                break

    if best_name:
        return best_name
    return rng.choice(players).get("name", "Unknown Player") if players else "Unknown Player"