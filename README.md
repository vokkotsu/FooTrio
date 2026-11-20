# FooTrio (Football Trivia Draft) — PHP version

A real-time multiplayer football trivia game for **exactly 3 players** (with single-player and duo-vs-bot modes). Each round, players draft constraints (Country, Position, Club), reveal them, then race to guess a real-life footballer who matches all three.

This `php` branch is a functionally equivalent port of the original Python FastAPI backend to **PHP** (Ratchet/ReactPHP WebSockets) so it can be deployed as a PHP project, while keeping the same React frontend and gameplay behavior.

## Game Flow

1. **Lobby** – Players create/join a room via WebSocket. The game requires exactly 3 players (or 2 in duo mode, or 1 vs 2 bots in single-player) and **Round 1 starts automatically** when the room is full.
2. **Drafting (constraint selection)** – Each round, players are assigned an attribute to pick (**Country**, **Position**, **Club**). Assignments **rotate every round**. The backend serves **5 randomized valid options** for the assigned attribute (with biased pools for countries/clubs). Players can refresh options (limited) and have a draft timer; missing picks are auto-selected when time runs out.
3. **Reveal & Guessing** – The chosen constraints are revealed to everyone and a **60-second countdown** starts. Each player submits the name of a real-life footballer they think matches the criteria (with name suggestions).
4. **Verification & Scoring** – When the timer ends or all players submit, guesses are verified against the dataset. Scoring is **+1 point per fulfilled aspect** (max 3 per round): country match, position match, and club history match.
5. **Winning condition** – After each round standings are broadcast. First player to reach **15 points** wins (draw if multiple reach in the same round); otherwise a new round begins automatically.

## Project Structure

- `backend_php/` — PHP WebSocket server (Ratchet/ReactPHP) and game logic.
  - `server.php` — WebSocket server, message handling, and timers (draft/guess timeouts, next-round scheduling).
  - `room_manager.php` — rooms, sessions, round flow, scoring, and state snapshots.
  - `data_loader.php` — loads `game_data.json`, samples options, matches guesses, and provides suggestions/best answers.
  - `config.php` — game constants.
  - `composer.json` — PHP dependencies.
- `backend/` — original Python backend (kept for reference).
- `frontend/` — React (Vite) + Tailwind CSS client. Includes local single-player/duo logic in `src/gameLogic.js` for browser-only play, and multiplayer over WebSockets.
- `game_data.json` — pre-generated dataset used by the PHP backend at runtime (loaded from project root).
- `index.php` — PHP front controller to serve the built SPA from `frontend/dist`.
- `.htaccess` — rewrite rules for SPA routing on Apache/PHP hosts.
- `run_php.php` — convenience script to start PHP WS backend + PHP static frontend server.
- `app.py`, `run.py` (if present) — original Python convenience scripts (kept for reference).

## Dataset

`game_data.json` is built from the included CSVs (`players.csv`, `transfers.csv`). To regenerate it after changing the CSVs, use the original scripts:

```bash
# Option A: stdlib only (no extra deps)
python generate_game_data.py

# Option B: pandas
pip install pandas
python preprocess_data.py
```

## Run Locally (PHP)

**Prerequisites:** PHP 8.1+ with Composer, and Node.js/npm (to build the frontend assets). Recommended PHP extensions: `json`, `mbstring` (and `intl` for best Unicode name normalization).

### 1. Install PHP backend dependencies

```bash
cd backend_php
composer install
```

### 2. Build the frontend

```bash
cd frontend
npm install --include=dev
npm run build
```

For local multiplayer, the frontend defaults to `ws://localhost:8000/ws` when running on localhost. For deployed builds, set `VITE_WS_URL` to your PHP WebSocket endpoint before building (e.g. `wss://<your-ws-host>/ws`):

```bash
# example
VITE_WS_URL=wss://your-ws-host/ws npm run build
```

### 3. Start the PHP servers

From the project root:

```bash
php run_php.php
```

- WebSocket backend: `ws://localhost:8000/ws` (same protocol and message types as the original backend)
- Frontend (built SPA): http://localhost:5173 (served via PHP built-in server + `index.php`)

Open the frontend URL and start playing. Press `Ctrl+C` to stop.

> Single-player and 2-player-vs-bot modes run locally in the browser and do not require the backend.

## Deployment (PHP)

- **Frontend/static SPA:** deploy the project on a PHP-capable web server with the document root at the project root (or route all non-file requests to `index.php`). `index.php` serves files from `frontend/dist` with SPA fallback. Ensure `frontend/dist` is built with the correct `VITE_WS_URL`.
- **WebSocket backend:** run the Ratchet server as a long-running PHP process on a host that supports persistent processes (VPS/container/PaaS with worker support):

  ```bash
  cd backend_php && composer install
  php server.php
  ```

  It listens on port `8000` by default, or the `$PORT` environment variable if provided. The WebSocket endpoint is `/ws` (e.g. `wss://your-host/ws`). The backend reads `game_data.json` from the project root (`../game_data.json` relative to `backend_php/`).

- Multiplayer room state is in-memory (resets on restart/redeploy), same as the original implementation.

## WebSocket Protocol

The WebSocket protocol and game behavior (room modes, drafting/guessing flow, timers, scoring, state sync/rejoin, player suggestions, etc.) match the original implementation so the existing frontend works without changes.
