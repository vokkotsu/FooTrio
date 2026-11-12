import json
import os

import pandas as pd


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLAYERS_CSV = os.path.join(BASE_DIR, "players.csv")
TRANSFERS_CSV = os.path.join(BASE_DIR, "transfers.csv")
OUTPUT_JSON = os.path.join(BASE_DIR, "game_data.json")


# Relevant columns identified from the provided datasets
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

TOP5_LEAGUE_CLUBS = [
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


def clean_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def clean_value(v) -> str:
    return str(v or "").strip()


def clean_id(v) -> str:
    cid = clean_value(v)
    if not cid:
        return ""
    try:
        if cid.endswith(".0"):
            cid = str(int(float(cid)))
    except Exception:
        pass
    return cid


def is_valid_club(name, cid="") -> bool:
    n = clean_value(name)
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


def register_club(club_name_by_id, cid, name):
    cid = clean_id(cid)
    name = clean_value(name)
    if not is_valid_club(name, cid):
        return
    if cid not in club_name_by_id:
        club_name_by_id[cid] = name


def main() -> None:
    players_df = pd.read_csv(
        PLAYERS_CSV,
        usecols=list(PLAYER_COLUMNS.values()),
        dtype=str,
        low_memory=False,
    ).rename(columns={v: k for k, v in PLAYER_COLUMNS.items()})

    transfers_df = pd.read_csv(
        TRANSFERS_CSV,
        usecols=list(TRANSFER_COLUMNS.values()),
        dtype=str,
        low_memory=False,
    ).rename(columns={v: k for k, v in TRANSFER_COLUMNS.items()})

    for col in ["player_id", "player_name", "position", "sub_position", "country", "current_club_id", "current_club"]:
        if col in players_df.columns:
            players_df[col] = clean_text(players_df[col])
    for col in ["player_id", "from_club_id", "to_club_id", "from_club", "to_club"]:
        if col in transfers_df.columns:
            transfers_df[col] = clean_text(transfers_df[col])

    # Keep players that have the attributes needed for gameplay
    players_df = players_df[
        (players_df["player_id"] != "")
        & (players_df["player_name"] != "")
        & (players_df["position"] != "")
        & (players_df["position"] != "Missing")
        & (players_df["sub_position"] != "")
        & (players_df["country"] != "")
    ].copy()

    club_name_by_id: dict[str, str] = {}

    # Build club history per player from transfers + current club (by club ID)
    clubs_by_player: dict[str, set[str]] = {}
    for pid, cid, cname in zip(players_df["player_id"], players_df["current_club_id"], players_df["current_club"]):
        clubs_by_player.setdefault(pid, set())
        if is_valid_club(cname, cid):
            register_club(club_name_by_id, cid, cname)
            clubs_by_player[pid].add(clean_id(cid))

    merged = transfers_df.merge(players_df[["player_id"]], on="player_id", how="inner")
    for _, row in merged.iterrows():
        pid = row["player_id"]
        for cid_col, cname_col in (("from_club_id", "from_club"), ("to_club_id", "to_club")):
            cid = row.get(cid_col, "")
            cname = row.get(cname_col, "")
            if is_valid_club(cname, cid):
                register_club(club_name_by_id, cid, cname)
                clubs_by_player.setdefault(pid, set()).add(clean_id(cid))

    players = []
    countries = set()
    positions = set()
    sub_positions = set()
    clubs_pool_ids = set()
    for _, row in players_df.iterrows():
        pid = row["player_id"]
        player_club_ids = sorted({c for c in clubs_by_player.get(pid, set()) if c in club_name_by_id})
        if not player_club_ids:
            continue
        record = {
            "player_id": pid,
            "name": row["player_name"],
            "position": row["sub_position"],
            "main_position": row["position"],
            "country": row["country"],
            "clubs": player_club_ids,
        }
        players.append(record)
        countries.add(record["country"])
        positions.add(row["position"])
        sub_positions.add(row["sub_position"])
        clubs_pool_ids.update(player_club_ids)

    # name index prefers richer club histories for ambiguous same-name matches
    name_index = {}
    by_id = {p["player_id"]: p for p in players}
    for p in players:
        norm = " ".join(str(p["name"]).lower().split())
        name_index.setdefault(norm, []).append(p["player_id"])
    for norm, ids in name_index.items():
        ids.sort(key=lambda pid: (-len(by_id[pid]["clubs"]), by_id[pid]["name"], pid))

    clubs_options = [
        {"id": cid, "name": club_name_by_id[cid]}
        for cid in sorted(clubs_pool_ids, key=lambda c: (club_name_by_id[c].lower(), c))
    ]
    clubs_by_name = {}
    for cid in clubs_pool_ids:
        clubs_by_name.setdefault(club_name_by_id[cid], []).append(cid)
    top5_league_clubs = []
    for name in TOP5_LEAGUE_CLUBS:
        ids_for_name = sorted(clubs_by_name.get(name, []))
        if ids_for_name:
            top5_league_clubs.append({"id": ids_for_name[0], "name": name})
    top_fifa_countries = [c for c in TOP_FIFA_COUNTRIES if c in countries]

    data = {
        "identified_columns": {
            "players_csv": PLAYER_COLUMNS,
            "transfers_csv": TRANSFER_COLUMNS,
            "notes": (
                "Club/Club History is derived from current_club_id/name plus "
                "transfers from/to club ids/names joined on player_id. Clubs use stable IDs for matching."
            ),
        },
        "players": players,
        "name_index": name_index,
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
            "player_count": len(players),
            "country_count": len(countries),
            "position_count": len(positions),
            "sub_position_count": len(sub_positions),
            "club_count": len(clubs_options),
            "top_fifa_country_count": len(top_fifa_countries),
            "top5_league_club_count": len(top5_league_clubs),
        },
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("Identified columns:", json.dumps(data["identified_columns"], indent=2))
    print("Stats:", json.dumps(data["stats"], indent=2))
    print(f"Wrote {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
