import asyncio
import random
import string
import time

from data_loader import sample_options, find_player_matches, best_guess_for_constraints, get_options, club_matches
import config


class Room:
    def __init__(self, code, host_id, single_player=False):
        self.code = code
        self.host_id = host_id
        self.single_player = single_player
        self.players = {}  # pid -> name (humans and bots)
        self.player_ws = {}  # pid -> websocket (humans only)
        self.bot_ids = set()  # pids that are bots
        self.scores = {}  # pid -> int
        self.state = "lobby"  # lobby | drafting | guessing | result | game_over
        self.round_number = 0
        self.history = []

        self.assignment_offset = 0
        self.assignments = {}  # pid -> attribute
        self.draft_options = {}  # pid -> [options]
        self.draft_refreshes_left = {}  # pid -> int
        self.selections = {}  # pid -> chosen value
        self.guesses = {}  # pid -> {"text": str, "submitted_at": float}
        self.round_result = None
        self.winner_id = None

        self.guess_deadline = None
        self.guess_task = None
        self.draft_deadline = None
        self.draft_task = None
        self.lock = asyncio.Lock()

    # --- player management ---
    def add_player(self, pid, name, ws):
        if len(self.players) >= config.ROOM_SIZE:
            return False
        self.players[pid] = name
        self.player_ws[pid] = ws
        self.scores.setdefault(pid, 0)
        return True

    def add_bot(self, name):
        if len(self.players) >= config.ROOM_SIZE:
            return None
        pid = f"bot-{len(self.bot_ids) + 1}"
        self.players[pid] = name
        self.bot_ids.add(pid)
        self.scores.setdefault(pid, 0)
        return pid

    def is_bot(self, pid):
        return pid in self.bot_ids

    def remove_player(self, pid):
        self.players.pop(pid, None)
        self.player_ws.pop(pid, None)
        self.bot_ids.discard(pid)
        self.scores.pop(pid, None)
        self.selections.pop(pid, None)
        self.guesses.pop(pid, None)
        # keep assignments/options for the round but host may need reassignment
        if pid == self.host_id and self.players:
            self.host_id = next(iter(self.players))

    def detach_player(self, pid):
        self.player_ws.pop(pid, None)

    def attach_player(self, pid, ws):
        if pid in self.players and not self.is_bot(pid):
            self.player_ws[pid] = ws
            return True
        return False

    def player_list(self):
        ordered = list(self.players.keys())
        return [
            {
                "id": pid,
                "name": self.players[pid],
                "score": self.scores.get(pid, 0),
                "isHost": pid == self.host_id,
                "isBot": self.is_bot(pid),
            }
            for pid in ordered
        ]

    async def broadcast(self, msg):
        dead = []
        for pid, ws in list(self.player_ws.items()):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(pid)
        for pid in dead:
            self.detach_player(pid)

    async def send_to(self, pid, msg):
        ws = self.player_ws.get(pid)
        if not ws:
            return
        try:
            await ws.send_json(msg)
        except Exception:
            self.detach_player(pid)

    # --- helpers ---
    def all_players_connected(self):
        # humans+bots must fill the room
        return len(self.players) == config.ROOM_SIZE

    def attribute_for(self, pid):
        return self.assignments.get(pid)

    def _ordered_pids(self):
        # stable order of join
        return list(self.players.keys())

    # --- game flow ---
    def start_round(self):
        if len(self.players) != config.ROOM_SIZE:
            return False
        self.cancel_guess_timer()
        self.cancel_draft_timer()
        self.state = "drafting"
        self.round_number += 1
        self.selections = {}
        self.guesses = {}
        self.round_result = None
        self.guess_deadline = None
        self.draft_deadline = time.monotonic() + config.DRAFT_COUNTDOWN

        pids = self._ordered_pids()
        attrs = config.ATTRIBUTE_ORDER
        self.assignments = {}
        self.draft_options = {}
        self.draft_refreshes_left = {}
        for i, pid in enumerate(pids):
            attr = attrs[(i + self.assignment_offset) % len(attrs)]
            self.assignments[pid] = attr
            self.draft_options[pid] = sample_options(attr, config.DRAFT_OPTIONS)
            self.draft_refreshes_left[pid] = 3 if attr in ("country", "position", "club") else 0

        # auto-select for bots
        self._auto_select_bots()
        return True

    def _pick_bot_option(self, attr, options):
        options = [o for o in (options or []) if o]
        if not options:
            return None
        opts = get_options()
        priority = []
        if attr == "country":
            priority = opts.get("top_fifa_countries") or []
        elif attr == "club":
            priority = opts.get("top5_league_clubs") or []
        priority_in_options = [o for o in options if o in set(priority)]
        others = [o for o in options if o not in set(priority_in_options)]
        # most likely choose from the biased/top picks when available
        if priority_in_options and (not others or random.random() < 0.8):
            return random.choice(priority_in_options)
        return random.choice(options)

    def _auto_select_bots(self):
        for pid in list(self.bot_ids):
            if pid in self.selections:
                continue
            options = self.draft_options.get(pid) or []
            choice = self._pick_bot_option(self.assignments.get(pid), options)
            if choice is not None:
                self.selections[pid] = choice

    def _auto_guess_bots(self):
        if self.state != "guessing":
            return
        constraints = self.current_constraints()
        for pid in list(self.bot_ids):
            if pid in self.guesses:
                continue
            guess_text = best_guess_for_constraints(constraints)
            self.guesses[pid] = {"text": guess_text, "submitted_at": time.monotonic()}

    def submit_selection(self, pid, value):
        if self.state != "drafting":
            return False, "Not in drafting phase"
        if pid not in self.assignments:
            return False, "Not in this round"
        if pid in self.selections:
            return False, "Already selected"
        attr = self.assignments[pid]
        options = self.draft_options.get(pid, [])
        if value not in options:
            return False, "Invalid selection"
        self.selections[pid] = value
        return True, None

    def refresh_draft_options(self, pid):
        if self.state != "drafting":
            return False, "Not in drafting phase", None, 0
        if pid not in self.assignments:
            return False, "Not in this round", None, 0
        if pid in self.selections:
            return False, "Already selected", None, 0
        attr = self.assignments.get(pid)
        if attr not in ("country", "position", "club"):
            return False, "Refresh not available for this attribute", None, 0
        left = self.draft_refreshes_left.get(pid, 0)
        if left <= 0:
            return False, "No refreshes left", None, 0

        current = set(self.draft_options.get(pid) or [])
        options = sample_options(attr, config.DRAFT_OPTIONS)
        # try to provide a completely new set of options when possible (bias preserved by sample_options)
        best_options = options
        best_overlap = len(set(options) & current)
        if best_overlap > 0 and current:
            for _ in range(25):
                candidate = sample_options(attr, config.DRAFT_OPTIONS)
                overlap = len(set(candidate) & current)
                if overlap < best_overlap:
                    best_options = candidate
                    best_overlap = overlap
                if best_overlap == 0:
                    break
        options = best_options

        self.draft_options[pid] = options
        self.draft_refreshes_left[pid] = left - 1
        return True, None, options, self.draft_refreshes_left[pid]

    def auto_select_missing(self):
        changed = False
        for pid in self._ordered_pids():
            if pid in self.selections:
                continue
            options = self.draft_options.get(pid) or []
            if not options:
                attr = self.assignments.get(pid)
                if attr:
                    options = sample_options(attr, config.DRAFT_OPTIONS)
                    self.draft_options[pid] = options
            choice = self._pick_bot_option(self.assignments.get(pid), options)
            if choice is not None:
                self.selections[pid] = choice
                changed = True
        return changed

    def all_selected(self):
        return len(self.selections) == config.ROOM_SIZE and self.all_players_connected()

    def current_constraints(self):
        # map attribute -> chosen value
        out = {}
        for pid, attr in self.assignments.items():
            if pid in self.selections:
                out[attr] = self.selections[pid]
        return out

    def start_guessing(self):
        if self.state != "drafting":
            return False
        self.cancel_draft_timer()
        self.state = "guessing"
        self.guesses = {}
        self.guess_deadline = time.monotonic() + config.GUESS_COUNTDOWN
        return True

    def submit_guess(self, pid, text):
        if self.state != "guessing":
            return False, "Not in guessing phase"
        if pid not in self.players:
            return False, "Not in room"
        if pid in self.guesses:
            return False, "Already guessed"
        guess_text = (text or "").strip()
        if not guess_text:
            return False, "Guess cannot be empty"
        self.guesses[pid] = {"text": guess_text, "submitted_at": time.monotonic()}
        return True, None

    def all_guessed(self):
        return len(self.guesses) == config.ROOM_SIZE and self.all_players_connected()

    def _score_guess(self, guess_text, constraints):
        matches = find_player_matches(guess_text)
        if not matches:
            return {
                "guess": guess_text,
                "matched_player": None,
                "breakdown": {"country": False, "position": False, "club": False},
                "points": 0,
            }
        # choose best match by constraint points, then by richer/cleaner record to avoid
        # ambiguous-name collisions (e.g. different players sharing the same name)
        best = None
        for player in matches:
            clubs = [c for c in (player.get("clubs") or []) if isinstance(c, str) and c.strip()]
            breakdown = {
                "country": player.get("country") == constraints.get("country"),
                "position": player.get("position") == constraints.get("position"),
                "club": club_matches(constraints.get("club"), clubs),
            }
            points = sum(1 for v in breakdown.values() if v)
            club_history_len = len(set(clubs))
            name = (player.get("name") or "").strip()
            # prefer: more points, then more complete club history, then stable id/name
            cand = (points, club_history_len, str(player.get("player_id", "")), name, player, breakdown)
            if best is None or cand[:4] > best[:4]:
                best = cand
        _, _, _, _, player, breakdown = best
        return {
            "guess": guess_text,
            "matched_player": {
                "player_id": player.get("player_id"),
                "name": player.get("name"),
                "country": player.get("country"),
                "position": player.get("position"),
            },
            "breakdown": breakdown,
            "points": sum(1 for v in breakdown.values() if v),
        }

    def finalize_round(self):
        if self.state != "guessing":
            return None
        self.cancel_guess_timer()
        constraints = self.current_constraints()
        per_player = {}
        for pid in self._ordered_pids():
            guess_info = self.guesses.get(pid, {"text": ""})
            scored = self._score_guess(guess_info.get("text", ""), constraints)
            points = scored["points"]
            self.scores[pid] = self.scores.get(pid, 0) + points
            per_player[pid] = {
                "playerId": pid,
                "name": self.players.get(pid, "?"),
                **scored,
                "totalScore": self.scores[pid],
            }

        # winner / draw check
        winner_id = None
        draw = False
        max_score = max(self.scores.values()) if self.scores else 0
        if max_score >= config.WIN_SCORE:
            reached = [pid for pid, sc in self.scores.items() if sc >= config.WIN_SCORE]
            if self.scores and all(sc >= config.WIN_SCORE for sc in self.scores.values()):
                draw = True
                winner_id = None
            else:
                # highest score wins; if tie among those at/above threshold, pick deterministically
                candidates = [pid for pid, sc in self.scores.items() if sc == max_score and sc >= config.WIN_SCORE]
                candidates.sort(key=lambda p: (self.players.get(p, ""), pid))
                winner_id = candidates[0] if candidates else None

        self.round_result = {
            "round": self.round_number,
            "constraints": constraints,
            "assignments": {pid: {"attribute": attr, "value": self.selections.get(pid)} for pid, attr in self.assignments.items()},
            "results": [per_player[pid] for pid in self._ordered_pids() if pid in per_player],
            "standings": self.player_list(),
            "winnerId": winner_id,
            "draw": draw,
            "gameOver": winner_id is not None or draw,
        }
        self.history.append(self.round_result)
        if winner_id or draw:
            self.state = "game_over"
            self.winner_id = winner_id
        else:
            self.state = "result"
            self.assignment_offset = (self.assignment_offset + 1) % len(config.ATTRIBUTE_ORDER)
        return self.round_result

    def cancel_guess_timer(self):
        task = self.guess_task
        self.guess_task = None
        self.guess_deadline = None
        if task and not task.done():
            task.cancel()

    def cancel_draft_timer(self):
        task = self.draft_task
        self.draft_task = None
        self.draft_deadline = None
        if task and not task.done():
            task.cancel()

    def guess_seconds_left(self):
        if self.guess_deadline is None:
            return None
        return max(0, int(round(self.guess_deadline - time.monotonic())))

    def draft_seconds_left(self):
        if self.draft_deadline is None:
            return None
        return max(0, int(round(self.draft_deadline - time.monotonic())))

    def state_snapshot(self, pid):
        snapshot = {
            "type": "state_sync",
            "playerId": pid,
            "code": self.code,
            "isHost": pid == self.host_id,
            "hostId": self.host_id,
            "state": self.state,
            "round": self.round_number,
            "players": self.player_list(),
            "history": self.history,
            "winScore": config.WIN_SCORE,
        }
        if self.state == "drafting":
            attr = self.assignments.get(pid)
            options = self.draft_options.get(pid, [])
            if attr and not options:
                options = sample_options(attr, config.DRAFT_OPTIONS)
                self.draft_options[pid] = options
            snapshot["draft"] = {
                "attribute": attr,
                "attributeLabel": config.ATTRIBUTE_LABELS.get(attr, attr),
                "options": options,
                "selected": self.selections.get(pid),
                "submittedCount": len(self.selections),
                "requiredCount": config.ROOM_SIZE,
                "secondsLeft": self.draft_seconds_left() or 0,
                "refreshesLeft": self.draft_refreshes_left.get(pid, 0),
            }
        elif self.state == "guessing":
            snapshot["constraints"] = self.current_constraints()
            snapshot["guess"] = {
                "submitted": pid in self.guesses,
                "submittedCount": len(self.guesses),
                "requiredCount": config.ROOM_SIZE,
                "secondsLeft": self.guess_seconds_left() or 0,
            }
        elif self.state in ("result", "game_over"):
            snapshot["result"] = self.round_result
        return snapshot


class RoomManager:
    def __init__(self):
        self.rooms = {}

    def _gen_code(self):
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=5))

    def create_room(self, host_id, single_player=False):
        code = self._gen_code()
        while code in self.rooms:
            code = self._gen_code()
        self.rooms[code] = Room(code, host_id, single_player=single_player)
        return code

    def get_room(self, code):
        return self.rooms.get((code or "").upper())

    def remove_room(self, code):
        self.rooms.pop((code or "").upper(), None)


manager = RoomManager()