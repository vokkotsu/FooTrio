# Football Trivia Draft (FooTrio)

A real-time multiplayer football trivia game for **exactly 3 players**. Each round, players draft constraints (Country, Position, Club), reveal them, then race to guess a real-life footballer who matches all three. Built with **FastAPI + WebSockets** (backend) and **React + Vite + Tailwind** (frontend).

Supports **multiplayer rooms** and a **single-player test mode** (you vs 2 bots) so you can try the full flow locally.

## Game Flow

1. **Lobby** – Players create/join a room via WebSocket. The game requires exactly 3 players and **Round 1 starts automatically** when the 3rd joins.
2. **Drafting (constraint selection)** – Each round, the 3 players are randomly assigned one attribute to pick:
   - Player A → **Country**
   - Player B → **Position**
   - Player C → **Club**
   
   Assignments **rotate every round**. Players don’t type values: the backend serves **5 randomized valid options** (from the dataset) for their assigned attribute. Players wait in a “Waiting for others…” state until all 3 have selected.
3. **Reveal & Guessing** – The 3 chosen constraints are revealed to everyone and a **30-second countdown** starts. Each player submits the name of a real-life footballer they think matches the criteria.
4. **Verification & Scoring** – When the timer ends or all players submit, guesses are verified against the dataset. Scoring is **+1 point per fulfilled aspect** (max 3 per round): country match, position match, and club history match (the player played for the chosen club).
5. **Winning condition** – After each round the standings are broadcast. First player to reach **15 points** wins; otherwise a new round begins (back to drafting with rotated assignments).

## Project Structure

```
.
├── backend/
│   ├── main.py            # FastAPI app, /ws endpoint, message routing & broadcasting
│   ├── room_manager.py    # Room state machine (lobby → draft → guess → result/game_over)
│   ├── data_loader.py     # Loads game_data.json, samples options, matches guesses
│   ├── config.py          # Game constants (room size, win score, timers, attributes)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx        # UI + WebSocket client (lobby, draft, guess, results, scoreboard)
│   │   ├── main.jsx
│   │   └── index.css
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── players.csv            # Source player dataset
├── transfers.csv          # Source transfer/club-history dataset
├── preprocess_data.py     # Pandas preprocessing script (CSV → game_data.json)
├── generate_game_data.py  # Stdlib (csv/json) preprocessing script
└── game_data.json         # Pre-generated dataset used by the backend at runtime
```

## Dataset & Preprocessing

The game data is built from the included CSVs:

| Concept | Source column(s) |
|---|---|
| **Player Name** | `players.csv` → `name` |
| **Position** | `players.csv` → `position` (Goalkeeper, Defender, Midfield, Attack) |
| **Country/Nationality** | `players.csv` → `country_of_citizenship` |
| **Club/Club History** | `players.csv` → `current_club_name` **+** `transfers.csv` → `from_club_name`, `to_club_name` (joined on `player_id`) |

`game_data.json` is pre-generated and loaded by the backend. To regenerate it after changing the CSVs:

```bash
# Option A: stdlib only (no extra deps)
python generate_game_data.py

# Option B: pandas
pip install pandas
python preprocess_data.py
```

Both scripts identify the relevant columns, merge club history per player, extract unique option pools (countries/positions/clubs), and write `game_data.json` with player records, a normalized name index for guess verification, and option pools.

## Running (Vercel + local backend)

The frontend is deployed on Vercel (https://footrio-pavo2.vercel.app). To play, run the backend locally and expose it so Vercel can connect:

### Prerequisites
- Python 3.10+
- A tunnel tool in PATH: `cloudflared` (recommended), `ngrok`, or `ssh`

### Start

From the project root:

```bash
python app.py
```

This will start the backend, open a public tunnel, and automatically open https://footrio-pavo2.vercel.app in your browser (with the backend connection attached). Keep the terminal open while playing; press `Ctrl+C` to stop.

Options:
```bash
python app.py --tunnel auto|cloudflared|ngrok|ssh
python app.py --port 8000
```

### Local development (optional)

To run backend and frontend locally without Vercel:

**Backend**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend**
```bash
cd frontend
npm install
npm run dev
```

## Configuration

- **Frontend WebSocket URL:** set `VITE_WS_URL` for non-local/deployed backends (defaults to `ws://localhost:8000/ws` on localhost).
  ```bash
  # example
  VITE_WS_URL=wss://your-backend.example.com/ws npm run dev
  ```
- **Game tuning:** edit `backend/config.py` (`ROOM_SIZE`, `WIN_SCORE`, `DRAFT_OPTIONS`, `GUESS_COUNTDOWN`, etc.).

## WebSocket Events (overview)

| Direction | Event | Purpose |
|---|---|---|
| client → server | `create_room`, `join_room`, `rejoin_room` | Session/room management |
| client → server | `select_option` | Draft pick for assigned attribute |
| client → server | `submit_guess` | Submit guessed player name |
| server → client | `joined`, `lobby_update`, `state_sync` | Join/reconnect & lobby state |

## Deploying (Frontend on Vercel + Backend on a WebSocket host)

This game uses **WebSockets** and **in-memory room state**, so the backend must run on a platform that supports long-lived connections (not Vercel serverless functions). The recommended split is:

- **Frontend (Vite/React)** → Vercel
- **Backend (FastAPI + WebSockets)** → Render, Railway, Fly.io, or any host that supports Docker/WebSockets

### 1) Deploy the backend (Render example)

1. Push this repo to GitHub (if not already).
2. In [Render](https://render.com), create a **Web Service** from the repo.
   - **Option A (Blueprint):** Render can detect `render.yaml` in the repo root.
   - **Option B (Manual):** Runtime **Docker**, Dockerfile path `backend/Dockerfile`, Docker build context `.` (repo root). Set health check path to `/`.
3. Deploy and copy the service URL, e.g. `https://footrio-backend.onrender.com`.
4. Verify: open `https://<your-backend>/` and confirm it returns `{"status":"ok","service":"football-trivia"}`. The WebSocket endpoint is `wss://<your-backend>/ws`.

Notes:
- `backend/Dockerfile` copies `backend/` and `game_data.json` from the repo root, so deploy from the **repository root** context.
- Free tiers may sleep when idle (first connect can be slow) and in-memory rooms reset on restart/redeploy. For a demo this is usually fine.

### 2) Deploy the frontend (Vercel)

1. In [Vercel](https://vercel.com), **Add New Project** and import the same GitHub repo.
2. Set **Root Directory** to `frontend`.
3. Framework preset: **Vite** (auto-detected). Build command: `npm run build`. Output directory: `dist`.
4. Add environment variable:
   - `VITE_WS_URL` = `wss://<your-backend-host>/ws` (example: `wss://footrio-backend.onrender.com/ws`)
5. Deploy. Open the Vercel URL and test creating/joining a room (single-player mode is the quickest check).

`frontend/vercel.json` is included for SPA rewrites. If you change `VITE_WS_URL`, redeploy the frontend so the value is baked into the Vite build.

### Local production-like test

```bash
# backend
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000

# frontend (in another terminal) with explicit WS URL
cd frontend
VITE_WS_URL=ws://localhost:8000/ws npm run build
npm run preview
```

| server → client | `round_started`, `draft_prompt`, `draft_status` | Draft phase & options |
| server → client | `guess_phase`, `guess_update` | Reveal constraints & guess timer |
| server → client | `round_result`, `game_over` | Verification, scoring, standings, winner |
