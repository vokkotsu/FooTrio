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


def _sample_weighted(pool, priority_pool, k, priority_count):
    pool = list(pool)
    priority = [x for x in priority_pool if x in pool]
    others = [x for x in pool if x not in set(priority)]

    if len(pool) <= k:
        return list(pool)

    p_count = min(priority_count, k, len(priority))
    o_count = k - p_count
    if o_count > len(others):
        # not enough non-priority options; fill remainder from priority
        o_count = len(others)
        p_count = min(k - o_count, len(priority))

    chosen = []
    if p_count > 0 and priority:
        chosen.extend(random.sample(priority, p_count))
    if o_count > 0 and others:
        chosen.extend(random.sample(others, o_count))

    remaining_needed = k - len(chosen)
    if remaining_needed > 0:
        remaining = [x for x in pool if x not in set(chosen)]
        if remaining:
            chosen.extend(random.sample(remaining, min(remaining_needed, len(remaining))))

    random.shuffle(chosen)
    return chosen


def sample_options(attribute, k=5):
    options = get_options()
    key_map = {
        "country": "countries",
        "position": "positions",
        "club": "clubs",
    }
    key = key_map.get(attribute, attribute)
    pool = options.get(key, [])

    if attribute == "country":
        priority = options.get("top_fifa_countries") or []
        if priority:
            # ensure 3/5 come from top 10 FIFA-ranked countries (when available)
            return _sample_weighted(pool, priority, k, priority_count=min(3, k))
    elif attribute == "club":
        priority = options.get("top5_league_clubs") or []
        if priority:
            # ensure 3/5 come from Europe top 5 leagues (when available)
            return _sample_weighted(pool, priority, k, priority_count=min(3, k))

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


@lru_cache(maxsize=1)
def _player_name_pairs():
    # list of (display_name, normalized_name, sub_position) for suggestion search
    return [
        (p.get("name", ""), normalize_name(p.get("name", "")), p.get("position", ""))
        for p in get_players()
        if p.get("name")
    ]


def search_player_names(query: str, limit: int = 8):
    q = normalize_name(query)
    if not q:
        return []
    pairs = _player_name_pairs()
    starts = []
    contains = []
    seen = set()
    for name, norm, position in pairs:
        if not norm or norm in seen:
            continue
        item = {"name": name, "position": position}
        if norm.startswith(q):
            seen.add(norm)
            starts.append(item)
            if len(starts) >= limit:
                return starts[:limit]
        elif q in norm:
            contains.append((norm, item))
    for norm, item in contains:
        if norm in seen:
            continue
        seen.add(norm)
        starts.append(item)
        if len(starts) >= limit:
            break
    return starts[:limit]