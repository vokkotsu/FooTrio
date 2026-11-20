import csv
import json
import os
import re
import unicodedata
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
PLAYERS_CSV = os.path.join(BASE, "players.csv")
TRANSFERS_CSV = os.path.join(BASE, "transfers.csv")
OUT_JSON = os.path.join(BASE, "game_data.json")
FRONTEND_OUT_JSON = os.path.join(BASE, "frontend", "src", "game_data.json")

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

# Preferred options for drafts: include aliases so curated picks resolve to the
# exact club entity present in this dataset even when display names differ.
TOP5_LEAGUE_CLUB_PREFERENCES = [
    ("Manchester City", ["Manchester City", "Man City"]),
    ("Arsenal FC", ["Arsenal FC", "Arsenal", "Arsenal Football Club"]),
    ("Liverpool FC", ["Liverpool FC", "Liverpool", "Liverpool Football Club"]),
    ("Aston Villa", ["Aston Villa"]),
    ("Tottenham Hotspur", ["Tottenham Hotspur", "Tottenham"]),
    ("Chelsea FC", ["Chelsea FC", "Chelsea", "Chelsea Football Club"]),
    ("Newcastle United", ["Newcastle United", "Newcastle"]),
    ("Manchester United", ["Manchester United", "Man Utd", "Manchester Utd"]),
    ("West Ham United", ["West Ham United", "West Ham"]),
    ("Brighton & Hove Albion", ["Brighton & Hove Albion", "Brighton"]),
    ("Real Madrid", ["Real Madrid", "Real Madrid CF", "Real Madrid Club de Fútbol"]),
    ("FC Barcelona", ["FC Barcelona", "Barcelona", "Futbol Club Barcelona"]),
    ("Girona FC", ["Girona FC", "Girona"]),
    ("Atlético de Madrid", ["Atlético de Madrid", "Atletico Madrid", "Atlético Madrid", "Club Atlético de Madrid"]),
    ("Athletic Bilbao", ["Athletic Bilbao", "Athletic Club"]),
    ("Real Sociedad", ["Real Sociedad"]),
    ("Real Betis Balompié", ["Real Betis Balompié", "Real Betis"]),
    ("Villarreal CF", ["Villarreal CF", "Villarreal"]),
    ("Valencia CF", ["Valencia CF", "Valencia"]),
    ("Sevilla FC", ["Sevilla FC", "Sevilla"]),
    ("Bayer 04 Leverkusen", ["Bayer 04 Leverkusen", "Bayer Leverkusen", "Leverkusen"]),
    ("Bayern Munich", ["Bayern Munich", "FC Bayern München", "Bayern München"]),
    ("VfB Stuttgart", ["VfB Stuttgart", "Stuttgart"]),
    ("RB Leipzig", ["RB Leipzig", "RasenBallsport Leipzig", "Leipzig"]),
    ("Borussia Dortmund", ["Borussia Dortmund", "Dortmund", "BVB"]),
    ("Eintracht Frankfurt", ["Eintracht Frankfurt", "Frankfurt"]),
    ("TSG 1899 Hoffenheim", ["TSG 1899 Hoffenheim", "Hoffenheim"]),
    ("1.FC Union Berlin", ["1.FC Union Berlin", "1. FC Union Berlin", "Union Berlin"]),
    ("SC Freiburg", ["SC Freiburg", "Freiburg"]),
    ("VfL Wolfsburg", ["VfL Wolfsburg", "Wolfsburg"]),
    ("Inter Milan", ["Inter Milan", "Inter", "FC Internazionale Milano", "Internazionale"]),
    ("AC Milan", ["AC Milan", "Milan", "Associazione Calcio Milan"]),
    ("Juventus FC", ["Juventus FC", "Juventus", "Juventus Football Club"]),
    ("Atalanta BC", ["Atalanta BC", "Atalanta", "Atalanta Bergamasca Calcio"]),
    ("Bologna FC 1909", ["Bologna FC 1909", "Bologna", "Bologna Football Club 1909"]),
    ("AS Roma", ["AS Roma", "Roma", "Associazione Sportiva Roma"]),
    ("SS Lazio", ["SS Lazio", "Lazio", "Società Sportiva Lazio S.p.A.", "Società Sportiva Lazio"]),
    ("ACF Fiorentina", ["ACF Fiorentina", "Fiorentina"]),
    ("SSC Napoli", ["SSC Napoli", "Napoli", "Società Sportiva Calcio Napoli"]),
    ("Torino FC", ["Torino FC", "Torino"]),
    ("Paris Saint-Germain", ["Paris Saint-Germain", "Paris SG", "Paris Saint-Germain Football Club", "PSG"]),
    ("AS Monaco", ["AS Monaco", "Monaco", "Association Sportive de Monaco Football Club"]),
    ("Stade Brestois 29", ["Stade Brestois 29", "Stade Brestois", "Brest"]),
    ("LOSC Lille", ["LOSC Lille", "Lille"]),
    ("OGC Nice", ["OGC Nice", "Nice"]),
    ("Olympique Lyon", ["Olympique Lyon", "Olympique Lyonnais", "Lyon"]),
    ("RC Lens", ["RC Lens", "Lens", "Racing Club de Lens"]),
    ("Olympique Marseille", ["Olympique Marseille", "Marseille"]),
    ("Stade Rennais FC", ["Stade Rennais FC", "Stade Rennais", "Rennes"]),
    ("Stade Reims", ["Stade Reims", "Reims", "Stade de Reims"]),
]


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return " ".join(s.split())


