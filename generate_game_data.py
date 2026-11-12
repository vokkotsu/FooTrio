import csv
import json
import os
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
PLAYERS_CSV = os.path.join(BASE, "players.csv")
TRANSFERS_CSV = os.path.join(BASE, "transfers.csv")
OUT_JSON = os.path.join(BASE, "game_data.json")

PLAYER_COLUMNS = {
    "player_id": "player_id",
    "player_name": "name",
    "position": "position",
    "sub_position": "sub_position",
    "country": "country_of_citizenship",
    "current_club_id": "current_club_id",
    "current_club": "current_club_name",
}
TRANSFER_COLUMNS = {
    "player_id": "player_id",
    "from_club_id": "from_club_id",
    "to_club_id": "to_club_id",
    "from_club": "from_club_name",
    "to_club": "to_club_name",
}


INVALID_CLUBS = {
    "",
    "Without Club",
    "Retired",
    "Unknown",
    "Career break",
    "---",
    "Without club",
    "Career Break",
    "Unknown Club",
    "No Club",
    "None",
    "N/A",
    "n/a",
    "-",
    "--",
    "unknown",
}


def clean(v):
    return (v or "").strip()


def clean_id(v):
    cid = clean(v)
    if not cid:
        return ""
    # csv ids may come as floats/ints-as-strings in some datasets
    try:
        if cid.endswith(".0"):
            cid = str(int(float(cid)))
    except Exception:
        pass
    return cid


def is_valid_club(name, cid=""):
    n = clean(name)
    i = clean_id(cid)
    if not n or not i:
        return False
    if n in INVALID_CLUBS:
        return False
    if n.lower() in {x.lower() for x in INVALID_CLUBS}:
        return False
    if n.startswith("---"):
        return False
    if i in {"0", "-1"}:
        return False
    return True


TOP_FIFA_COUNTRIES = [
    "Argentina",
    "France",
    "Spain",
    "England",
    "Brazil",
    "Portugal",
    "Netherlands",
    "Belgium",
    "Germany",
    "Croatia",
]

TOP5_LEAGUE_CLUB_NAMES = [
    # Premier League
    "Manchester City",
    "Arsenal FC",
    "Liverpool FC",
    "Aston Villa",
    "Tottenham Hotspur",
    "Chelsea FC",
    "Newcastle United",
    "Manchester United",
    "West Ham United",
    "Brighton & Hove Albion",
    # La Liga
    "Real Madrid",
    "FC Barcelona",
    "Girona FC",
    "Atlético de Madrid",
    "Athletic Bilbao",
    "Real Sociedad",
    "Real Betis Balompié",
    "Villarreal CF",
    "Valencia CF",
    "Sevilla FC",
    # Bundesliga
    "Bayer 04 Leverkusen",
    "Bayern Munich",
    "VfB Stuttgart",
    "RB Leipzig",
    "Borussia Dortmund",
    "Eintracht Frankfurt",
    "TSG 1899 Hoffenheim",
    "1.FC Union Berlin",
    "SC Freiburg",
    "VfL Wolfsburg",
    # Serie A
    "Inter Milan",
    "AC Milan",
    "Juventus FC",
    "Atalanta BC",
    "Bologna FC 1909",
    "AS Roma",
    "SS Lazio",
    "ACF Fiorentina",
    "SSC Napoli",
    "Torino FC",
    # Ligue 1
    "Paris Saint-Germain",
    "AS Monaco",
    "Stade Brestois 29",
    "LOSC Lille",
    "OGC Nice",
    "Olympique Lyon",
    "RC Lens",
    "Olympique Marseille",
    "Stade Rennais FC",
    "Stade Reims",
]


def register_club(club_name_by_id, cid, name):
    cid = clean_id(cid)
    name = clean(name)
    if not is_valid_club(name, cid):
        return
    # keep first seen non-empty name for an id (stable)
    if cid not in club_name_by_id:
        club_name_by_id[cid] = name


