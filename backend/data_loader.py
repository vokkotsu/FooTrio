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