PREFERRED_CLUB_NAMES_BY_ID = {
    "46": "Inter Milan",
    "12": "AS Roma",
    "398": "SS Lazio",
    "1025": "Bologna FC 1909",
    "281": "Manchester City",
    "631": "Chelsea FC",
    "985": "Manchester United",
    "148": "Tottenham Hotspur",
    "762": "Newcastle United",
    "379": "West Ham United",
    "1237": "Brighton & Hove Albion",
    "131": "FC Barcelona",
    "418": "Real Madrid",
    "13": "Atlético de Madrid",
    "621": "Athletic Bilbao",
    "1050": "Villarreal CF",
    "1049": "Valencia CF",
    "150": "Real Betis",
    "368": "Sevilla FC",
    "12321": "Girona FC",
    "681": "Real Sociedad",
    "15": "Bayer 04 Leverkusen",
    "27": "Bayern Munich",
    "79": "VfB Stuttgart",
    "23826": "RB Leipzig",
    "16": "Borussia Dortmund",
    "24": "Eintracht Frankfurt",
    "533": "TSG 1899 Hoffenheim",
    "89": "1.FC Union Berlin",
    "60": "SC Freiburg",
    "82": "VfL Wolfsburg",
    "5": "AC Milan",
    "506": "Juventus FC",
    "800": "Atalanta BC",
    "430": "ACF Fiorentina",
    "6195": "SSC Napoli",
    "416": "Torino FC",
    "583": "Paris Saint-Germain",
    "162": "AS Monaco",
    "3911": "Stade Brestois 29",
    "1082": "LOSC Lille",
    "417": "OGC Nice",
    "1041": "Olympique Lyon",
    "826": "RC Lens",
    "244": "Olympique Marseille",
    "273": "Stade Rennais FC",
    "1421": "Stade Reims",
    "11": "Arsenal FC",
    "31": "Liverpool FC",
    "405": "Aston Villa",
}


def _name_quality(name: str):
    lname = f" {name.lower()} "
    bad_markers = (" u17", " u18", " u19", " u20", " u21", " u23", " youth", " b team", " ii", " reserve", " juvenil", " primavera", " yth", " sub-")
    penalty = sum(5 for m in bad_markers if m in lname)
    # prefer reasonably short, readable names but not tiny abbreviations
    short_penalty = 2 if len(name) <= 3 else 0
    return (penalty, short_penalty, len(name), name.lower())


def register_club(club_name_by_id, club_names_by_id, cid, name):
    cid = clean_id(cid)
    name = clean(name)
    if not is_valid_club(name, cid):
        return
    club_names_by_id.setdefault(cid, set()).add(name)
    preferred = PREFERRED_CLUB_NAMES_BY_ID.get(cid)
    if preferred:
        club_name_by_id[cid] = preferred
        return
    if cid not in club_name_by_id:
        club_name_by_id[cid] = name
        return
    existing = club_name_by_id[cid]
    if _name_quality(name) < _name_quality(existing):
        club_name_by_id[cid] = name


def main():
    players = {}
    club_name_by_id = {}
    club_names_by_id = defaultdict(set)

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
                register_club(club_name_by_id, club_names_by_id, current_club_id, current_club)
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
                    register_club(club_name_by_id, club_names_by_id, cid, cname)
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
        norm = normalize_name(p["name"])
        if not norm:
            continue
        name_index[norm].append(p["player_id"])
    for norm, ids in name_index.items():
        ids.sort(key=lambda pid: (-len(by_id[pid]["clubs"]), by_id[pid]["name"], pid))
        name_index[norm] = ids

    clubs_options = [
        {"id": cid, "name": club_name_by_id[cid]}
        for cid in sorted(clubs_pool_ids, key=lambda c: (club_name_by_id[c].lower(), c))
    ]

    # popularity helps pick the real/main club when aliases collide (e.g. Arsenal, Juventus)
    player_count_by_club = defaultdict(int)
    for p in records:
        for cid in p["clubs"]:
            player_count_by_club[cid] += 1

    clubs_by_norm_name = defaultdict(list)
    for cid in clubs_pool_ids:
        names = set(club_names_by_id.get(cid, set()))
        names.add(club_name_by_id[cid])
        for nm in names:
            norm = normalize_name(nm)
            if norm:
                clubs_by_norm_name[norm].append(cid)

    def _club_candidate_score(cid):
        name = club_name_by_id[cid]
        lname = f" {name.lower()} "
        bad_markers = (" u17", " u18", " u19", " u20", " u21", " u23", " youth", " b team", " ii", " reserve", " juvenil", " primavera", " yth", " sub-")
        penalty = sum(5 for m in bad_markers if m in lname)
        popularity = player_count_by_club.get(cid, 0)
        # prefer non-youth, more-referenced clubs; then cleaner/shorter names
        return (penalty, -popularity, len(name), name.lower(), cid)

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

    if os.path.isdir(os.path.dirname(FRONTEND_OUT_JSON)):
        with open(FRONTEND_OUT_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print("Wrote", FRONTEND_OUT_JSON)

    print(json.dumps(data["identified_columns"], indent=2))
    print(json.dumps(data["stats"], indent=2))
    print("Wrote", OUT_JSON)


if __name__ == "__main__":
    main()