def main():
    players = {}
    club_name_by_id = {}

    with open(PLAYERS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = clean(row.get(PLAYER_COLUMNS["player_id"]))
            name = clean(row.get(PLAYER_COLUMNS["player_name"]))
            position = clean(row.get(PLAYER_COLUMNS["position"]))
            sub_position = clean(row.get(PLAYER_COLUMNS["sub_position"]))
            country = clean(row.get(PLAYER_COLUMNS["country"]))
            current_club_id = clean_id(row.get(PLAYER_COLUMNS["current_club_id"]))
            current_club = clean(row.get(PLAYER_COLUMNS["current_club"]))
            if not pid or not name or not position or position == "Missing" or not sub_position or not country:
                continue
            clubs = set()
            if is_valid_club(current_club, current_club_id):
                register_club(club_name_by_id, current_club_id, current_club)
                clubs.add(current_club_id)
            players[pid] = {
                "player_id": pid,
                "name": name,
                "position": position,
                "sub_position": sub_position,
                "country": country,
                "clubs": clubs,
            }

    with open(TRANSFERS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = clean(row.get(TRANSFER_COLUMNS["player_id"]))
            if not pid or pid not in players:
                continue
            for id_key, name_key in (("from_club_id", "from_club"), ("to_club_id", "to_club")):
                cid = clean_id(row.get(TRANSFER_COLUMNS[id_key]))
                cname = clean(row.get(TRANSFER_COLUMNS[name_key]))
                if is_valid_club(cname, cid):
                    register_club(club_name_by_id, cid, cname)
                    players[pid]["clubs"].add(cid)

    records = []
    countries = set()
    positions = set()
    sub_positions = set()
    clubs_pool_ids = set()
    for p in players.values():
        club_ids = sorted({cid for cid in p["clubs"] if cid in club_name_by_id})
        if not club_ids:
            continue
        rec = {
            "player_id": p["player_id"],
            "name": p["name"],
            "position": p["sub_position"],
            "main_position": p["position"],
            "country": p["country"],
            "clubs": club_ids,
        }
        records.append(rec)
        countries.add(rec["country"])
        positions.add(p["position"])
        sub_positions.add(p["sub_position"])
        clubs_pool_ids.update(club_ids)

    # index by normalized name; prefer richer records first so ambiguous guesses resolve better
    by_id = {p["player_id"]: p for p in records}
    name_index = defaultdict(list)
    for p in records:
        norm = " ".join(p["name"].lower().split())
        name_index[norm].append(p["player_id"])
    for norm, ids in name_index.items():
        ids.sort(key=lambda pid: (-len(by_id[pid]["clubs"]), by_id[pid]["name"], pid))
        name_index[norm] = ids

    clubs_options = [
        {"id": cid, "name": club_name_by_id[cid]}
        for cid in sorted(clubs_pool_ids, key=lambda c: (club_name_by_id[c].lower(), c))
    ]

    # map top-5 league names to ids present in pool (by exact name match)
    clubs_by_name = {}
    for cid in clubs_pool_ids:
        clubs_by_name.setdefault(club_name_by_id[cid], []).append(cid)
    top5_league_clubs = []
    for name in TOP5_LEAGUE_CLUB_NAMES:
        ids_for_name = sorted(clubs_by_name.get(name, []))
        if ids_for_name:
            top5_league_clubs.append({"id": ids_for_name[0], "name": name})

    top_fifa_countries = [c for c in TOP_FIFA_COUNTRIES if c in countries]

    data = {
        "identified_columns": {
            "players_csv": PLAYER_COLUMNS,
            "transfers_csv": TRANSFER_COLUMNS,
            "notes": "Club/Club History is derived from current_club_id/name plus transfers from/to club ids/names joined on player_id. Clubs use stable IDs for matching.",
        },
        "players": records,
        "name_index": dict(name_index),
        "options": {
            "countries": sorted(countries),
            "positions": sorted(sub_positions),
            "sub_positions": sorted(sub_positions),
            "main_positions": sorted(positions),
            "clubs": clubs_options,
            "top_fifa_countries": top_fifa_countries,
            "top5_league_clubs": top5_league_clubs,
        },
        "stats": {
            "player_count": len(records),
            "country_count": len(countries),
            "position_count": len(positions),
            "sub_position_count": len(sub_positions),
            "club_count": len(clubs_options),
            "top_fifa_country_count": len(top_fifa_countries),
            "top5_league_club_count": len(top5_league_clubs),
        },
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print(json.dumps(data["identified_columns"], indent=2))
    print(json.dumps(data["stats"], indent=2))
    print("Wrote", OUT_JSON)


if __name__ == "__main__":
    main()
