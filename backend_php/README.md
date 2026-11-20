# FooTrio PHP Backend

PHP (Ratchet/ReactPHP) WebSocket backend for FooTrio multiplayer, functionally equivalent to the original Python FastAPI backend.

## Requirements

- PHP 8.1+
- Composer
- Extensions: `json`, `mbstring` (recommended: `intl` for accurate Unicode normalization)

## Install

```bash
composer install
```

## Run

```bash
php server.php
```

The server listens on port `8000` by default, or the `$PORT` environment variable if set. WebSocket endpoint: `ws://localhost:8000/ws`.

It loads game data from `../game_data.json` (project root). Run this from the project root context or ensure the data file is available at that path.
