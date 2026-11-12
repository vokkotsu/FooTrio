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
    "country": "country_of_citizenship",
    "current_club": "current_club_name",
}
TRANSFER_COLUMNS = {
    "player_id": "player_id",
    "from_club": "from_club_name",
    "to_club": "to_club_name",
}


def clean_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


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

    for col in ["player_id", "player_name", "position", "country", "current_club"]:
        players_df[col] = clean_text(players_df[col])
    for col in ["player_id", "from_club", "to_club"]:
        transfers_df[col] = clean_text(transfers_df[col])

    # Keep players that have the attributes needed for gameplay
    players_df = players_df[
        (players_df["player_id"] != "")
        & (players_df["player_name"] != "")
        & (players_df["position"] != "")
        & (players_df["position"] != "Missing")
        & (players_df["country"] != "")
    ].copy()

    # Build club history per player from transfers + current club
    clubs_by_player: dict[str, set[str]] = {}
    for pid, club in zip(players_df["player_id"], players_df["current_club"]):
        clubs_by_player.setdefault(pid, set())
        if club:
            clubs_by_player[pid].add(club)

    invalid_clubs = {"", "Without Club", "Retired", "Unknown", "Career break", "---"}
    merged = transfers_df.merge(players_df[["player_id"]], on="player_id", how="inner")
    for _, row in merged.iterrows():
        pid = row["player_id"]
        for club in (row["from_club"], row["to_club"]):
            if club and club not in invalid_clubs:
                clubs_by_player.setdefault(pid, set()).add(club)

    players = []
    countries = set()
    positions = set()
    clubs = set()
    for _, row in players_df.iterrows():
        pid = row["player_id"]
        player_clubs = sorted(clubs_by_player.get(pid, set()))
        if not player_clubs:
            continue
        record = {
            "player_id": pid,
            "name": row["player_name"],
            "position": row["position"],
            "country": row["country"],
            "clubs": player_clubs,
        }
        players.append(record)
        countries.add(record["country"])
        positions.add(record["position"])
        clubs.update(player_clubs)

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
        "options": {
            "countries": sorted(countries),
            "positions": sorted(positions),
            "clubs": sorted(clubs),
        },
        "stats": {
            "player_count": len(players),
            "country_count": len(countries),
            "position_count": len(positions),
            "club_count": len(clubs),
        },
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("Identified columns:", json.dumps(data["identified_columns"], indent=2))
    print("Stats:", json.dumps(data["stats"], indent=2))
    print(f"Wrote {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
