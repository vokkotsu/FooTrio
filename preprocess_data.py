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
    "current_club": "current_club_name",
}
TRANSFER_COLUMNS = {
    "player_id": "player_id",
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


def is_valid_club(name) -> bool:
    n = clean_value(name)
    if not n:
        return False
    if n in INVALID_CLUBS:
        return False
    if n.lower() in {x.lower() for x in INVALID_CLUBS}:
        return False
    if n.startswith("---"):
        return False
    return True


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

    for col in ["player_id", "player_name", "position", "sub_position", "country", "current_club"]:
        players_df[col] = clean_text(players_df[col])
    for col in ["player_id", "from_club", "to_club"]:
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

    # Build club history per player from transfers + current club
    clubs_by_player: dict[str, set[str]] = {}
    for pid, club in zip(players_df["player_id"], players_df["current_club"]):
        clubs_by_player.setdefault(pid, set())
        if is_valid_club(club):
            clubs_by_player[pid].add(clean_value(club))

    merged = transfers_df.merge(players_df[["player_id"]], on="player_id", how="inner")
    for _, row in merged.iterrows():
        pid = row["player_id"]
        for club in (row["from_club"], row["to_club"]):
            if is_valid_club(club):
                clubs_by_player.setdefault(pid, set()).add(clean_value(club))

    players = []
    countries = set()
    positions = set()
    sub_positions = set()
    clubs = set()
    for _, row in players_df.iterrows():
        pid = row["player_id"]
        player_clubs = sorted({c for c in clubs_by_player.get(pid, set()) if is_valid_club(c)})
        if not player_clubs:
            continue
        record = {
            "player_id": pid,
            "name": row["player_name"],
            "position": row["sub_position"],
            "main_position": row["position"],
            "country": row["country"],
            "clubs": player_clubs,
        }
        players.append(record)
        countries.add(record["country"])
        positions.add(row["position"])
        sub_positions.add(row["sub_position"])
        clubs.update(player_clubs)

    # name index prefers richer club histories for ambiguous same-name matches
    name_index = {}
    by_id = {p["player_id"]: p for p in players}
    for p in players:
        norm = " ".join(str(p["name"]).lower().split())
        name_index.setdefault(norm, []).append(p["player_id"])
    for norm, ids in name_index.items():
        ids.sort(key=lambda pid: (-len(by_id[pid]["clubs"]), by_id[pid]["name"], pid))

    top_fifa_countries = [c for c in TOP_FIFA_COUNTRIES if c in countries]
    top5_league_clubs = [c for c in TOP5_LEAGUE_CLUBS if c in clubs]

    data = {
        "identified_columns": {
            "players_csv": PLAYER_COLUMNS,
            "transfers_csv": TRANSFER_COLUMNS,
            "notes": (
                "Club/Club History is derived from players.current_club_name plus "
                "transfers.from_club_name and transfers.to_club_name joined on player_id."
            ),
        },
        "players": players,
        "name_index": name_index,
        "options": {
            "countries": sorted(countries),
            "positions": sorted(sub_positions),
            "sub_positions": sorted(sub_positions),
            "main_positions": sorted(positions),
            "clubs": sorted(clubs),
            "top_fifa_countries": top_fifa_countries,
            "top5_league_clubs": top5_league_clubs,
        },
        "stats": {
            "player_count": len(players),
            "country_count": len(countries),
            "position_count": len(positions),
            "sub_position_count": len(sub_positions),
            "club_count": len(clubs),
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
