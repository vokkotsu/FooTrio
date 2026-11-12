import asyncio
import json
import os
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from room_manager import manager
from data_loader import sample_options, search_player_names
import config

app = FastAPI(title="Football Trivia Multiplayer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def broadcast_lobby(room):
    await room.broadcast(
        {
            "type": "lobby_update",
            "players": room.player_list(),
            "hostId": room.host_id,
            "roomSize": config.ROOM_SIZE,
        }
    )


async def send_draft_prompts(room):
    for pid, attr in room.assignments.items():
        if room.is_bot(pid):
            continue
        options = room.draft_options.get(pid, [])
        if attr and not options:
            options = sample_options(attr, config.DRAFT_OPTIONS)
            room.draft_options[pid] = options
        await room.send_to(
            pid,
            {
                "type": "draft_prompt",
                "round": room.round_number,
                "attribute": attr,
                "attributeLabel": config.ATTRIBUTE_LABELS.get(attr, attr),
                "options": options,
                "selected": room.selections.get(pid),
                "secondsLeft": room.draft_seconds_left() or config.DRAFT_COUNTDOWN,
                "refreshesLeft": room.draft_refreshes_left.get(pid, 0),
            },
        )
    await room.broadcast(
        {
            "type": "draft_status",
            "round": room.round_number,
            "submittedCount": len(room.selections),
            "requiredCount": config.ROOM_SIZE,
            "secondsLeft": room.draft_seconds_left() or config.DRAFT_COUNTDOWN,
        }
    )


async def send_state_sync(room):
    for pid in room.players:
        if room.is_bot(pid):
            continue
        await room.send_to(pid, room.state_snapshot(pid))


async def start_round(room):
    if not room.all_players_connected():
        return
    room.start_round()
    await room.broadcast(
        {
            "type": "round_started",
            "round": room.round_number,
            "players": room.player_list(),
        }
    )
    await send_draft_prompts(room)
    # ensure each human has full state (reliable draft prompt delivery)
    await send_state_sync(room)
    # if bots already satisfied all selections (e.g. no humans), advance
    if room.all_selected():
        await begin_guessing(room)
    else:
        schedule_draft_timeout(room)


def schedule_guess_timeout(room):
    room.cancel_guess_timer()

    async def _timeout():
        try:
            await asyncio.sleep(config.GUESS_COUNTDOWN)
            async with room.lock:
                if room.state != "guessing":
                    return
                await finalize_and_broadcast(room)
        except asyncio.CancelledError:
            return
        finally:
            if room.guess_task is asyncio.current_task():
                room.guess_task = None

    room.guess_task = asyncio.create_task(_timeout())


def schedule_draft_timeout(room):
    room.cancel_draft_timer()

    async def _timeout():
        try:
            await asyncio.sleep(config.DRAFT_COUNTDOWN)
            async with room.lock:
                if room.state != "drafting":
                    return
                room.auto_select_missing()
                await room.broadcast(
                    {
                        "type": "draft_status",
                        "round": room.round_number,
                        "submittedCount": len(room.selections),
                        "requiredCount": config.ROOM_SIZE,
                        "secondsLeft": 0,
                    }
                )
                if room.all_selected():
                    await begin_guessing(room)
        except asyncio.CancelledError:
            return
        finally:
            if room.draft_task is asyncio.current_task():
                room.draft_task = None

    room.draft_task = asyncio.create_task(_timeout())


async def begin_guessing(room):
    if room.state != "drafting":
        return
    room.start_guessing()
    # bots submit guesses immediately
    room._auto_guess_bots()
    constraints = room.current_constraints()
    await room.broadcast(
        {
            "type": "guess_phase",
            "round": room.round_number,
            "constraints": constraints,
            "secondsLeft": config.GUESS_COUNTDOWN,
            "submittedCount": len(room.guesses),
            "requiredCount": config.ROOM_SIZE,
        }
    )
    await send_state_sync(room)
    if room.all_guessed():
        await finalize_and_broadcast(room)
    else:
        schedule_guess_timeout(room)


async def finalize_and_broadcast(room):
    if room.state != "guessing":
        return
    result = room.finalize_round()
    if not result:
        return
    await room.broadcast({"type": "round_result", **result, "players": room.player_list()})
    if result.get("gameOver"):
        winner = None
        for p in room.player_list():
            if p["id"] == result.get("winnerId"):
                winner = p
                break
        await room.broadcast(
            {
                "type": "game_over",
                "winnerId": result.get("winnerId"),
                "winnerName": winner["name"] if winner else None,
                "draw": bool(result.get("draw")),
                "players": room.player_list(),
                "history": room.history,
            }
        )
    else:
        # auto-start next round after a short reveal
        async def _next():
            try:
                await asyncio.sleep(config.REVEAL_DELAY + 4)
                async with room.lock:
                    if room.state == "result" and room.all_players_connected():
                        await start_round(room)
            except asyncio.CancelledError:
                return

        asyncio.create_task(_next())


@app.get("/")
def root():
    return {"status": "ok", "service": "football-trivia"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    player_id = str(uuid.uuid4())
    room = None
    code = None
    rejoined = False
    explicit_leave = False

    try:
        raw = await ws.receive_text()
        data = json.loads(raw)
        msg_type = data.get("type")

        if msg_type == "create_room":
            name = (data.get("name") or "Player").strip() or "Player"
            mode = (data.get("mode") or "multi").strip().lower()
            single_player = mode == "single"
            code = manager.create_room(player_id, single_player=single_player)
            room = manager.get_room(code)
            room.add_player(player_id, name, ws)
            if single_player:
                room.add_bot("Bot 1")
                room.add_bot("Bot 2")
        elif msg_type == "join_room":
            name = (data.get("name") or "Player").strip() or "Player"
            code = (data.get("code") or "").strip().upper()
            room = manager.get_room(code)
            if room is None:
                await ws.send_json({"type": "error", "message": "Room not found"})
                await ws.close()
                return
            if room.single_player:
                await ws.send_json({"type": "error", "message": "Single-player room"})
                await ws.close()
                return
            if room.state != "lobby":
                await ws.send_json({"type": "error", "message": "Game already in progress"})
                await ws.close()
                return
            if len(room.players) >= config.ROOM_SIZE:
                await ws.send_json({"type": "error", "message": "Room is full"})
                await ws.close()
                return
            room.add_player(player_id, name, ws)
        elif msg_type == "rejoin_room":
            player_id = (data.get("playerId") or "").strip()
            code = (data.get("code") or "").strip().upper()
            room = manager.get_room(code)
            if room is None or not player_id or player_id not in room.players:
                await ws.send_json({"type": "session_invalid", "message": "Session not found"})
                await ws.close()
                return
            room.attach_player(player_id, ws)
            rejoined = True
            await ws.send_json(room.state_snapshot(player_id))
            await broadcast_lobby(room)
        else:
            await ws.send_json({"type": "error", "message": "First message must create, join, or rejoin a room"})
            await ws.close()
            return

        if not rejoined:
            await ws.send_json(
                {
                    "type": "joined",
                    "playerId": player_id,
                    "code": code,
                    "name": room.players.get(player_id),
                    "isHost": player_id == room.host_id,
                    "players": room.player_list(),
                    "roomSize": config.ROOM_SIZE,
                }
            )
            # broadcast lobby state to others, then send a fresh lobby_update to the
            # joining socket too (in case the "joined" message was missed client-side)
            await room.broadcast(
                {
                    "type": "lobby_update",
                    "players": room.player_list(),
                    "hostId": room.host_id,
                    "roomSize": config.ROOM_SIZE,
                },
                exclude_pid=player_id,
            )
            await ws.send_json(
                {
                    "type": "lobby_update",
                    "players": room.player_list(),
                    "hostId": room.host_id,
                    "roomSize": config.ROOM_SIZE,
                }
            )
            # auto-start when 3 players present
            if room.state == "lobby" and room.all_players_connected():
                async with room.lock:
                    if room.state == "lobby" and room.all_players_connected():
                        await start_round(room)

        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            t = data.get("type")

            async with room.lock:
                if t == "select_option":
                    if room.state != "drafting":
                        continue
                    value = data.get("value")
                    ok, err = room.submit_selection(player_id, value)
                    if not ok:
                        await ws.send_json({"type": "error", "message": err or "Invalid selection"})
                        continue
                    # confirm to selector and update draft status
                    await room.send_to(
                        player_id,
                        {
                            "type": "draft_selected",
                            "attribute": room.assignments.get(player_id),
                            "value": value,
                        },
                    )
                    await room.broadcast(
                        {
                            "type": "draft_status",
                            "round": room.round_number,
                            "submittedCount": len(room.selections),
                            "requiredCount": config.ROOM_SIZE,
                            "secondsLeft": room.draft_seconds_left() or 0,
                        }
                    )
                    if room.all_selected():
                        await begin_guessing(room)

                elif t == "submit_guess":
                    if room.state != "guessing":
                        continue
                    guess = data.get("guess")
                    ok, err = room.submit_guess(player_id, guess)
                    if not ok:
                        await ws.send_json({"type": "error", "message": err or "Invalid guess"})
                        continue
                    await room.broadcast(
                        {
                            "type": "guess_update",
                            "submittedCount": len(room.guesses),
                            "requiredCount": config.ROOM_SIZE,
                        }
                    )
                    if room.all_guessed():
                        await finalize_and_broadcast(room)

                elif t == "search_players":
                    if room.state != "guessing":
                        await ws.send_json({"type": "player_suggestions", "query": data.get("query") or "", "suggestions": []})
                    else:
                        q = (data.get("query") or "").strip()
                        suggestions = search_player_names(q, 8) if q else []
                        await ws.send_json({"type": "player_suggestions", "query": data.get("query") or "", "suggestions": suggestions})

                elif t == "refresh_draft":
                    if room.state != "drafting":
                        await ws.send_json({"type": "error", "message": "Not in drafting phase"})
                        continue
                    ok, err, options, refreshes_left = room.refresh_draft_options(player_id)
                    if not ok:
                        await ws.send_json({"type": "error", "message": err or "Could not refresh options"})
                        continue
                    attr = room.assignments.get(player_id)
                    await room.send_to(
                        player_id,
                        {
                            "type": "draft_prompt",
                            "round": room.round_number,
                            "attribute": attr,
                            "attributeLabel": config.ATTRIBUTE_LABELS.get(attr, attr),
                            "options": options,
                            "selected": room.selections.get(player_id),
                            "secondsLeft": room.draft_seconds_left() if room.draft_seconds_left() is not None else 0,
                            "refreshesLeft": refreshes_left,
                        },
                    )

                elif t == "leave":
                    explicit_leave = True
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if room is not None and code is not None and player_id in room.players:
            if explicit_leave:
                room.remove_player(player_id)
                if not room.players:
                    room.cancel_guess_timer()
                    room.cancel_draft_timer()
                    manager.remove_room(code)
                else:
                    await room.broadcast(
                        {
                            "type": "player_left",
                            "playerId": player_id,
                            "players": room.player_list(),
                            "state": room.state,
                        }
                    )
                    await broadcast_lobby(room)
            else:
                room.detach_player(player_id)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
