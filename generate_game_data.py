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
    "country": "country_of_citizenship",
    "current_club": "current_club_name",
}
TRANSFER_COLUMNS = {
    "player_id": "player_id",
    "from_club": "from_club_name",
    "to_club": "to_club_name",
}


def clean(v):
    return (v or "").strip()


def main():
    players = {}
    with open(PLAYERS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = clean(row.get(PLAYER_COLUMNS["player_id"]))
            name = clean(row.get(PLAYER_COLUMNS["player_name"]))
            position = clean(row.get(PLAYER_COLUMNS["position"]))
            country = clean(row.get(PLAYER_COLUMNS["country"]))
            current_club = clean(row.get(PLAYER_COLUMNS["current_club"]))
            if not pid or not name or not position or position == "Missing" or not country:
                continue
            clubs = set()
            if current_club:
                clubs.add(current_club)
            players[pid] = {
                "player_id": pid,
                "name": name,
                "position": position,
                "country": country,
                "clubs": clubs,
            }

    invalid_clubs = {"", "Without Club", "Retired", "Unknown", "Career break", "---"}
    with open(TRANSFERS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = clean(row.get(TRANSFER_COLUMNS["player_id"]))
            if not pid or pid not in players:
                continue
            for key in ("from_club", "to_club"):
                c = clean(row.get(TRANSFER_COLUMNS[key]))
                if c and c not in invalid_clubs:
                    players[pid]["clubs"].add(c)

    records = []
    countries = set()
    positions = set()
    clubs_pool = set()
    for p in players.values():
        club_list = sorted(p["clubs"])
        if not club_list:
            continue
        rec = {
            "player_id": p["player_id"],
            "name": p["name"],
            "position": p["position"],
            "country": p["country"],
            "clubs": club_list,
        }
        records.append(rec)
        countries.add(rec["country"])
        positions.add(rec["position"])
        clubs_pool.update(club_list)

    name_index = defaultdict(list)
    for p in records:
        norm = " ".join(p["name"].lower().split())
        name_index[norm].append(p["player_id"])

    data = {
        "identified_columns": {
            "players_csv": PLAYER_COLUMNS,
            "transfers_csv": TRANSFER_COLUMNS,
            "notes": "Club/Club History is derived from players.current_club_name plus transfers.from_club_name and transfers.to_club_name joined on player_id.",
        },
        "players": records,
        "name_index": dict(name_index),
        "options": {
            "countries": sorted(countries),
            "positions": sorted(positions),
            "clubs": sorted(clubs_pool),
        },
        "stats": {
            "player_count": len(records),
            "country_count": len(countries),
            "position_count": len(positions),
            "club_count": len(clubs_pool),
        },
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print(json.dumps(data["identified_columns"], indent=2))
    print(json.dumps(data["stats"], indent=2))
    print("Wrote", OUT_JSON)


if __name__ == "__main__":
    main()
