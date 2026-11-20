import json
import os
import re
import unicodedata
from collections import defaultdict

import pandas as pd


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLAYERS_CSV = os.path.join(BASE_DIR, "players.csv")
TRANSFERS_CSV = os.path.join(BASE_DIR, "transfers.csv")
OUTPUT_JSON = os.path.join(BASE_DIR, "game_data.json")
FRONTEND_OUTPUT_JSON = os.path.join(BASE_DIR, "frontend", "src", "game_data.json")


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

TOP5_LEAGUE_CLUB_PREFERENCES = [
    ("Manchester City", ["Manchester City"]),
    ("Arsenal FC", ["Arsenal FC", "Arsenal Football Club"]),
    ("Liverpool FC", ["Liverpool FC", "Liverpool Football Club"]),
    ("Aston Villa", ["Aston Villa"]),
    ("Tottenham Hotspur", ["Tottenham Hotspur"]),
    ("Chelsea FC", ["Chelsea FC", "Chelsea Football Club"]),
    ("Newcastle United", ["Newcastle United"]),
    ("Manchester United", ["Manchester United"]),
    ("West Ham United", ["West Ham United"]),
    ("Brighton & Hove Albion", ["Brighton & Hove Albion"]),
    ("Real Madrid", ["Real Madrid", "Real Madrid CF", "Real Madrid Club de Fútbol"]),
    ("FC Barcelona", ["FC Barcelona", "Futbol Club Barcelona"]),
    ("Girona FC", ["Girona FC"]),
    ("Atlético de Madrid", ["Atlético de Madrid", "Club Atlético de Madrid"]),
    ("Athletic Bilbao", ["Athletic Bilbao", "Athletic Club"]),
    ("Real Sociedad", ["Real Sociedad"]),
    ("Real Betis Balompié", ["Real Betis Balompié", "Real Betis"]),
    ("Villarreal CF", ["Villarreal CF"]),
    ("Valencia CF", ["Valencia CF"]),
    ("Sevilla FC", ["Sevilla FC"]),
    ("Bayer 04 Leverkusen", ["Bayer 04 Leverkusen"]),
    ("Bayern Munich", ["Bayern Munich", "FC Bayern München"]),
    ("VfB Stuttgart", ["VfB Stuttgart"]),
    ("RB Leipzig", ["RB Leipzig", "RasenBallsport Leipzig"]),
    ("Borussia Dortmund", ["Borussia Dortmund"]),
    ("Eintracht Frankfurt", ["Eintracht Frankfurt"]),
    ("TSG 1899 Hoffenheim", ["TSG 1899 Hoffenheim"]),
    ("1.FC Union Berlin", ["1.FC Union Berlin", "1. FC Union Berlin"]),
    ("SC Freiburg", ["SC Freiburg"]),
    ("VfL Wolfsburg", ["VfL Wolfsburg"]),
    ("Inter Milan", ["Inter Milan", "FC Internazionale Milano", "Internazionale"]),
    ("AC Milan", ["AC Milan", "Associazione Calcio Milan"]),
    ("Juventus FC", ["Juventus FC", "Juventus Football Club"]),
    ("Atalanta BC", ["Atalanta BC", "Atalanta Bergamasca Calcio"]),
    ("Bologna FC 1909", ["Bologna FC 1909", "Bologna Football Club 1909"]),
    ("AS Roma", ["AS Roma", "Associazione Sportiva Roma"]),
    ("SS Lazio", ["SS Lazio", "Società Sportiva Lazio S.p.A.", "Società Sportiva Lazio"]),
    ("ACF Fiorentina", ["ACF Fiorentina"]),
    ("SSC Napoli", ["SSC Napoli", "Società Sportiva Calcio Napoli"]),
    ("Torino FC", ["Torino FC"]),
    ("Paris Saint-Germain", ["Paris Saint-Germain", "Paris Saint-Germain Football Club"]),
    ("AS Monaco", ["AS Monaco", "Association Sportive de Monaco Football Club"]),
    ("Stade Brestois 29", ["Stade Brestois 29"]),
    ("LOSC Lille", ["LOSC Lille"]),
    ("OGC Nice", ["OGC Nice"]),
    ("Olympique Lyon", ["Olympique Lyon", "Olympique Lyonnais"]),
    ("RC Lens", ["RC Lens", "Racing Club de Lens"]),
    ("Olympique Marseille", ["Olympique Marseille"]),
    ("Stade Rennais FC", ["Stade Rennais FC", "Stade Rennais"]),
    ("Stade Reims", ["Stade Reims", "Stade de Reims"]),
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


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return " ".join(s.split())


def register_club(club_name_by_id, cid, name):
    cid = clean_id(cid)
    name = clean_value(name)
    if not is_valid_club(name, cid):
        return
    if cid not in club_name_by_id:
        club_name_by_id[cid] = name
        return
    existing = club_name_by_id[cid]
    if len(name) < len(existing) and len(name) >= 4:
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
        norm = normalize_name(str(p["name"]))
        if not norm:
            continue
        name_index.setdefault(norm, []).append(p["player_id"])
    for norm, ids in name_index.items():
        ids.sort(key=lambda pid: (-len(by_id[pid]["clubs"]), by_id[pid]["name"], pid))

    clubs_options = [
        {"id": cid, "name": club_name_by_id[cid]}
        for cid in sorted(clubs_pool_ids, key=lambda c: (club_name_by_id[c].lower(), c))
    ]

    clubs_by_norm_name = defaultdict(list)
    for cid in clubs_pool_ids:
        clubs_by_norm_name[normalize_name(club_name_by_id[cid])].append(cid)

    def _club_candidate_score(cid):
        name = club_name_by_id[cid]
        bad_markers = (" u17", " u18", " u19", " u20", " u21", " youth", " b team", " ii", " reserve", " juvenil", " primavera")
        lname = f" {name.lower()} "
        penalty = sum(5 for m in bad_markers if m in lname)
        return (penalty, len(name), name.lower(), cid)

    top5_league_clubs = []
    seen_top_ids = set()
    for display_name, aliases in TOP5_LEAGUE_CLUB_PREFERENCES:
        candidate_ids = []
        for alias in aliases:
            candidate_ids.extend(clubs_by_norm_name.get(normalize_name(alias), []))
        candidate_ids = sorted(set(candidate_ids), key=_club_candidate_score)
        if not candidate_ids:
            continue
        cid = candidate_ids[0]
        if cid in seen_top_ids:
            continue
        seen_top_ids.add(cid)
        top5_league_clubs.append({"id": cid, "name": club_name_by_id[cid]})

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

    if os.path.isdir(os.path.dirname(FRONTEND_OUTPUT_JSON)):
        with open(FRONTEND_OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Wrote {FRONTEND_OUTPUT_JSON}")

    print("Identified columns:", json.dumps(data["identified_columns"], indent=2))
    print("Stats:", json.dumps(data["stats"], indent=2))
    print(f"Wrote {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
